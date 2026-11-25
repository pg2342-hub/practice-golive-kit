"""Dry run: replay one week of made-up insurance remittance lines through an office's setup.

Each line is one procedure on one insurer payment (like a line on an ERA or EOB). The dry run asks,
for every line, whether it could be posted with no person touching it, given the office's payers,
fee schedules, adjustment types and the rules read from its write-off policy. Lines that need a
person are split into two kinds:
- held by policy: the office chose to look at these (denials, overpayments). Expected.
- stuck on setup: something is missing or unclear in the setup. These are what onboarding fixes.
"""

from __future__ import annotations

import random

from kit.intake import CODES

COINS = {"preventive": 0.0, "basic": 0.2, "major": 0.5}
SPECIFIC = {"named": 3, "ppo": 2, "hmo": 2, "medicaid": 2, "all": 1}


def remittances(office: dict, week: int | None = None) -> list[dict]:
    """One week of lines for the office, the same every run (seeded by office id and week)."""
    rng = random.Random(f"{office['id']}-{week or 0}")
    payers = [p for p in office["payers"] if p["share_pct"] > 0]
    weights = [p["share_pct"] for p in payers]
    out = []
    for n in range(office["lines_per_week"]):
        p = rng.choices(payers, weights)[0]
        code = rng.choice(list(CODES))
        fee = CODES[code][1]
        if p["plan_type"] == "Medicaid":
            contracted = round(fee * 0.40)
        else:
            # what the payer actually allows: its real contract (made up), which the office's
            # fee schedule file should match
            contracted = round(fee * _true_pct(p["name"]))
        r = rng.random()
        status = "paid"
        allowed = contracted
        if r < 0.07:
            status = "denied"
        elif r < 0.10:
            status = "overpaid"
        elif r < 0.14 and p["plan_type"] != "Medicaid":
            status = "underpaid"
            allowed = contracted - rng.randint(8, 40)
        coins = 0.0 if p["plan_type"] == "Medicaid" else COINS[CODES[code][2]]
        patient = round(allowed * coins, 2)
        if status == "paid" and patient == 0 and rng.random() < 0.15 and p["plan_type"] != "Medicaid":
            patient = round(rng.uniform(1, 9.5), 2)  # a small leftover (frequency limits, rounding)
        paid = 0.0 if status == "denied" else round(allowed - patient, 2)
        if status == "overpaid":
            paid = round(paid + rng.randint(10, 60), 2)
        out.append(dict(n=n + 1, payer=p["name"], plan_type=p["plan_type"], code=code, fee=fee,
                        allowed=0 if status == "denied" else allowed, patient=0 if status == "denied" else patient,
                        paid=paid, status=status))
    return out


def _true_pct(name: str) -> float:
    from kit.intake import _PCT
    return _PCT.get(name, 0.60)


def _matches(rule: dict, payer: dict) -> bool:
    s = rule["payer_scope"]
    if s == "all":
        return True
    if s == "named":
        nm = payer["name"].lower()
        return any(x.lower() in nm or nm in x.lower() for x in rule["payer_names"])
    return {"ppo": "PPO", "hmo": "HMO", "medicaid": "Medicaid"}[s] == payer["plan_type"]


def find_rule(rules: list[dict], case: str, payer: dict, amount: float | None = None):
    """The most specific rule for this case and payer. Returns (rule, conflict)."""
    hits = [r for r in rules if r["case"] == case and _matches(r, payer)
            and (r["max_amount"] is None or amount is None or amount < r["max_amount"])]
    if not hits:
        return None, False
    top = max(SPECIFIC[r["payer_scope"]] for r in hits)
    best = [r for r in hits if SPECIFIC[r["payer_scope"]] == top]
    if len({r["action"] for r in best}) > 1:
        return None, True
    return best[0], False


def rules_of(lines: list[dict]) -> list[dict]:
    return [x["rule"] for x in lines if x["kind"] == "rule" and x.get("rule")]


def post_line(office: dict, rules: list[dict], line: dict, week: int | None = None) -> dict:
    payer = next(p for p in office["payers"] if p["name"] == line["payer"] and p["share_pct"] > 0)
    steps, adj_known = [], set(office["adjustment_types"])

    def stuck(reason):
        return {"result": "stuck", "reason": reason, "steps": steps}

    def held(reason):
        return {"result": "held", "reason": reason, "steps": steps}

    if not office["sync_tested"]:
        return stuck("PMS sync not tested")
    if not office["bank_linked"]:
        return stuck("Deposit cannot be matched to the bank")
    if payer["remit"] == "none":
        return stuck("EFT deposit with no ERA to match it to")
    if payer["remit"] == "paper" and (week is None or payer["era_live_week"] is None or week < payer["era_live_week"]):
        return stuck("Paper EOB, keyed by hand until ERA is live")
    if not payer["plan_type"]:
        return stuck("Payer plan type unknown")

    if line["status"] == "denied":
        r, clash = find_rule(rules, "denied_claim", payer, line["fee"])
        if clash:
            return stuck("Policy rules disagree on denials")
        if r is None:
            return stuck("No rule for denied claims")
        if r["action"] == "hold_for_review":
            return held("Denied claim, held for review")
        if not r["adjustment_type"] or r["adjustment_type"] not in adj_known:
            return stuck("Adjustment type not set up in the PMS")
        steps.append(("write_off", line["fee"], r["adjustment_type"]))
        return {"result": "auto", "reason": None, "steps": steps}

    if line["status"] == "overpaid":
        r, clash = find_rule(rules, "overpayment", payer)
        if r is None or clash:
            return stuck("No rule for overpayments")
        return held("Overpayment, held for refund review")

    diff = line["fee"] - line["allowed"]
    if diff > 0:
        sched = office["fees"].get(payer["name"])
        if sched is None and payer["plan_type"] in ("PPO", "Premier"):
            return stuck("No fee schedule to check the allowed amount")
        if sched is not None and line["allowed"] < sched[line["code"]]:
            return stuck("Paid below the contracted fee")
        r, clash = find_rule(rules, "contract_difference", payer)
        if clash:
            return stuck("Policy rules disagree on the contract write-off")
        if r is None:
            return stuck("No write-off rule for this payer")
        if r["action"] != "write_off":
            return stuck("Contract difference not written off by policy")
        if not r["adjustment_type"] or r["adjustment_type"] not in adj_known:
            return stuck("Adjustment type not set up in the PMS")
        steps.append(("write_off", diff, r["adjustment_type"]))

    if line["patient"] > 0:
        # The patient's share is always billed at posting. A small-balance write-off is a later,
        # account-level step on what is left after the patient pays, never a write-off on the EOB line.
        r, clash = find_rule(rules, "patient_portion", payer)
        if r is None or clash or r["action"] != "bill_patient":
            return stuck("No rule for the patient's share")
        steps.append(("bill_patient", line["patient"], None))
        small, _ = find_rule(rules, "small_balance", payer, line["patient"])
        if small and small["action"] == "write_off" and small["max_amount"] is not None:
            if not small["adjustment_type"] or small["adjustment_type"] not in adj_known:
                return stuck("Adjustment type not set up in the PMS")
            steps.append(("small_balance_later", line["patient"], small["adjustment_type"]))
    steps.append(("post_payment", line["paid"], None))
    return {"result": "auto", "reason": None, "steps": steps}


def dry_run(office: dict, rules: list[dict], week: int | None = None) -> dict:
    lines = remittances(office, week)
    res = [post_line(office, rules, ln, week) for ln in lines]
    reasons: dict = {}
    for r in res:
        if r["reason"]:
            k = (r["result"], r["reason"])
            reasons[k] = reasons.get(k, 0) + 1
    n = len(res)
    auto = sum(r["result"] == "auto" for r in res)
    held = sum(r["result"] == "held" for r in res)
    return dict(lines=n, auto=auto, held=held, stuck=n - auto - held,
                reasons=[dict(kind=k[0], reason=k[1], count=v)
                         for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])])
