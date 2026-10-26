"""Conformance test for the Meterless World Model engine (agent/world_model.py).

    python3 -m unittest discover -s tests -v

Checks the engine's three services and its use in the live feature: the shared
case board that every agent reads and writes.
  WorldStoreService      entities, facts, relationships, append-only JSONL trail
  IngestPipelineService  every query result enters here, with full provenance,
                         idempotently (the same query never creates two facts)
  ContextBuilderService  a grounded, compact view of the case for agent prompts
Needs only the Python standard library (runs in SAMPLE_MODE, no services).
"""
import json
import os
import tempfile
import unittest

os.environ["SAMPLE_MODE"] = "true"

from agent.data_client import QueryResult  # noqa: E402
from agent.world_model import WorldModel  # noqa: E402


def _result(sql="SELECT 0.744 AS value", rows=None):
    return QueryResult(columns=["value"], rows=rows or [[0.744]], sql=sql, ms=12,
                       source="zetaris")


class WorldModelEngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.trail = os.path.join(self.tmp.name, "world_model.jsonl")
        self.wm = WorldModel(self.trail)

    def tearDown(self):
        self.tmp.cleanup()

    def ingest(self, sql="SELECT 0.744 AS value", purpose="primary"):
        return self.wm.ingest.ingest_metric(
            "OOS-001", "fill_on_time_pct", "Qty Fill On-Time %", "supply", 0.744,
            "below 95%", "flagged", {"orders_in_window": 12}, _result(sql), "Investigator",
            purpose=purpose)

    def test_ingest_records_full_provenance(self):
        fact = self.ingest()
        prov = fact["provenance"]
        self.assertEqual(prov["source"], "zetaris")
        self.assertIn("SELECT", prov["sql"])
        self.assertEqual(prov["rows_returned"], 1)
        self.assertEqual(fact["recorded_by"], "Investigator")
        self.assertEqual(fact["value"], 0.744)

    def test_ingest_is_idempotent(self):
        a, b = self.ingest(), self.ingest()
        self.assertEqual(a["fact_id"], b["fact_id"])
        self.assertEqual(len(self.wm.store.facts), 1)
        self.assertNotEqual(self.ingest(purpose="verification")["fact_id"], a["fact_id"])

    def test_every_write_is_on_the_trail(self):
        self.ingest()
        self.wm.store.upsert_entity("H-x", "hypothesis", case_id="OOS-001", state="testing")
        with open(self.trail) as f:
            kinds = [json.loads(line)["kind"] for line in f]
        self.assertIn("fact", kinds)
        self.assertIn("relationship", kinds)
        self.assertIn("entity", kinds)

    def test_hypothesis_can_be_rolled_back_and_linked_to_refuting_fact(self):
        fact = self.ingest()
        st = self.wm.store
        st.upsert_entity("H-ss", "hypothesis", case_id="OOS-001", title="Safety stock",
                         state="testing")
        st.upsert_entity("H-ss", "hypothesis", case_id="OOS-001", title="Safety stock",
                         state="confirmed")
        st.upsert_entity("H-ss", "hypothesis", case_id="OOS-001", title="Safety stock",
                         state="rolled back: symptom of transport delays")
        st.relate("H-ss", "refuted_by", fact["fact_id"], "Planner")
        self.assertTrue(st.entities["H-ss"]["state"].startswith("rolled back"))
        self.assertIn({"src": "H-ss", "rel": "refuted_by", "dst": fact["fact_id"],
                       "by": "Planner"}, st.relationships)

    def test_context_builder_is_grounded_in_facts(self):
        self.ingest()
        self.wm.store.upsert_entity("H-ss", "hypothesis", case_id="OOS-001",
                                    title="Safety stock", state="confirmed")
        ctx = self.wm.context.case_context("OOS-001")
        self.assertIn("Qty Fill On-Time %", ctx)
        self.assertIn("74.4%", ctx)
        self.assertIn("Hypothesis 'Safety stock': confirmed", ctx)
        self.assertEqual(self.wm.context.case_context("OOS-999"), "(no facts yet)")


class WorldModelInLiveFeatureTest(unittest.TestCase):
    """The engine powering the real feature: one full investigation (OOS-001)."""

    @classmethod
    def setUpClass(cls):
        from agent.data_client import SampleClient
        from agent.llm import Nemotron
        from agent.main import investigate, list_events
        data = SampleClient()
        event = next(e for e in list_events(data) if e["event_id"] == "OOS-001")
        cls.result = investigate(event, data, Nemotron(), printer=lambda *_: None)
        from agent import config
        cls.run_dir = os.path.join(config.LOG_DIR, cls.result["run_id"])

    def test_every_fact_carries_its_sql_and_source(self):
        for f in self.result["evidence"]:
            self.assertTrue(f["provenance"]["sql"].strip().upper().startswith(("SELECT", "WITH")))
            self.assertTrue(f["provenance"]["source"])

    def test_rolled_back_cause_is_recorded_with_its_refuting_fact(self):
        with open(os.path.join(self.run_dir, "world_model.jsonl")) as f:
            lines = [json.loads(line) for line in f]
        states = [e.get("state", "") for e in lines if e["kind"] == "entity"]
        self.assertTrue(any(s.startswith("rolled back") for s in states))
        self.assertTrue(any(e["kind"] == "relationship" and e["rel"] == "refuted_by"
                            for e in lines))


if __name__ == "__main__":
    unittest.main()
