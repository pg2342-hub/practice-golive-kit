"""The made-up five-office dental group, its onboarding intake, and the problems planted in it.

Everything here is invented. Payer names and CDT procedure codes are public; fees, shares,
offices, staff and policies are made up and do not describe any real practice.

An office's intake is what an onboarding call collects: the practice management system (PMS),
the bank account for deposits, who works the exception queue, the payers and how each one pays,
contracted fee schedules, the PMS adjustment types, and the office manager's write-off policy in
plain English. Each policy line carries a label (what a careful reader should turn it into), which
the eval uses to score Claude's reading and the checks' own eval uses as ground truth.
"""

from __future__ import annotations

import copy

GROUP_NAME = "A made-up five-office dental group"

# CDT code -> (plain name, office fee, coverage class). Coverage class sets coinsurance:
# preventive 0%, basic 20%, major 50% (a common PPO pattern, used here as an assumption).
CODES = {
    "D0120": ("Periodic exam", 75, "preventive"),
    "D0150": ("Comprehensive exam", 120, "preventive"),
    "D0274": ("Four bitewing x-rays", 85, "preventive"),
    "D1110": ("Adult cleaning", 140, "preventive"),
    "D1120": ("Child cleaning", 95, "preventive"),
    "D2391": ("One-surface back-tooth filling", 210, "basic"),
    "D2740": ("Porcelain crown", 1450, "major"),
}

# Contracted fee as a share of the office fee, per payer (made up).
_PCT = {"Delta Dental PPO": 0.62, "MetLife": 0.66, "Cigna": 0.60, "Guardian": 0.64,
        "Aetna": 0.61, "United Concordia": 0.59, "Delta Dental Premier": 0.82}


def _fees(payer: str) -> dict:
    return {c: round(v[1] * _PCT[payer]) for c, v in CODES.items()}


def _payer(name, plan, pid, share, remit="ERA", eft=True, era_live_week=None):
    return dict(name=name, plan_type=plan, payer_id=pid, share_pct=share, remit=remit,
                eft=eft, era_live_week=era_live_week)


def L(text, kind, **rule):
    """One policy line and its label. kind: rule, question or not_posting."""
    out = {"text": text, "expect": {"kind": kind}}
    if kind == "rule":
        r = dict(case=rule["case"], action=rule["action"], payer_scope=rule.get("scope", "all"),
                 payer_names=rule.get("names", []), max_amount=rule.get("max"),
                 adjustment_type=rule.get("adj"))
        out["expect"]["rule"] = r
        if rule.get("accept_question"):
            out["expect"]["accept_question"] = True
    return out


def clean_group() -> list[dict]:
    """The group as it should be on go-live day: every office ready, policies settled."""
    offices = [
        dict(id="OAK", name="Oak", kind="General, 3 dentists", pms="Dentrix G7", sync_tested=True,
             bank_linked=True, exception_owner="Billing coordinator", lines_per_week=140,
             exception_hours_per_week=6,
             adjustment_types=["PPO Write-Off", "Small Balance W/O", "Insurance Refund", "Premier Adj"],
             payers=[_payer("Delta Dental PPO", "PPO", "94276", 34),
                     _payer("Delta Dental Premier", "Premier", "94276P", 10),
                     _payer("MetLife", "PPO", "65978", 18),
                     _payer("Cigna", "PPO", "62308", 14),
                     _payer("Guardian", "PPO", "64246", 12),
                     _payer("Aetna", "PPO", "60054", 12)],
             policy=[
                 L("For PPO plans we are in network with, write off the difference between our fee and "
                   "the allowed amount, using the PPO Write-Off adjustment.", "rule",
                   case="contract_difference", action="write_off", scope="ppo", adj="PPO Write-Off"),
                 L("Delta Dental Premier: write off the difference down to the Premier allowed amount "
                   "with the Premier Adj adjustment.", "rule", case="contract_difference",
                   action="write_off", scope="named", names=["Delta Dental Premier"], adj="Premier Adj"),
                 L("Deductibles and coinsurance go on the patient's account; we never write those off.",
                   "rule", case="patient_portion", action="bill_patient"),
                 L("A balance under $5 left after insurance can be written off as Small Balance W/O.",
                   "rule", case="small_balance", action="write_off", max=5, adj="Small Balance W/O"),
                 L("Denied claims are never written off automatically. Hold them for the billing "
                   "coordinator.", "rule", case="denied_claim", action="hold_for_review"),
                 L("If an insurance company pays more than it should, flag it for a refund review.",
                   "rule", case="overpayment", action="refund_review"),
                 L("The office is closed for lunch from 12 to 1.", "not_posting"),
             ]),
        dict(id="CED", name="Cedar", kind="Pediatric, 2 dentists", pms="Dentrix G7", sync_tested=True,
             bank_linked=True, exception_owner="Office manager", lines_per_week=120,
             exception_hours_per_week=5,
             adjustment_types=["PPO Write-Off", "Medi-Cal W/O", "Small Balance W/O", "Insurance Refund"],
             payers=[_payer("Denti-Cal", "Medicaid", "DCAL", 38, remit="paper", eft=False, era_live_week=6),
                     _payer("Delta Dental PPO", "PPO", "94276", 30),
                     _payer("Cigna", "PPO", "62308", 12),
                     _payer("United Concordia", "PPO", "CX021", 10),
                     _payer("MetLife", "PPO", "65978", 10)],
             policy=[
                 L("Write off PPO contractual differences with PPO Write-Off.", "rule",
                   case="contract_difference", action="write_off", scope="ppo", adj="PPO Write-Off"),
                 L("Denti-Cal: write off whatever Denti-Cal does not pay, using Medi-Cal W/O. We cannot "
                   "bill those families.", "rule", case="contract_difference", action="write_off",
                   scope="medicaid", adj="Medi-Cal W/O"),
                 L("Small balances under $3 get written off as Small Balance W/O.", "rule",
                   case="small_balance", action="write_off", max=3, adj="Small Balance W/O"),
                 L("The patient's share goes to the family's account.", "rule",
                   case="patient_portion", action="bill_patient"),
                 L("Denials go to the office manager for review.", "rule", case="denied_claim",
                   action="hold_for_review"),
                 L("Overpayments: hold for refund review.", "rule", case="overpayment",
                   action="refund_review"),
             ]),
        dict(id="BIR", name="Birch", kind="General, 2 dentists", pms="Dentrix Ascend", sync_tested=True,
             bank_linked=True, exception_owner="Front desk lead", lines_per_week=110,
             exception_hours_per_week=4,
             adjustment_types=["Contractual Adj", "Small Bal Adj", "Refund Review"],
             payers=[_payer("Delta Dental PPO", "PPO", "94276", 36),
                     _payer("MetLife", "PPO", "65978", 22),
                     _payer("Guardian", "PPO", "64246", 16),
                     _payer("Cigna", "PPO", "62308", 14),
                     _payer("Aetna", "PPO", "60054", 12)],
             policy=[
                 L("PPO plans: write off the contractual difference as Contractual Adj.", "rule",
                   case="contract_difference", action="write_off", scope="ppo", adj="Contractual Adj"),
                 L("The patient owes the deductible and coinsurance; bill the patient.", "rule",
                   case="patient_portion", action="bill_patient"),
                 L("Anything under $10 left after insurance, write off as Small Bal Adj.", "rule",
                   case="small_balance", action="write_off", max=10, adj="Small Bal Adj"),
                 L("Overpayments go to Refund Review.", "rule", case="overpayment",
                   action="refund_review"),
                 L("Denials go to Maria's queue.", "rule", case="denied_claim", action="hold_for_review"),
                 L("For Guardian denials, Dr. Lee reviews each one before anything is resubmitted.",
                   "rule", case="denied_claim", action="hold_for_review", scope="named",
                   names=["Guardian"]),
             ]),
        dict(id="MAP", name="Maple", kind="General, 4 dentists", pms="Open Dental", sync_tested=True,
             bank_linked=True, exception_owner="Billing coordinator", lines_per_week=170,
             exception_hours_per_week=7,
             adjustment_types=["PPO Writeoff", "Small Balance", "Overpayment Hold"],
             payers=[_payer("Delta Dental PPO", "PPO", "94276", 30),
                     _payer("MetLife", "PPO", "65978", 20),
                     _payer("Cigna", "PPO", "62308", 18),
                     _payer("Aetna", "PPO", "60054", 16),
                     _payer("Guardian", "PPO", "64246", 16)],
             policy=[
                 L("In-network PPO: write off the difference between our fee and the allowed amount "
                   "(PPO Writeoff).", "rule", case="contract_difference", action="write_off",
                   scope="ppo", adj="PPO Writeoff"),
                 L("Patient portions always go to the patient.", "rule", case="patient_portion",
                   action="bill_patient"),
                 L("Write off balances under $5 as Small Balance.", "rule", case="small_balance",
                   action="write_off", max=5, adj="Small Balance"),
                 L("Never write off a denied claim; it goes to the billing coordinator.", "rule",
                   case="denied_claim", action="hold_for_review"),
                 L("Overpayments go to Overpayment Hold for a refund review.", "rule",
                   case="overpayment", action="refund_review", adj="Overpayment Hold"),
             ]),
        dict(id="WIL", name="Willow", kind="General, 1 dentist, acquired this year", pms="Eaglesoft",
             sync_tested=True, bank_linked=True, exception_owner="Office manager", lines_per_week=70,
             exception_hours_per_week=3,
             adjustment_types=["PPO DISC", "SMALL BAL", "INS REFUND"],
             payers=[_payer("Delta Dental PPO", "PPO", "94276", 40),
                     _payer("Aetna", "PPO", "60054", 22),
                     _payer("Cigna", "PPO", "62308", 20),
                     _payer("United Concordia", "PPO", "CX021", 10, remit="paper", eft=False,
                            era_live_week=5),
                     _payer("MetLife", "PPO", "65978", 8)],
             policy=[
                 L("PPO differences are written off with PPO DISC.", "rule", case="contract_difference",
                   action="write_off", scope="ppo", adj="PPO DISC"),
                 L("Patient portion goes to the patient.", "rule", case="patient_portion",
                   action="bill_patient"),
                 L("Write off balances under $5 as SMALL BAL.", "rule", case="small_balance",
                   action="write_off", max=5, adj="SMALL BAL"),
                 L("Cigna claims denied for missing x-rays get resubmitted with the x-rays, never "
                   "written off. Other denials also go to the office manager.", "rule",
                   case="denied_claim", action="hold_for_review"),
                 L("Overpayments: INS REFUND, after the office manager reviews.", "rule",
                   case="overpayment", action="refund_review", adj="INS REFUND"),
             ]),
    ]
    for o in offices:
        o["fees"] = {"Office fee": {c: v[1] for c, v in CODES.items()}}
        for p in o["payers"]:
            if p["name"] in _PCT:
                o["fees"][p["name"]] = _fees(p["name"])
    return offices


def _office(g, oid):
    return next(o for o in g if o["id"] == oid)


def _line(o, idx, new):
    o["policy"][idx] = new


def _add_line(o, new):
    o["policy"].append(new)


# Each plant: (office, label, expected check ids, function that applies it).
# Expected checks are what a correct checker reports for that plant on its own.
def _p_oak_adj(g):
    o = _office(g, "OAK"); o["adjustment_types"].remove("PPO Write-Off")


def _p_oak_premier(g):
    _line(_office(g, "OAK"), 1, L("Delta Premier claims, handle like we always do.", "question"))


def _p_oak_dup(g):
    _office(g, "OAK")["payers"].append(_payer("Guardian", "PPO", "GI813", 0))


def _p_ced_bank(g):
    _office(g, "CED")["bank_linked"] = False


def _p_ced_small(g):
    _line(_office(g, "CED"), 2, L("Small balances get written off.", "question"))


def _p_ced_secondary(g):
    _add_line(_office(g, "CED"), L("Write off the secondary insurance stuff if it isn't worth chasing.",
                                   "question"))


def _p_ced_fees(g):
    del _office(g, "CED")["fees"]["United Concordia"]


def _p_bir_sync(g):
    _office(g, "BIR")["sync_tested"] = False


def _p_bir_guardian(g):
    _line(_office(g, "BIR"), 5, L("For Guardian, the doctor decides case by case.", "question"))


def _p_bir_era(g):
    p = next(p for p in _office(g, "BIR")["payers"] if p["name"] == "MetLife")
    p["remit"] = "none"


def _p_map_owner(g):
    _office(g, "MAP")["exception_owner"] = ""


def _p_map_small(g):
    _line(_office(g, "MAP"), 2, L("Write off small balances under $5 or $10, whichever makes sense.",
                                  "question"))


def _p_map_fee(g):
    _office(g, "MAP")["fees"]["Delta Dental PPO"]["D2740"] = 1520


def _p_map_conflict(g):
    _add_line(_office(g, "MAP"), L("Denied claims under $20 can be written off as Small Balance.", "rule",
                                   case="denied_claim", action="write_off", max=20, adj="Small Balance",
                                   accept_question=True))


def _p_wil_same(g):
    o = _office(g, "WIL")
    o["policy"] = [L("We follow the same write-off rules as the other offices.", "question")] + o["policy"][3:]


def _p_wil_type(g):
    next(p for p in _office(g, "WIL")["payers"] if p["name"] == "Aetna")["plan_type"] = ""


PLANTS = [
    ("OAK", "PPO Write-Off adjustment type named in the policy is not set up in Dentrix", ["adj_type_missing"], _p_oak_adj),
    ("OAK", "Delta Premier policy line says 'handle like we always do'", ["policy_open_question", "no_rule_for_case"], _p_oak_premier),
    ("OAK", "Guardian listed twice under two payer IDs", ["duplicate_payer"], _p_oak_dup),
    ("CED", "Deposit account not linked, so payments cannot be matched to the bank", ["bank_not_linked"], _p_ced_bank),
    ("CED", "Small balance write-off with no dollar limit", ["policy_open_question"], _p_ced_small),
    ("CED", "Secondary insurance line with no clear rule", ["policy_open_question"], _p_ced_secondary),
    ("CED", "United Concordia contracted fee schedule never sent", ["fee_schedule_missing"], _p_ced_fees),
    ("BIR", "PMS sync not yet tested on Dentrix Ascend", ["pms_sync_untested"], _p_bir_sync),
    ("BIR", "Guardian line says the doctor decides case by case", ["policy_open_question"], _p_bir_guardian),
    ("BIR", "MetLife pays by EFT but no electronic remittance (ERA) is set up", ["eft_without_era"], _p_bir_era),
    ("MAP", "Nobody named to work the exception queue", ["no_exception_owner"], _p_map_owner),
    ("MAP", "Small balance limit given as '$5 or $10'", ["policy_open_question"], _p_map_small),
    ("MAP", "Crown fee for Delta Dental PPO entered above the office fee", ["fee_above_office_fee"], _p_map_fee),
    ("MAP", "Policy both writes off small denials and never writes off denials", ["policy_conflict"], _p_map_conflict),
    ("WIL", "Policy says 'same rules as the other offices' instead of its own rules",
     ["policy_open_question", "no_rule_for_case"], _p_wil_same),
    ("WIL", "Aetna plan type left blank", ["payer_type_missing"], _p_wil_type),
]


def as_received() -> list[dict]:
    g = clean_group()
    for _, _, _, fn in PLANTS:
        fn(g)
    return g


def with_plant(i: int) -> list[dict]:
    g = clean_group()
    PLANTS[i][3](g)
    return g


def state(name: str) -> list[dict]:
    return copy.deepcopy(as_received() if name == "as_received" else clean_group())
