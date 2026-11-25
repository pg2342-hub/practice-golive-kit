"""Turn an office manager's write-off policy (plain English) into posting rules.

Claude reads the numbered policy lines and returns, through a JSON schema, one entry per line:
a rule, an open question for the owner, or "not about posting". The prompt tells it to ask
instead of guessing whenever a line leaves out who, which payer, how much, or what to do.

Results are cached in data/compiled/<office>_<state>_run<N>.json, so tests and the demo page run
without an API key. `python3 -m kit.policy --live` refreshes them (needs ANTHROPIC_API_KEY and the
`anthropic` package; the GitHub Action does this).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time

MODEL = "claude-opus-5-5"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "compiled")

CASES = ["contract_difference", "patient_portion", "small_balance", "denied_claim", "overpayment",
         "secondary_insurance", "other"]
ACTIONS = ["write_off", "bill_patient", "hold_for_review", "refund_review", "bill_secondary"]
SCOPES = ["all", "ppo", "hmo", "medicaid", "named"]

_RULE = {
    "type": "object",
    "properties": {
        "case": {"type": "string", "enum": CASES},
        "action": {"type": "string", "enum": ACTIONS},
        "payer_scope": {"type": "string", "enum": SCOPES},
        "payer_names": {"type": "array", "items": {"type": "string"}},
        "max_amount": {"type": ["number", "null"]},
        "adjustment_type": {"type": ["string", "null"]},
    },
    "required": ["case", "action", "payer_scope", "payer_names", "max_amount", "adjustment_type"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["rule", "question", "not_posting"]},
                    "rule": {"anyOf": [_RULE, {"type": "null"}]},
                    "question_for_owner": {"type": ["string", "null"]},
                },
                "required": ["line", "kind", "rule", "question_for_owner"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}

SYSTEM = """You set up insurance payment posting for a dental office. The office manager wrote the
office's write-off policy in plain English. Turn each numbered line into exactly one entry.

kind = "rule" when the line says clearly what to do with one kind of balance:
- case: contract_difference (office fee minus the payer's allowed amount), patient_portion
  (deductible, coinsurance, copay), small_balance (a small amount left after insurance),
  denied_claim, overpayment, secondary_insurance, or other.
- action: write_off, bill_patient, hold_for_review (a person decides), refund_review, bill_secondary.
- payer_scope: all, ppo, hmo, medicaid (Medicaid, including Denti-Cal / Medi-Cal Dental), or named
  (then list the payers in payer_names exactly as written). Use "all" when the line names no payer.
- max_amount: the dollar limit if the line gives exactly one, else null.
- adjustment_type: the adjustment name the line gives, copied exactly, else null.

kind = "question" when acting on the line would mean guessing: it leaves out the amount, the payer,
or the action, gives two possible values, says "case by case" without a rule, or points to habits
or other documents ("like we always do", "same as the other offices"). Write the one question the
owner must answer. Never turn a vague line into a write-off.

kind = "not_posting" when the line is not about posting payments.

If two lines contradict each other, still record each one as written; a later check finds conflicts.
The office's adjustment types are listed for reference; copy the name the policy uses even if it is
not on that list."""


def policy_text(office: dict) -> str:
    return "\n".join(f"{i + 1}. {line['text']}" for i, line in enumerate(office["policy"]))


def _key(office: dict) -> str:
    return hashlib.sha256(policy_text(office).encode()).hexdigest()[:12]


def from_labels(office: dict) -> list[dict]:
    """The labelled answer for each line (ground truth, used by the checks' own eval)."""
    out = []
    for i, line in enumerate(office["policy"]):
        e = line["expect"]
        out.append({"line": i + 1, "kind": e["kind"], "rule": e.get("rule"),
                    "question_for_owner": "label" if e["kind"] == "question" else None})
    return out


def call_claude(office: dict) -> tuple[list[dict], dict]:
    import anthropic  # only needed for live runs

    client = anthropic.Anthropic()
    user = (f"Office: {office['name']} ({office['kind']}), PMS {office['pms']}.\n"
            f"Payers: {', '.join(p['name'] + ' (' + (p['plan_type'] or 'type not given') + ')' for p in office['payers'])}.\n"
            f"Adjustment types set up in the PMS: {', '.join(office['adjustment_types'])}.\n\n"
            f"Write-off policy:\n{policy_text(office)}")
    t0 = time.time()
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"refused for {office['id']}")
    text = next(b.text for b in resp.content if b.type == "text")
    usage = {"model": resp.model, "input_tokens": resp.usage.input_tokens,
             "output_tokens": resp.usage.output_tokens, "seconds": round(time.time() - t0, 1)}
    return json.loads(text)["lines"], usage


def cache_path(office: dict, state: str, run: int) -> str:
    return os.path.join(CACHE, f"{office['id']}_{state}_run{run}.json")


def load(office: dict, state: str, run: int = 1) -> dict | None:
    p = cache_path(office, state, run)
    if not os.path.exists(p):
        return None
    d = json.load(open(p))
    return d if d.get("policy_sha") == _key(office) else None


def compiled(office: dict, state: str, source: str = "claude", run: int = 1) -> list[dict]:
    """Rules for an office. source="labels" uses the labelled answers; "claude" the cached run."""
    if source == "labels":
        return from_labels(office)
    d = load(office, state, run)
    if d is None:
        raise FileNotFoundError(f"no current Claude run for {office['id']} {state} run {run}; "
                                "run `python3 -m kit.policy --live`")
    return d["lines"]


def main() -> None:
    from kit import intake

    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="call Claude and refresh the cache")
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()
    if not a.live:
        for st in ("as_received", "after_fixes"):
            for o in intake.state(st):
                print(st, o["id"], "cached" if load(o, st) else "missing")
        return
    os.makedirs(CACHE, exist_ok=True)
    for st in ("as_received", "after_fixes"):
        for o in intake.state(st):
            for run in range(1, a.runs + 1):
                if load(o, st, run):
                    continue
                lines, usage = call_claude(o)
                json.dump({"office": o["id"], "state": st, "run": run, "policy_sha": _key(o),
                           "policy": policy_text(o), "usage": usage, "lines": lines},
                          open(cache_path(o, st, run), "w"), indent=1)
                print(st, o["id"], "run", run, usage)


if __name__ == "__main__":
    main()
