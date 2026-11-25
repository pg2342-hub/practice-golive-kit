"""Weekly note to the practice owner, drafted by Claude from the health numbers.

Claude gets only that office's weekly numbers and flags, and writes a short note in plain words.
Every number in the note must be one of the numbers it was given (`grounded`), so a note that
invents a figure fails and is not shown. Notes are cached in data/notes/; refresh with
`python3 -m kit.notes --live` (needs ANTHROPIC_API_KEY and the `anthropic` package).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time

from kit.policy import MODEL, ROOT

NOTES = os.path.join(ROOT, "data", "notes")
NOTE_WEEKS = (4, 8)

SYSTEM = """You write the weekly update a deployment lead sends to the owner of one dental office
during the first eight weeks on an AI billing assistant. The owner is a dentist, busy, not technical.

Write 3 to 5 short sentences in plain words: how posting went this week, the one thing that needs
attention (if any) and what you will do about it, and anything you need from the owner. Use only the
numbers given to you, written the same way (a percentage stays a percentage). Do not invent names,
dates, dollar amounts or numbers. No greeting line, no sign-off, no bullet points."""

SCHEMA = {"type": "object", "properties": {"note": {"type": "string"}},
          "required": ["note"], "additionalProperties": False}


def facts(sim: dict, week: int, target: int) -> dict:
    ws = [w for w in sim["weeks"] if w["week"] <= week]
    return {"office": sim["name"], "week": week, "auto_post_target_pct": target,
            "weeks": [{k: w[k] for k in ("week", "mode", "lines", "auto", "held", "stuck", "auto_rate",
                                          "backlog_hours", "oldest_days", "paper_pct", "top_stuck")}
                      for w in ws],
            "flags": [f for f in sim["flags"] if f["week"] <= week]}


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def grounded(note: str, fx: dict) -> list[str]:
    """Numbers in the note that are not in the facts it was given. Empty list = grounded."""
    allowed: set = set()

    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            allowed.add(float(v))
        elif isinstance(v, str):
            allowed.update(float(x.replace(",", "")) for x in _NUM.findall(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(fx)
    allowed.update({1.0, 2.0})  # "one", "two" written as digits, "week 1"
    nums = [n.rstrip(",").replace(",", "") for n in _NUM.findall(note)]
    return [n for n in nums if float(n) not in allowed]


def _key(fx: dict) -> str:
    return hashlib.sha256(json.dumps(fx, sort_keys=True).encode()).hexdigest()[:12]


def path(office_id: str, week: int) -> str:
    return os.path.join(NOTES, f"{office_id}_week{week}.json")


def load(office_id: str, week: int, fx: dict) -> dict | None:
    p = path(office_id, week)
    if not os.path.exists(p):
        return None
    d = json.load(open(p))
    return d if d.get("facts_sha") == _key(fx) else None


def call_claude(fx: dict) -> tuple[str, dict]:
    import anthropic

    client = anthropic.Anthropic()
    t0 = time.time()
    resp = client.beta.messages.create(
        model=MODEL, max_tokens=16000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        system=SYSTEM, messages=[{"role": "user", "content": json.dumps(fx, indent=1)}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("refused")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)["note"], {"model": resp.model, "input_tokens": resp.usage.input_tokens,
                                      "output_tokens": resp.usage.output_tokens,
                                      "seconds": round(time.time() - t0, 1)}


def main() -> None:
    from kit import health, intake
    from kit.dryrun import rules_of
    from kit.policy import compiled

    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    os.makedirs(NOTES, exist_ok=True)
    for o in intake.state("after_fixes"):
        sim = health.simulate(o, rules_of(compiled(o, "after_fixes")))
        for wk in NOTE_WEEKS:
            fx = facts(sim, wk, health.TARGET)
            if load(o["id"], wk, fx):
                print(o["id"], wk, "cached")
                continue
            if not a.live:
                print(o["id"], wk, "missing")
                continue
            for attempt in range(1, 4):
                note, usage = call_claude(fx)
                bad = grounded(note, fx)
                if not bad:
                    break
                print(o["id"], wk, "attempt", attempt, "ungrounded numbers", bad)
            json.dump({"office": o["id"], "week": wk, "facts_sha": _key(fx), "note": note,
                       "ungrounded": bad, "attempts": attempt, "usage": usage},
                      open(path(o["id"], wk), "w"), indent=1)
            print(o["id"], wk, usage, "grounded" if not bad else f"UNGROUNDED {bad}")


if __name__ == "__main__":
    main()
