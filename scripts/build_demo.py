"""Build docs/index.html (the GitHub Pages demo) from the kit's own output.

    python3 scripts/build_demo.py            # needs the cached Claude runs in data/
    python3 scripts/build_demo.py --labels   # local preview with the labelled policy answers
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from eval.run_eval import eval_checks, eval_policy  # noqa: E402
from kit import checks, dryrun, health, intake, notes, policy  # noqa: E402

CASE = {"contract_difference": "contract difference", "patient_portion": "patient's share",
        "small_balance": "small balance", "denied_claim": "denied claim", "overpayment": "overpayment",
        "secondary_insurance": "secondary insurance", "other": "other balance"}
ACT = {"write_off": "write off", "bill_patient": "bill the patient", "hold_for_review": "hold for a person",
       "refund_review": "refund review", "bill_secondary": "bill secondary insurance"}
SCOPE = {"all": "all payers", "ppo": "PPO payers", "hmo": "HMO payers", "medicaid": "Medicaid"}


def say(r: dict) -> str:
    who = ", ".join(r["payer_names"]) if r["payer_scope"] == "named" else SCOPE[r["payer_scope"]]
    s = f"{CASE[r['case']].capitalize()}, {who}: {ACT[r['action']]}"
    if r["max_amount"] is not None:
        s += f" if under ${r['max_amount']:g}"
    if r["adjustment_type"]:
        s += f" ({r['adjustment_type']})"
    return s


def view(state: str, src: str) -> list[dict]:
    out = []
    for o in intake.state(state):
        comp = policy.compiled(o, state, src)
        f = checks.run_checks(o, comp)
        d = dryrun.dry_run(o, dryrun.rules_of(comp))
        lines = []
        for i, ln in enumerate(o["policy"]):
            x = next((c for c in comp if c["line"] == i + 1), None)
            lines.append(dict(n=i + 1, text=ln["text"], kind=x["kind"] if x else "missing",
                              read=say(x["rule"]) if x and x["kind"] == "rule" and x.get("rule") else
                              (x.get("question_for_owner") if x and x["kind"] == "question" else
                               ("Not about posting" if x and x["kind"] == "not_posting" else ""))))
        out.append(dict(checks.summarize(o, f, d), findings=f, policy=lines))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", action="store_true")
    a = ap.parse_args()
    src = "labels" if a.labels else "claude"
    hl, note = [], {}
    for o in intake.state("after_fixes"):
        sim = health.simulate(o, dryrun.rules_of(policy.compiled(o, "after_fixes", src)))
        hl.append(sim)
        for wk in notes.NOTE_WEEKS:
            fx = notes.facts(sim, wk, health.TARGET)
            c = notes.load(o["id"], wk, fx)
            if c and not c["ungrounded"]:
                note[f"{o['id']}-{wk}"] = c["note"]
    ce, pe = eval_checks(), eval_policy()
    usage = None
    if pe:
        runs = [json.load(open(os.path.join(policy.CACHE, fn))) for fn in sorted(os.listdir(policy.CACHE)) if fn.endswith(".json")]
        usage = dict(calls=len(runs), model=runs[0]["usage"]["model"],
                     seconds=round(sum(r["usage"]["seconds"] for r in runs) / len(runs), 1),
                     tokens_in=sum(r["usage"]["input_tokens"] for r in runs),
                     tokens_out=sum(r["usage"]["output_tokens"] for r in runs))
    payload = dict(
        preview=src == "labels", group=intake.GROUP_NAME, target=health.TARGET, review_weeks=health.REVIEW_WEEKS,
        views={"as_received": view("as_received", src), "after_fixes": view("after_fixes", src)},
        health=hl, notes=note, scenario=[dict(office=s["office"], what=s["what"]) for s in health.SCENARIO],
        checks=[dict(id=k, name=v[0], severity=v[1], owner=v[2]) for k, v in checks.CHECKS.items()],
        plants=[dict(office=o, label=lab) for o, lab, _, _ in intake.PLANTS],
        eval=dict(checks={k: ce[k] for k in ("total", "alone_caught", "alone_extra", "together_caught")}
                  | {"fp": len(ce["together_false_positives"]), "clean": len(ce["clean_extra"])},
                  policy=None if pe is None else {k: pe[k] for k in ("total_lines", "correct", "critical", "clear", "vague")}
                  | {"runs": len(pe["runs"]), "misses": [{k: m[k] for k in ("state", "office", "run", "line", "text", "what")} for m in pe["misses"]]},
                  usage=usage))
    tpl = open(os.path.join(ROOT, "docs", "template.html"), encoding="utf-8").read()
    out = tpl.replace("/*DATA*/null", json.dumps(payload))
    dst = os.path.join(ROOT, "docs", "index.html")
    open(dst, "w", encoding="utf-8").write(out)
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "demo_chrome.py"), dst, "--repo", "practice-golive-kit"], check=True)
    print("wrote docs/index.html", "(preview with labels)" if a.labels else "")


if __name__ == "__main__":
    main()
