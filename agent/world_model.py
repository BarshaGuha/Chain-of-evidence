"""Meterless World Model engine (minimal implementation for this project).

Implements the three services the Meterless World Model Agent Engine names as
the minimum: WorldStoreService, IngestPipelineService and ContextBuilderService.
It is the shared "case board" every agent reads and writes:

  entities      the stockout case, SKU, DC, hypotheses
  facts         metric results with full provenance (SQL, source, rows, time)
  relationships hypothesis -> supported_by / refuted_by -> fact

Ingest is idempotent (content-hashed), every write is appended to a JSONL
provenance trail in logs/, and the context builder gives each agent a compact,
grounded view instead of letting agents re-derive facts themselves.
"""
import hashlib
import json
import time


class WorldStoreService:
    def __init__(self, trail_path):
        self.entities, self.facts, self.relationships = {}, {}, []
        self.trail_path = trail_path

    def _append(self, kind, record):
        with open(self.trail_path, "a") as f:
            f.write(json.dumps({"ts": time.time(), "kind": kind, **record},
                               default=str) + "\n")

    def upsert_entity(self, entity_id, etype, **attrs):
        ent = self.entities.setdefault(entity_id, {"id": entity_id, "type": etype})
        ent.update(attrs)
        self._append("entity", ent)
        return ent

    def put_fact(self, fact):
        self.facts[fact["fact_id"]] = fact
        self._append("fact", fact)

    def relate(self, src, rel, dst, by):
        rec = {"src": src, "rel": rel, "dst": dst, "by": by}
        self.relationships.append(rec)
        self._append("relationship", rec)


class IngestPipelineService:
    """Canonical write path: every tool result enters the world model here."""

    def __init__(self, store):
        self.store = store

    def ingest_metric(self, case_id, metric_id, label, branch, value, threshold,
                      status, support, query_result, agent, purpose="primary"):
        digest = hashlib.sha256(
            f"{case_id}|{metric_id}|{purpose}|{query_result.sql}".encode()).hexdigest()[:12]
        fact_id = f"F-{metric_id}-{purpose}-{digest}"
        if fact_id in self.store.facts:          # idempotent: same query, same fact
            return self.store.facts[fact_id]
        fact = {
            "fact_id": fact_id, "case_id": case_id, "metric_id": metric_id,
            "label": label, "branch": branch, "purpose": purpose,
            "value": value, "threshold": threshold, "status": status,
            "support": support, "recorded_by": agent,
            "provenance": {"source": query_result.source, "sql": query_result.sql.strip(),
                           "ms": query_result.ms, "attempts": query_result.attempts,
                           "rows_returned": len(query_result.rows)},
        }
        self.store.put_fact(fact)
        self.store.relate(case_id, "has_fact", fact_id, agent)
        return fact


class ContextBuilderService:
    def __init__(self, store):
        self.store = store

    def case_context(self, case_id, max_facts=20):
        facts = [f for f in self.store.facts.values() if f["case_id"] == case_id]
        lines = []
        for f in facts[-max_facts:]:
            v = f["value"]
            vs = f"{v:.1%}" if isinstance(v, (int, float)) else str(v)
            lines.append(f"- {f['label']} ({f['branch']}, {f['purpose']}): {vs} "
                         f"| threshold {f['threshold']} | status {f['status']}")
        hyps = [e for e in self.store.entities.values()
                if e.get("type") == "hypothesis" and e.get("case_id") == case_id]
        for h in hyps:
            lines.append(f"- Hypothesis '{h['title']}': {h.get('state', 'open')}")
        return "\n".join(lines) if lines else "(no facts yet)"


class WorldModel:
    """Facade bundling the three services."""

    def __init__(self, trail_path):
        self.store = WorldStoreService(trail_path)
        self.ingest = IngestPipelineService(self.store)
        self.context = ContextBuilderService(self.store)
