# practice-golive-kit

Demo page: https://pranavgudise.dev/practice-golive-kit/

Getting a dental office live on an AI billing assistant comes down to two jobs. Before go-live, the office's payers, fee schedules, practice management system (PMS), and the office manager's write-off policy have to become posting rules that a machine can follow, and every gap has to land with the person who can fix it. After go-live, someone has to watch the first eight weeks closely enough to catch an account drifting before the owner notices.

This kit does both for a made-up five-office group (Dentrix G7, Dentrix Ascend, Open Dental and Eaglesoft offices):

1. **Policy reader.** Claude reads each office's write-off policy, written in plain English, and turns every line into a posting rule, a question for the owner, or "not about posting". The prompt says to ask whenever a line would mean guessing ("handle like we always do", "$5 or $10, whichever makes sense"), and never to turn a vague line into a write-off.
2. **Readiness checks.** Thirteen checks across the intake and the rules: PMS sync, bank link, ERA and EFT enrollment, plan types, fee schedules, exception-queue owner, open policy questions, conflicting rules, adjustment types the PMS does not have, and kinds of balance with no rule. Each office gets NO-GO, GO WITH FIXES or GO, and each finding goes to its owner (practice owner, office manager, onboarding team, payer enrollment).
3. **Dry run.** One week of made-up insurance payment lines per office, run through the setup: how many would post with no person, how many the policy holds for review on purpose (denials, overpayments), and how many are stuck on setup, by reason.
4. **First eight weeks.** A weekly simulation after go-live, with staff approving every post in weeks 1 and 2. Five rules flag drift (auto-post rate drop, below target, growing exception backlog, stale exceptions, late ERA enrollment), each with a reason and a next step. Claude drafts the week 4 and week 8 note to each owner from that office's numbers only; a note with any number that was not in its input is rejected.

## Run it

Python 3.10+, standard library only (the `anthropic` package is needed only to refresh the Claude runs).

```
python3 -m kit.report as_received          # the intake as first collected: 16 planted problems
python3 -m kit.report after_fixes          # after the fixes and the owners' answers, plus the eight weeks
python3 -m eval.run_eval                   # both evals below
python3 -m unittest                        # tests
python3 scripts/build_demo.py              # rebuild docs/index.html from the output
```

Claude's policy readings (3 runs per policy) and owner notes are cached in `data/compiled/` and `data/notes/`. The `claude runs` GitHub Action refreshes them with `python3 -m kit.policy --live` and `python3 -m kit.notes --live` (model `claude-opus-5-5`, structured JSON output).

## Evals

- **Checks.** 16 setup problems planted in a clean intake (`kit/intake.py`), run one at a time and all together, using the labelled policy answers so the checks are tested on their own. Results: see `eval/results/eval_results.json` and the demo page.
- **Policy reading.** Every policy line (both intakes, 3 runs each) is scored against its label: a clear line must become the right rule (case, action, payer scope, payer names, dollar limit, adjustment type), a vague line must become a question. A critical error is a write-off the policy did not clearly allow.

## Layout

```
kit/intake.py    the made-up group, labelled policies, and the 16 planted problems
kit/policy.py    Claude policy reader (prompt, JSON schema, cache)
kit/checks.py    readiness checks, verdicts, owners
kit/dryrun.py    one week of payment lines through the setup
kit/health.py    first eight weeks, flags, and next steps
kit/notes.py     Claude's weekly owner note, with the number check
kit/report.py    text report
eval/run_eval.py both evals
scripts/build_demo.py, docs/template.html   the demo page
```

## Data

Everything is made up: offices, staff, fees, payer shares, policies, and payment lines. Payer names and CDT procedure codes are public. Coinsurance by procedure class (0%, 20%, 50%) and staff minutes per exception are stated assumptions. Deductibles are not modelled, so a patient's share is coinsurance only. The patient's share is always billed at posting; a small-balance write-off is recorded as a later account-level step, not a write-off on the EOB line. All five offices start together in the simulation to keep it simple; the plan brings them on in waves. Nothing here describes a real practice or comes from any company's systems.
