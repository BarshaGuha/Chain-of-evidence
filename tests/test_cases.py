"""End-to-end check: all six stockouts against the answer key (data/ANSWER_KEY.md).

    python3 -m unittest discover -s tests -v

Runs every investigation in SAMPLE_MODE (bundled data, offline reasoner) and
checks the confirmed causes, the loops and rollbacks, and that the Evaluator
signed off a report whose every cause matches the evidence.
"""
import os
import unittest

os.environ["SAMPLE_MODE"] = "true"

EXPECTED = {  # event: (confirmed causes, dig-deeper loops >= , rollbacks)
    "OOS-001": ({"Transport delays from plant to DC"}, 0, 1),
    "OOS-002": ({"Recent demand surge not reflected in the forecast"}, 1, 0),
    "OOS-003": ({"Safety stock set too low for demand variability",
                 "DC ordered less than needed"}, 0, 0),
    "OOS-004": ({"Transport delays from plant to DC"}, 0, 1),
    "OOS-005": ({"Recent demand surge not reflected in the forecast"}, 1, 0),
    "OOS-006": ({"Plant short-shipped against DC orders"}, 0, 1),
}


class AnswerKeyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from agent.data_client import SampleClient
        from agent.llm import Nemotron
        from agent.main import investigate, list_events
        data, llm = SampleClient(), Nemotron()
        cls.results = {e["event_id"]: investigate(e, data, llm, printer=lambda *_: None)
                       for e in list_events(data)}

    def test_six_stockouts(self):
        self.assertEqual(sorted(self.results), sorted(EXPECTED))

    def test_root_causes_loops_and_rollbacks_match_the_answer_key(self):
        for event, (causes, loops, rollbacks) in EXPECTED.items():
            r = self.results[event]
            with self.subTest(event=event):
                self.assertEqual({c["cause"] for c in r["confirmed_causes"]}, causes)
                self.assertGreaterEqual(r["loops"], loops)
                self.assertEqual(len(r["rollbacks"]), rollbacks)

    def test_reports_are_signed_off_with_impact(self):
        for event, r in self.results.items():
            with self.subTest(event=event):
                self.assertEqual(r["status"], "approved")
                self.assertGreater(r["impact"]["lost_units"], 0)
                self.assertIsNotNone(r["impact"]["lost_value"])


if __name__ == "__main__":
    unittest.main()
