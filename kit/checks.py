"""Go-live readiness checks for each office, and the fix list by owner.

An office is NO-GO with any blocking finding, GO WITH FIXES with warnings only, and GO otherwise.
"""

from __future__ import annotations

from kit.dryrun import find_rule, remittances, rules_of

OWNER = "Practice owner"
MANAGER = "Office manager"
ONBOARD = "Onboarding team"
ENROLL = "Payer enrollment"

CHECKS = {
    "pms_sync_untested": ("PMS sync not tested on this office's system", "blocking", ONBOARD),
    "bank_not_linked": ("Deposit account not linked", "blocking", MANAGER),
    "eft_without_era": ("Payer pays by EFT but sends no electronic remittance (ERA)", "blocking", ENROLL),
    "paper_payer": ("Payer still sends paper EOBs", "warning", ENROLL),
    "payer_type_missing": ("Payer plan type missing", "blocking", MANAGER),
    "duplicate_payer": ("Same payer listed twice", "warning", MANAGER),
    "fee_schedule_missing": ("In-network payer with no contracted fee schedule", "blocking", MANAGER),
    "fee_above_office_fee": ("Contracted fee higher than the office fee", "warning", MANAGER),
    "no_exception_owner": ("Nobody named to work the exception queue", "blocking", MANAGER),
    "policy_open_question": ("Policy line needs the owner's decision", "blocking", OWNER),
    "policy_conflict": ("Two policy rules disagree", "blocking", OWNER),
    "adj_type_missing": ("Policy names an adjustment type the PMS does not have", "blocking", ONBOARD),
    "no_rule_for_case": ("No policy rule for a kind of balance this office sees", "blocking", OWNER),
}

NEEDED = {"contract_difference": "the contract write-off", "patient_portion": "the patient's share",
          "denied_claim": "denied claims", "overpayment": "overpayments"}


def _f(office, check, message, line=None):
    name, sev, owner = CHECKS[check]
    return dict(office=office["id"], check=check, severity=sev, owner=owner, message=message, line=line)


def run_checks(office: dict, compiled: list[dict]) -> list[dict]:
    o, out = office, []
    if not o["sync_tested"]:
        out.append(_f(o, "pms_sync_untested", f"Sync with {o['pms']} has not been tested at this office."))
    if not o["bank_linked"]:
        out.append(_f(o, "bank_not_linked", "Insurance deposits cannot be matched to the bank until the account is linked."))
    if not o["exception_owner"].strip():
        out.append(_f(o, "no_exception_owner", "Name the person who clears exceptions each day."))
    seen: dict = {}
    for p in o["payers"]:
        key = p["name"].lower()
        if key in seen and seen[key] != p["payer_id"]:
            out.append(_f(o, "duplicate_payer", f"{p['name']} is listed under payer IDs {seen[key]} and {p['payer_id']}."))
        seen.setdefault(key, p["payer_id"])
        if p["share_pct"] == 0:
            continue
        if not p["plan_type"]:
            out.append(_f(o, "payer_type_missing", f"{p['name']} has no plan type (PPO, HMO, Medicaid)."))
        if p["remit"] == "none" and p["eft"]:
            out.append(_f(o, "eft_without_era", f"{p['name']} deposits by EFT but no ERA is set up, so deposits cannot be matched to claims."))
        if p["remit"] == "paper":
            wk = f" ERA enrollment planned to be live by week {p['era_live_week']}." if p["era_live_week"] else ""
            out.append(_f(o, "paper_payer", f"{p['name']} ({p['share_pct']}% of payments) still sends paper EOBs.{wk}"))
        if p["plan_type"] in ("PPO", "Premier"):
            sched = o["fees"].get(p["name"])
            if sched is None:
                out.append(_f(o, "fee_schedule_missing", f"No contracted fee schedule for {p['name']}, so allowed amounts cannot be checked."))
            else:
                for code, fee in sched.items():
                    if fee > o["fees"]["Office fee"][code]:
                        out.append(_f(o, "fee_above_office_fee", f"{p['name']} fee for {code} (${fee}) is above the office fee (${o['fees']['Office fee'][code]})."))

    rules = rules_of(compiled)
    for x in compiled:
        if x["kind"] == "question":
            text = o["policy"][x["line"] - 1]["text"] if 0 < x["line"] <= len(o["policy"]) else ""
            out.append(_f(o, "policy_open_question", f"Line {x['line']}: \"{text}\"", line=x["line"]))
    known = set(o["adjustment_types"])
    for x in compiled:
        r = x.get("rule")
        if x["kind"] == "rule" and r and r["action"] == "write_off" and r["adjustment_type"] and r["adjustment_type"] not in known:
            out.append(_f(o, "adj_type_missing", f"Line {x['line']} uses \"{r['adjustment_type']}\", which is not set up in {o['pms']}.", line=x["line"]))
    out += _conflicts(o, compiled)

    # Coverage: every kind of balance this office's own payments produce needs a rule.
    live = [p for p in o["payers"] if p["share_pct"] > 0 and p["plan_type"]]
    for case, label in NEEDED.items():
        missing = [p["name"] for p in live if find_rule(rules, case, p)[0] is None and not find_rule(rules, case, p)[1]]
        if case == "patient_portion":
            missing = [m for m in missing if next(p for p in live if p["name"] == m)["plan_type"] != "Medicaid"]
        if missing:
            out.append(_f(o, "no_rule_for_case", f"No rule for {label} ({', '.join(missing)})."))
    return out


def _conflicts(o, compiled):
    out, rules = [], [(x["line"], x["rule"]) for x in compiled if x["kind"] == "rule" and x.get("rule")]
    for i, (la, a) in enumerate(rules):
        for lb, b in rules[i + 1:]:
            if a["case"] != b["case"] or a["action"] == b["action"]:
                continue
            same_scope = a["payer_scope"] == b["payer_scope"] and sorted(a["payer_names"]) == sorted(b["payer_names"])
            if same_scope:
                out.append(_f(o, "policy_conflict", f"Lines {la} and {lb} give different actions for the same balance.", line=la))
    return out


def verdict(findings: list[dict]) -> str:
    if any(f["severity"] == "blocking" for f in findings):
        return "NO-GO"
    return "GO WITH FIXES" if findings else "GO"


def summarize(office: dict, findings: list[dict], dry: dict) -> dict:
    return dict(id=office["id"], name=office["name"], kind=office["kind"], pms=office["pms"],
                verdict=verdict(findings),
                blocking=sum(f["severity"] == "blocking" for f in findings),
                warnings=sum(f["severity"] == "warning" for f in findings), dry=dry)


__all__ = ["CHECKS", "run_checks", "verdict", "summarize", "remittances"]
