"""Print the go-live readiness report for every office.

    python3 -m kit.report as_received            # the intake as first collected
    python3 -m kit.report after_fixes            # after the owner's answers and the fixes
    python3 -m kit.report after_fixes --labels   # use the labelled policy answers instead of Claude's
"""

from __future__ import annotations

import argparse

from kit import checks, dryrun, health, intake, policy


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("state", choices=["as_received", "after_fixes"])
    ap.add_argument("--labels", action="store_true")
    a = ap.parse_args()
    src = "labels" if a.labels else "claude"
    print(f"# Go-live readiness: {intake.GROUP_NAME}, {a.state.replace('_', ' ')}\n")
    for o in intake.state(a.state):
        comp = policy.compiled(o, a.state, src)
        f = checks.run_checks(o, comp)
        d = dryrun.dry_run(o, dryrun.rules_of(comp))
        print(f"## {o['name']} ({o['kind']}, {o['pms']}): {checks.verdict(f)}")
        print(f"Dry run, one week: {d['auto']} of {d['lines']} lines post with no person, "
              f"{d['held']} held by policy, {d['stuck']} stuck on setup.")
        for x in f:
            print(f"- [{x['severity']}] {x['message']} (owner: {x['owner']})")
        print()
    if a.state == "after_fixes":
        print("## First eight weeks (simulated)\n")
        for o in intake.state("after_fixes"):
            s = health.simulate(o, dryrun.rules_of(policy.compiled(o, "after_fixes", src)))
            print(f"{o['name']}: auto-post rate by week " + ", ".join(f"{w['auto_rate']}%" for w in s["weeks"]))
            for fl in s["flags"]:
                print(f"- week {fl['week']}: {fl['signal']}. {fl['reason']} Next: {fl['next_step']}")


if __name__ == "__main__":
    main()
