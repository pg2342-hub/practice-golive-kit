"""First eight weeks after go-live: weekly account health per office, with risk flags.

This is a simulation, not real accounts. Each week replays that week's made-up lines through the
office's setup (so paper payers turn electronic on their ERA go-live week), adds the events in
SCENARIO, and runs the exception queue with the office's staff hours. The flags are rules a
deployment lead would watch; each one comes with the reason and the next step.

Autonomy for the pilot: weeks 1 and 2 are review weeks (staff approve every automatic post before
it lands); automatic posting switches on in week 3.
"""

from __future__ import annotations

import copy

from kit.dryrun import dry_run

WEEKS = 8
REVIEW_WEEKS = 2
TARGET = 90  # % of lines the policy does not hold, posted with no person
MIN_HELD, MIN_STUCK, MIN_REVIEW = 6, 4, 0.5  # staff minutes per line (assumption)

# Events in the made-up story, applied to the office's setup for the weeks listed.
SCENARIO = [
    dict(office="BIR", weeks=[4, 5], what="MetLife moved Birch to a new ERA payer ID; ERAs stop matching",
         apply=lambda o: next(p for p in o["payers"] if p["name"] == "MetLife").update(remit="none")),
    dict(office="CED", weeks=list(range(1, 9)), what="Denti-Cal ERA enrollment slips from week 6 to week 8",
         apply=lambda o: next(p for p in o["payers"] if p["name"] == "Denti-Cal").update(era_live_week=8)),
    dict(office="WIL", weeks=list(range(1, 9)), what="Office manager also covers the front desk; 1 hour a week on the queue",
         apply=lambda o: o.update(exception_hours_per_week=1)),
    dict(office="MAP", weeks=[6, 7], what="Billing coordinator on leave; no one clears the queue",
         apply=lambda o: o.update(exception_hours_per_week=0)),
]


def simulate(office: dict, rules: list[dict]) -> dict:
    weeks, flags, backlog, queue = [], [], 0.0, []
    active, seen_now = set(), set()  # a signal is reported when it starts, not every week it lasts
    planned = {p["name"]: p["era_live_week"] for p in office["payers"] if p["remit"] == "paper"}
    for w in range(1, WEEKS + 1):
        o = copy.deepcopy(office)
        events = [s["what"] for s in SCENARIO if s["office"] == o["id"] and w in s["weeks"]]
        for s in SCENARIO:
            if s["office"] == o["id"] and w in s["weeks"]:
                s["apply"](o)
        d = dry_run(o, rules, week=w)
        n, auto, held, stuck = d["lines"], d["auto"], d["held"], d["stuck"]
        rate = round(100 * auto / (auto + stuck)) if auto + stuck else 0
        minutes_in = held * MIN_HELD + stuck * MIN_STUCK + (auto * MIN_REVIEW if w <= REVIEW_WEEKS else 0)
        cap = o["exception_hours_per_week"] * 60
        queue.append([w, minutes_in])
        left, cleared = cap, 0.0
        while queue and left > 0:  # oldest work first
            take = min(left, queue[0][1])
            queue[0][1] -= take; left -= take; cleared += take
            if queue[0][1] <= 0.01:
                queue.pop(0)
        backlog = sum(q[1] for q in queue)
        oldest = (w - queue[0][0] + 1) * 5 if queue and backlog > 0.5 else 0  # working days, by week
        paper = sum(p["share_pct"] for p in o["payers"]
                    if p["remit"] == "paper" and (p["era_live_week"] is None or w < p["era_live_week"]))
        top = next((r for r in d["reasons"] if r["kind"] == "stuck"), None)
        weeks.append(dict(week=w, lines=n, auto=auto, held=held, stuck=stuck, auto_rate=rate,
                          mode="review" if w <= REVIEW_WEEKS else "auto",
                          queue_hours_in=round(minutes_in / 60, 1), hours_cleared=round(cleared / 60, 1),
                          backlog_hours=round(backlog / 60, 1), oldest_days=oldest, paper_pct=paper,
                          top_stuck=top["reason"] if top else None, events=events))
        for f in _flags(o, weeks, planned):
            if f["signal"] not in active:
                flags.append(f)
            seen_now.add(f["signal"])
        active, seen_now = seen_now, set()
    return dict(office=office["id"], name=office["name"], weeks=weeks, flags=flags)


def _drop_step(top: str | None) -> str:
    if top and "Paper EOB" in top:
        return "Check the payer's ERA enrollment date and add queue hours for keyed EOBs until it is live."
    if top and "no ERA" in top:
        return "Ask the payer for its current ERA payer ID, update the enrollment, and match the open deposits by hand meanwhile."
    if top and ("fee" in top or "Paid below" in top):
        return "Load the payer's current fee schedule and check whether the contract changed."
    return "Find what changed for that payer this week and fix the setup before the backlog builds."


def _flag(week, office, signal, reason, step):
    return dict(week=week, office=office, signal=signal, reason=reason, next_step=step)


def _flags(o, ws, planned):
    w, out = ws[-1], []
    prev = ws[-2] if len(ws) > 1 else None
    if prev and w["mode"] == "auto" and prev["mode"] == "auto" and prev["auto_rate"] - w["auto_rate"] >= 10:
        out.append(_flag(w["week"], o["id"], "Auto-post rate dropped",
                         f"Down from {prev['auto_rate']}% to {w['auto_rate']}%; most stuck lines: {w['top_stuck']}.",
                         _drop_step(w["top_stuck"])))
    elif w["mode"] == "auto" and w["week"] >= 4 and w["auto_rate"] < TARGET:
        out.append(_flag(w["week"], o["id"], "Below the auto-post target",
                         f"{w['auto_rate']}% against a {TARGET}% target; most stuck lines: {w['top_stuck']}.",
                         "Work the top stuck reason with the office manager this week."))
    if len(ws) >= 3 and ws[-1]["backlog_hours"] > ws[-2]["backlog_hours"] > ws[-3]["backlog_hours"]:
        out.append(_flag(w["week"], o["id"], "Exception backlog growing",
                         f"{w['backlog_hours']} hours of exceptions waiting, up two weeks in a row.",
                         "Agree more queue hours with the owner, or move the held denials to a second person."))
    if w["oldest_days"] > 5:
        out.append(_flag(w["week"], o["id"], "Exceptions going stale",
                         f"Some exceptions have waited more than a week (up to {w['oldest_days']} working days).",
                         "Name a backup for the exception queue and clear the oldest items first."))
    for name, wk in planned.items():
        p = next(p for p in o["payers"] if p["name"] == name)
        if wk and w["week"] == wk and p["era_live_week"] and p["era_live_week"] > wk:
            out.append(_flag(w["week"], o["id"], "ERA enrollment late",
                             f"{name} was planned to send ERAs by week {wk} and still sends paper.",
                             f"Call {name}'s EDI enrollment line, confirm the enrollment form, and keep keying its EOBs until it is live."))
    return out
