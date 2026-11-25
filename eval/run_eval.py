"""Two evals.

1. The checks: 16 problems planted in a clean five-office intake (kit/intake.py PLANTS), each run on
   its own and all together, using the labelled policy answers so this measures the checks alone.
2. Claude's reading of the write-off policies: every policy line (as received and after the owner's
   answers, 3 runs each) scored against its label. A line is right when the rule matches on case,
   action, payer scope, payer names, dollar limit and adjustment type, or when a vague line becomes
   a question. A critical error is a write-off the policy did not clearly allow.

Writes eval/results/eval_results.json. Part 2 needs the cached Claude runs in data/compiled/.
"""

from __future__ import annotations

import json
import os

from kit import checks, intake, policy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _found(group):
    out = set()
    for o in group:
        for f in checks.run_checks(o, policy.from_labels(o)):
            out.add((o["id"], f["check"]))
    return out


def eval_checks() -> dict:
    base = _found(intake.clean_group())
    alone = []
    for i, (oid, label, expect, _) in enumerate(intake.PLANTS):
        got = _found(intake.with_plant(i)) - base
        want = {(oid, c) for c in expect}
        alone.append(dict(plant=label, office=oid, expected=sorted(expect), caught=want <= got,
                          extra=sorted(c for _, c in got - want)))
    want_all = {(oid, c) for oid, _, exp, _ in intake.PLANTS for c in exp}
    got_all = _found(intake.as_received()) - base
    together_caught = sum(1 for oid, _, exp, _ in intake.PLANTS if {(oid, c) for c in exp} <= got_all)
    return dict(total=len(intake.PLANTS), clean_extra=sorted(base - {(o["id"], "paper_payer") for o in intake.clean_group()}),
                baseline=sorted(base), alone_caught=sum(a["caught"] for a in alone),
                alone_extra=sum(len(a["extra"]) for a in alone), together_caught=together_caught,
                together_false_positives=sorted(got_all - want_all), alone=alone)


def _norm(r):
    return (r["case"], r["action"], r["payer_scope"], tuple(sorted(n.lower() for n in r["payer_names"])),
            None if r["max_amount"] is None else float(r["max_amount"]), (r["adjustment_type"] or "").lower() or None)


def score_line(expect: dict, got: dict | None) -> tuple[bool, bool, str]:
    """(correct, critical, what happened)."""
    if got is None:
        return False, False, "line missing from the answer"
    k = expect["kind"]
    if k == "question":
        if got["kind"] == "question":
            return True, False, "asked the owner"
        crit = got["kind"] == "rule" and got["rule"] and got["rule"]["action"] == "write_off"
        return False, bool(crit), "guessed a rule for a vague line"
    if k == "not_posting":
        return got["kind"] == "not_posting", got["kind"] == "rule" and got["rule"]["action"] == "write_off", \
            "skipped" if got["kind"] == "not_posting" else "treated as a posting rule"
    # expected a rule
    if got["kind"] == "question":
        return bool(expect.get("accept_question")), False, "asked the owner instead"
    if got["kind"] != "rule" or not got["rule"]:
        return False, False, "no rule"
    e, g = expect["rule"], got["rule"]
    crit = g["action"] == "write_off" and (e["action"] != "write_off" or
                                           (e["max_amount"] is not None and (g["max_amount"] is None or g["max_amount"] > e["max_amount"])))
    if _norm(e) == _norm(g):
        return True, False, "rule matches"
    fields = ("case", "action", "payer scope", "payer names", "dollar limit", "adjustment type")
    diff = [f for f, a, b in zip(fields, _norm(e), _norm(g)) if a != b]
    return False, crit, "differs on " + ", ".join(diff)


def eval_policy(runs: int = 3) -> dict | None:
    rows, have = [], True
    for st in ("as_received", "after_fixes"):
        for o in intake.state(st):
            for run in range(1, runs + 1):
                d = policy.load(o, st, run)
                if d is None:
                    have = False
                    continue
                by_line = {x["line"]: x for x in d["lines"]}
                for i, line in enumerate(o["policy"]):
                    ok, crit, what = score_line(line["expect"], by_line.get(i + 1))
                    rows.append(dict(state=st, office=o["id"], run=run, line=i + 1, text=line["text"],
                                     expected=line["expect"]["kind"], got=(by_line.get(i + 1) or {}).get("kind"),
                                     question=(by_line.get(i + 1) or {}).get("question_for_owner"),
                                     correct=ok, critical=crit, what=what))
    if not rows:
        return None
    per_run = {}
    for r in rows:
        k = r["run"]
        per_run.setdefault(k, {"lines": 0, "correct": 0, "critical": 0})
        per_run[k]["lines"] += 1
        per_run[k]["correct"] += r["correct"]
        per_run[k]["critical"] += r["critical"]
    vague = [r for r in rows if r["expected"] == "question"]
    clear = [r for r in rows if r["expected"] == "rule"]
    return dict(complete=have, runs=per_run, total_lines=len(rows), correct=sum(r["correct"] for r in rows),
                critical=sum(r["critical"] for r in rows),
                clear=dict(n=len(clear), correct=sum(r["correct"] for r in clear)),
                vague=dict(n=len(vague), asked=sum(r["correct"] for r in vague)),
                misses=[r for r in rows if not r["correct"]], rows=rows)


def main():
    out = dict(checks=eval_checks(), policy=eval_policy())
    os.makedirs(os.path.join(ROOT, "eval", "results"), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, "eval", "results", "eval_results.json"), "w"), indent=1)
    c = out["checks"]
    print(f"Checks: clean system extra findings {len(c['clean_extra'])}; each plant alone {c['alone_caught']}/{c['total']} "
          f"caught, {c['alone_extra']} extra; all together {c['together_caught']}/{c['total']} caught, "
          f"{len(c['together_false_positives'])} false positives")
    p = out["policy"]
    if p is None:
        print("Policy reading: no Claude runs cached yet (run python3 -m kit.policy --live)")
    else:
        print(f"Policy reading: {p['correct']}/{p['total_lines']} lines right over {len(p['runs'])} runs; "
              f"clear lines {p['clear']['correct']}/{p['clear']['n']}, vague lines asked {p['vague']['asked']}/{p['vague']['n']}, "
              f"critical {p['critical']}")
        for m in p["misses"]:
            print("  miss", m["state"], m["office"], "run", m["run"], "line", m["line"], m["what"])


if __name__ == "__main__":
    main()
