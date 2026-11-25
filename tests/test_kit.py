import unittest

from eval.run_eval import eval_checks, score_line
from kit import checks, dryrun, health, intake, notes, policy


class Checks(unittest.TestCase):
    def test_clean_group_only_paper_warnings(self):
        for o in intake.clean_group():
            f = checks.run_checks(o, policy.from_labels(o))
            self.assertTrue(all(x["check"] == "paper_payer" for x in f), (o["id"], f))
            self.assertNotEqual(checks.verdict(f), "NO-GO")

    def test_every_plant_caught_alone_and_together(self):
        r = eval_checks()
        self.assertEqual(r["alone_caught"], r["total"])
        self.assertEqual(r["alone_extra"], 0)
        self.assertEqual(r["together_caught"], r["total"])
        self.assertEqual(r["together_false_positives"], [])

    def test_as_received_all_no_go(self):
        for o in intake.as_received():
            self.assertEqual(checks.verdict(checks.run_checks(o, policy.from_labels(o))), "NO-GO", o["id"])


class DryRun(unittest.TestCase):
    def test_counts_add_up_and_repeat(self):
        o = intake.clean_group()[0]
        r = dryrun.rules_of(policy.from_labels(o))
        a, b = dryrun.dry_run(o, r), dryrun.dry_run(o, r)
        self.assertEqual(a, b)
        self.assertEqual(a["auto"] + a["held"] + a["stuck"], a["lines"])

    def test_missing_adjustment_type_blocks_posting(self):
        o = intake.with_plant(0)[0]
        d = dryrun.dry_run(o, dryrun.rules_of(policy.from_labels(o)))
        self.assertTrue(any(x["reason"] == "Adjustment type not set up in the PMS" for x in d["reasons"]))

    def test_paper_payer_posts_after_era_week(self):
        o = next(x for x in intake.clean_group() if x["id"] == "WIL")
        r = dryrun.rules_of(policy.from_labels(o))
        before, after = dryrun.dry_run(o, r, week=4), dryrun.dry_run(o, r, week=5)
        paper = lambda d: sum(x["count"] for x in d["reasons"] if x["reason"].startswith("Paper EOB"))
        self.assertGreater(paper(before), 0)
        self.assertEqual(paper(after), 0)

    def test_conflicting_rules_do_not_auto_post(self):
        payer = {"name": "Cigna", "plan_type": "PPO"}
        rules = [dict(case="denied_claim", action="hold_for_review", payer_scope="all", payer_names=[], max_amount=None, adjustment_type=None),
                 dict(case="denied_claim", action="write_off", payer_scope="all", payer_names=[], max_amount=None, adjustment_type="X")]
        self.assertEqual(dryrun.find_rule(rules, "denied_claim", payer), (None, True))


class Health(unittest.TestCase):
    def test_scenario_flags_fire(self):
        signals = set()
        for o in intake.clean_group():
            s = health.simulate(o, dryrun.rules_of(policy.from_labels(o)))
            self.assertEqual(len(s["weeks"]), health.WEEKS)
            signals |= {(f["office"], f["signal"]) for f in s["flags"]}
        self.assertIn(("BIR", "Auto-post rate dropped"), signals)
        self.assertIn(("CED", "ERA enrollment late"), signals)
        self.assertIn(("MAP", "Exceptions going stale"), signals)
        self.assertIn(("WIL", "Exception backlog growing"), signals)
        self.assertFalse(any(o == "OAK" for o, _ in signals))


class Scoring(unittest.TestCase):
    def test_vague_line_guessed_as_write_off_is_critical(self):
        got = {"kind": "rule", "rule": dict(case="small_balance", action="write_off", payer_scope="all", payer_names=[], max_amount=None, adjustment_type=None)}
        ok, crit, _ = score_line({"kind": "question"}, got)
        self.assertFalse(ok)
        self.assertTrue(crit)

    def test_note_with_invented_number_fails(self):
        fx = {"week": 4, "weeks": [{"auto_rate": 93}], "flags": []}
        self.assertEqual(notes.grounded("Posting ran at 93% in week 4.", fx), [])
        self.assertEqual(notes.grounded("You saved $1,200 this week.", fx), ["1200"])


if __name__ == "__main__":
    unittest.main()
