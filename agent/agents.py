"""The agent system: four agents that talk through a message bus.

  Planner       walks the root-cause tree, decides what to investigate next
  Investigator  runs metric and verification queries on Zetaris
  Evaluator     challenges every finding: re-check, rule out, dig deeper,
                and signs off (or vetoes) the final report
  Writer        drafts the root-cause report; cannot publish without sign-off

There is no fixed pipeline. Agents react to messages, and four feedback
loops are built in:
  1. Evaluator -> Investigator  recheck       (independent verification)
  2. Evaluator -> Planner       dig_deeper    (inconclusive -> investigate more)
  3. Evaluator -> Investigator  counter_test  (try to falsify a confirmed cause)
     Evaluator -> Planner       rollback      (retract a cause that fails it)
  4. Evaluator -> Writer        revise        (report claims must match evidence)

Optional analyst checkpoint (web interface): at the first review the Evaluator
pauses, sends its findings and its own recommendation to the human ("You"),
and acts on the direction it gets back. With no reply it continues on its own.
"""
import itertools
import json
import re
import time
from dataclasses import dataclass, field

from . import config
from .metrics import (ACTIONS, COUNTER_TESTS, DRILL_DOWNS, IMPACT_SQL, IMPACT_WINDOW_DAYS,
                      METRICS, NAIVE_FIX, ONSET, PLAIN, ROOTS, TREE, VERIFY, onset)

_ids = itertools.count(1)


@dataclass
class Message:
    sender: str
    recipient: str
    type: str
    payload: dict = field(default_factory=dict)
    id: int = field(default_factory=lambda: next(_ids))


class Bus:
    """Delivers messages and writes every one of them to the run trace."""

    def __init__(self, trace_path, printer=print, listener=None):
        self.queue, self.agents, self.transcript = [], {}, []
        self.trace_path, self.printer, self.listener = trace_path, printer, listener

    def register(self, agent):
        self.agents[agent.name] = agent
        agent.bus = self

    def send(self, sender, recipient, mtype, summary="", **payload):
        msg = Message(sender, recipient, mtype, payload)
        entry = {"ts": time.time(), "msg_id": msg.id, "from": sender, "to": recipient,
                 "type": mtype, "summary": summary,
                 "payload": {k: v for k, v in payload.items() if k != "rows"}}
        self.transcript.append(entry)
        with open(self.trace_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        self.printer(f"[{sender} → {recipient}] {mtype}: {summary}")
        if self.listener:
            self.listener(entry)
        self.queue.append(msg)

    def run(self):
        steps = 0
        while self.queue and steps < config.MAX_MESSAGES:
            msg = self.queue.pop(0)
            self.agents[msg.recipient].handle(msg)
            steps += 1
        if self.queue:
            self.printer(f"[system] stopped after {steps} messages (safety cap)")
        return steps


class Agent:
    name = "agent"

    def __init__(self, case, wm, llm, data, receipts):
        self.case, self.wm, self.llm, self.data = case, wm, llm, data
        self.receipts = receipts
        self.bus = None

    def send(self, to, mtype, summary="", **payload):
        self.bus.send(self.name, to, mtype, summary, **payload)

    def handle(self, msg):
        getattr(self, "on_" + msg.type)(msg)

    def think(self, system, user, fallback, want_json=True, **kw):
        r = self.llm.ask(self.name.lower(), system, user, fallback, want_json, **kw)
        rec = {"agent": self.name, "model": r.model, "receipt_id": r.receipt_id,
               "latency_ms": r.latency_ms, "tokens": r.tokens, "fallback": r.fallback,
               "error": r.error, "receipt": r.receipt}
        self.receipts.append(rec)
        return r

    def fmt(self, metric_id, v):
        return "n/a" if v is None else (f"{v:.1%}" if metric_id in METRICS else str(v))


def _status(metric_id, value):
    direction, thr = config.THRESHOLDS[metric_id]
    if value is None:
        return "no_data"
    flagged = value < thr if direction == "below" else value > thr
    if flagged:
        return "flagged"
    return "borderline" if abs(value - thr) <= config.BORDERLINE_BAND else "clear"


# A loop re-examines an area the first pass judged healthy; link it back so the
# chain of evidence shows what the first pass missed.
LOOP_PARENT = {"under_forecast_error_recent_pct": "under_forecast_error_pct",
               "lead_time_overrun_pct": "fill_on_time_pct",
               "order_qty_deviation_pct": "fill_on_time_pct"}


# ---------------------------------------------------------------- Planner
class Planner(Agent):
    name = "Planner"

    def __init__(self, *a):
        super().__init__(*a)
        self.pending, self.visited, self.causes = set(), set(), []
        self.loops = 0
        self.rollbacks = []
        self.parent = {}   # metric -> the metric whose result led us here

    def investigate(self, metric_id, why, purpose="primary", parent=None):
        if metric_id in self.visited:
            return
        self.visited.add(metric_id)
        self.parent[metric_id] = parent
        self.pending.add(metric_id)
        self.wm.store.upsert_entity(f"H-{metric_id}", "hypothesis",
                                    case_id=self.case["case_id"],
                                    title=METRICS[metric_id]["label"], state="testing")
        self.send("Investigator", "investigate", f"{METRICS[metric_id]['label']} ({why})",
                  metric_id=metric_id, purpose=purpose, parent=parent, why=why,
                  label=METRICS[metric_id]['label'], plain=PLAIN.get(metric_id, ''))

    def on_case_opened(self, msg):
        c = self.case
        system = ("You are the Planner in a supply-chain root-cause team. You walk an "
                  "expert root-cause tree for stockouts with three branches: supply "
                  "(did replenishment arrive in full and on time), demand (was demand "
                  "under-forecast) and inventory_norm (is safety stock adequate). "
                  "Reply with JSON only.")
        user = (f"Stockout: {c['product_name']} (SKU {c['sku_id']}) at {c['dc_name']} on {c['oos_date']} "
                f"(lost demand {c['lost_demand_qty']} units). All three branches will be "
                "tested. Decide the order to investigate them and give a one-sentence "
                'rationale. JSON: {"order": ["supply","demand","inventory_norm"], '
                '"rationale": "..."}')
        r = self.think(system, user, lambda: (
            "", {"order": ["supply", "demand", "inventory_norm"],
                 "rationale": "Start with supply, the most common stockout driver, then "
                              "demand and safety-stock policy."}))
        order = [b for b in r.data.get("order", []) if b in ROOTS]
        order += [b for b in ROOTS if b not in order]
        self.send("Evaluator", "plan", r.data.get("rationale", "")[:240],
                  order=order, reasoner=r.model)
        for branch in order:
            self.investigate(ROOTS[branch], f"{branch} branch entry check")

    def on_verdict(self, msg):
        p = msg.payload
        m = p["metric_id"]
        self.pending.discard(m)
        node = TREE.get(m, {})
        self.wm.store.upsert_entity(f"H-{m}", "hypothesis", case_id=self.case["case_id"],
                                    title=METRICS[m]["label"], state=p["verdict"])
        if p["verdict"] == "confirmed":
            if "cause" in node:
                self.causes.append({"metric_id": m, "cause": node["cause"],
                                    "owner": node["owner"]})
            for child in node.get("if_flagged", []):
                self.investigate(child, f"drill down: {METRICS[m]['label']} is off", parent=m)
        elif p["verdict"] in ("ruled_out", "provisionally_ruled_out"):
            for child in node.get("if_clear", []):
                self.investigate(child, f"{METRICS[m]['label']} is healthy, so check the next node",
                                 parent=m)
        if not self.pending:
            self.request_review()

    def on_dig_deeper(self, msg):
        self.loops += 1
        for m in msg.payload["metrics"]:
            self.investigate(m, f"loop {self.loops}: {msg.payload['reason'][:80]}",
                             purpose="drill_down", parent=LOOP_PARENT.get(m))
        if not self.pending:
            self.request_review()

    def on_judgement(self, msg):
        p = msg.payload
        self.wm.store.upsert_entity(f"H-{p['metric_id']}", "hypothesis",
                                    case_id=self.case["case_id"],
                                    title=METRICS[p["metric_id"]]["label"],
                                    state=f"judged {p['classification']}")

    def on_rollback(self, msg):
        p = msg.payload
        m = p["metric_id"]
        retracted = [c for c in self.causes if c["metric_id"] == m]
        self.causes[:] = [c for c in self.causes if c["metric_id"] != m]
        self.rollbacks.append({**p, "cause": retracted[0]["cause"] if retracted else m})
        self.wm.store.upsert_entity(f"H-{m}", "hypothesis", case_id=self.case["case_id"],
                                    title=METRICS[m]["label"],
                                    state=f"rolled back: symptom of {p['symptom_of']}")
        self.wm.store.relate(f"H-{m}", "refuted_by", p.get("fact_id", ""), self.name)
        self.request_review()

    def on_cause_upheld(self, msg):
        m = msg.payload["metric_id"]
        self.wm.store.upsert_entity(f"H-{m}", "hypothesis", case_id=self.case["case_id"],
                                    title=METRICS[m]["label"],
                                    state="confirmed; survived counter-test")
        self.request_review()

    def chain(self, metric_id):
        """The path through the tree that led to a cause: root ... leaf."""
        path, m = [], metric_id
        while m and m not in path:
            path.insert(0, m)
            m = self.parent.get(m)
        return path

    def request_review(self):
        self.send("Evaluator", "review_request",
                  f"tree walk complete; candidate causes: "
                  f"{[c['cause'] for c in self.causes] or 'none'}",
                  causes=self.causes, loops=self.loops, visited=sorted(self.visited),
                  rollbacks=self.rollbacks)


# ---------------------------------------------------------------- Investigator
class Investigator(Agent):
    name = "Investigator"

    def params(self):
        return dict(sku=self.case["sku_id"], dc=self.case["dc_id"], d=self.case["oos_date"],
                    p1_days=config.P1_DAYS, **config.SOURCES)

    def on_investigate(self, msg):
        m = msg.payload["metric_id"]
        spec = METRICS[m]
        sql = spec["sql"].format(**self.params())
        try:
            res = self.data.run(sql)
            row = res.first()
            value = row.get("value")
            value = float(value) if value is not None else None
            status = _status(m, value)
            support = {k: v for k, v in row.items() if k != "value"}
        except Exception as e:
            self.send("Evaluator", "evidence", f"{spec['label']}: query failed ({e})"[:200],
                      metric_id=m, status="error", error=str(e)[:300],
                      purpose=msg.payload.get("purpose", "primary"))
            return
        thr = config.THRESHOLDS[m]
        fact = self.wm.ingest.ingest_metric(
            self.case["case_id"], m, spec["label"], spec["branch"], value,
            f"{thr[0]} {thr[1]:.0%}", status, support, res, self.name,
            purpose=msg.payload.get("purpose", "primary"))
        self.send("Evaluator", "evidence",
                  f"{spec['label']} = {self.fmt(m, value)} (threshold {thr[0]} {thr[1]:.0%}) "
                  f"→ {status} [{res.source}, {res.ms} ms]",
                  metric_id=m, value=value, status=status, support=support,
                  fact_id=fact["fact_id"], purpose=msg.payload.get("purpose", "primary"),
                  label=spec["label"], branch=spec["branch"],
                  threshold=f"{thr[0]} {thr[1]:.0%}", source=res.source, ms=res.ms)

    def on_recheck(self, msg):
        m = msg.payload["metric_id"]
        sql_t, recompute, compare_key = VERIFY[m]
        sql = sql_t.format(**self.params())
        try:
            res = self.data.run(sql)
            rows = res.records()
            recomputed = recompute(rows, self.case["oos_date"])
        except Exception as e:
            self.send("Evaluator", "recheck_result", f"verification query failed ({e})"[:200],
                      metric_id=m, recomputed=None, error=str(e)[:300])
            return
        fact = self.wm.ingest.ingest_metric(
            self.case["case_id"], m, METRICS[m]["label"] + " (independent recheck)",
            METRICS[m]["branch"], recomputed, "-", "verification",
            {"rows_checked": len(rows), "compared_field": compare_key}, res, self.name,
            purpose="verification")
        shown = (self.fmt(m, recomputed) if compare_key == "value"
                 else f"{recomputed:,.0f}" if recomputed is not None else "n/a")
        self.send("Evaluator", "recheck_result",
                  f"recomputed from {len(rows)} raw rows: {compare_key} = {shown}",
                  metric_id=m, recomputed=recomputed, compare_key=compare_key,
                  sample_rows=rows[:8], fact_id=fact["fact_id"])


    def on_counter_test(self, msg):
        m = msg.payload["metric_id"]
        test = COUNTER_TESTS[m]
        sql = test["sql"].format(**self.params())
        try:
            res = self.data.run(sql)
            row = res.first()
            early = float(row["early_rate"]) if row.get("early_rate") is not None else None
            late = float(row["late_rate"]) if row.get("late_rate") is not None else None
        except Exception as e:
            self.send("Evaluator", "counter_result", f"counter-test failed ({e})"[:200],
                      metric_id=m, early=None, late=None, error=str(e)[:300])
            return
        fact = self.wm.ingest.ingest_metric(
            self.case["case_id"], m, test["label"], METRICS[m]["branch"], early, "-",
            "counter_test", {"early_rate": early, "late_rate": late,
                             "days_observed": row.get("days_observed")},
            res, self.name, purpose="counter_test")
        self.send("Evaluator", "counter_result",
                  f"{test['label']}: {early:.1%} → {late:.1%} [{res.source}, {res.ms} ms]",
                  metric_id=m, early=early, late=late, fact_id=fact["fact_id"],
                  source=res.source, ms=res.ms)


    # -- business impact, asked for by the Writer before it drafts
    def on_impact(self, msg):
        p = msg.payload
        prm = self.params()
        out = {"window_days": IMPACT_WINDOW_DAYS, "warnings": [], "avoided": None,
               "currency": "₹"}
        try:
            q = {k: self.data.run(sql.format(**prm)) for k, sql in IMPACT_SQL.items()}
        except Exception as e:
            self.send("Writer", "impact_result", f"impact queries failed ({e})"[:200],
                      impact=None, error=str(e)[:300])
            return
        lost = q["lost"].first()
        out["lost_units"] = int(float(lost.get("lost_units") or 0))
        out["stockout_dates"] = [str(r["snapshot_date"])[:10] for r in q["stockout_days"].records()]
        out["sku_desc"] = (q["sku"].first() or {}).get("product_name") or self.case["sku_id"]
        out["dc_name"] = (q["dc"].first() or {}).get("dc_name") or self.case["dc_id"]
        avg_demand = float(q["avg_demand"].first().get("avg_daily_demand") or 0)
        row = q["economics"].first() or {}
        econ = {k: float(v) for k, v in row.items() if v is not None}
        out["net_price"] = econ.get("net_price_inr")
        out["lost_value"] = round(out["lost_units"] * econ["net_price_inr"]) if econ else None

        # early warning per confirmed cause
        for c in p.get("causes", []):
            m = c["metric_id"]
            if m not in ONSET:
                continue
            sql, fn = ONSET[m]
            rows = self.data.run(sql.format(**prm)).records()
            direction, thr = config.THRESHOLDS[m]
            start, run, total = onset(rows, sql, fn, self.case["oos_date"], direction, thr)
            if start:
                import datetime as _dt
                days = (_dt.date.fromisoformat(self.case["oos_date"])
                        - _dt.date.fromisoformat(start)).days
                out["warnings"].append({"metric_id": m, "cause": c["cause"], "since": start,
                                        "days_before": days, "weeks_off": total,
                                        "chronic": total >= 8})

        # the wrong fix a rollback prevented, sized to the cause that is really there
        kept = {c["metric_id"] for c in p.get("causes", [])}
        for rb in p.get("rollbacks", []):
            if rb["metric_id"] not in NAIVE_FIX or not econ or not avg_demand:
                continue
            from .metrics import _as_of, _days, _f
            rows = self.data.run(VERIFY["lead_time_overrun_pct"][0].format(**prm)).records()
            units, reason = 0, ""
            if "lead_time_overrun_pct" in kept:
                late = [x for x in (_days(_as_of(r["delivery_date"], self.case["oos_date"]),
                                          r["dispatch_date"]) - _f(r["std_lead_time_days"])
                                    for r in rows) if x > 0]
                if late:
                    avg_delay = sum(late) / len(late)
                    units = round(avg_delay * avg_demand / 100) * 100
                    reason = (f"to absorb {avg_delay:.1f}-day delivery delays; the delays "
                              "would continue")
            elif "fill_rate_pct" in kept:
                short = [(_f(r["ordered_qty"]) - (_f(r["accepted_qty"]) or 0)) for r in rows
                         if r["accepted_qty"] not in (None, "")
                         and _f(r["accepted_qty"]) < 0.95 * _f(r["ordered_qty"])]
                if short:
                    avg_short = sum(short) / len(short)
                    units = round(avg_short / 100) * 100
                    reason = ("to cover the plant's short-shipments; the plant would keep "
                              "shipping short")
            if units:
                value = int(units * econ["unit_cost_inr"])
                out["avoided"] = {"cause": rb["cause"], "fix": NAIVE_FIX[rb["metric_id"]],
                                  "units": units, "value": value, "reason": reason,
                                  "carrying_per_year": round(value * config.CARRYING_RATE)}
        fact = self.wm.ingest.ingest_metric(
            self.case["case_id"], "business_impact", "Business impact", "impact",
            out["lost_units"], "-", "impact",
            {"lost_value": out["lost_value"], "stockout_days": len(out["stockout_dates"])},
            q["lost"], self.name, purpose="impact")
        cur = out["currency"]
        summary = (f"{out['lost_units']:,} units of demand lost in {IMPACT_WINDOW_DAYS} days"
                   + (f" ({cur}{out['lost_value']:,})" if out["lost_value"] is not None else "")
                   + f"; out of stock on {len(out['stockout_dates'])} "
                   + ("day" if len(out["stockout_dates"]) == 1 else "days"))
        onsets = [w for w in out["warnings"] if not w["chronic"]]
        if onsets:
            w = max(onsets, key=lambda x: x["days_before"])
            summary += f"; '{w['cause']}' was visible {w['days_before']} days before"
        for w in out["warnings"]:
            if w["chronic"]:
                summary += f"; '{w['cause']}' was off target in {w['weeks_off']} of 12 weeks (chronic)"
        if out["avoided"]:
            summary += f"; wasted spend averted: {cur}{out['avoided']['value']:,} of extra stock"
        self.send("Writer", "impact_result", summary, impact=out, fact_id=fact["fact_id"])


# ---------------------------------------------------------------- Evaluator
class Evaluator(Agent):
    name = "Evaluator"

    def __init__(self, *a):
        super().__init__(*a)
        self.evidence, self.borderline, self.confirmed, self.ruled_out = {}, [], [], []
        self.loops, self.revisions = 0, 0
        self.unexplained = False
        self.judgements = []
        self.counter_tested = set()
        self.awaiting = None   # causes held while a counter-test runs
        self.checkpoint = False          # set by main.investigate when a human is present
        self.checkpoint_done = False
        self.held_review = None

    def on_plan(self, msg):
        pass  # noted in the trace; the Evaluator holds the plan to account at review

    def on_evidence(self, msg):
        p = msg.payload
        m = p["metric_id"]
        self.evidence[m] = p
        label = METRICS[m]["label"]
        if p["status"] in ("error", "no_data"):
            self.send("Planner", "verdict", f"{label}: inconclusive (no usable data)",
                      metric_id=m, verdict="inconclusive")
        elif p["status"] == "flagged":
            self.send("Investigator", "recheck",
                      f"{label} is off; verify it independently from raw rows before I accept it",
                      metric_id=m)
        elif p["status"] == "borderline":
            self.borderline.append(m)
            self.send("Planner", "verdict",
                      f"{label} = {self.fmt(m, p['value'])} is near the threshold; "
                      "provisionally ruled out, will re-judge with full context at review",
                      metric_id=m, verdict="provisionally_ruled_out")
        else:
            self.ruled_out.append(m)
            self.send("Planner", "verdict",
                      f"{label} = {self.fmt(m, p['value'])} is healthy → ruled out with evidence",
                      metric_id=m, verdict="ruled_out")

    def on_recheck_result(self, msg):
        p = msg.payload
        m = p["metric_id"]
        ev = self.evidence.get(m, {})
        target = ev.get("value") if p.get("compare_key") == "value" else \
            ev.get("support", {}).get(p.get("compare_key"))
        rc = p.get("recomputed")
        agree = (rc is not None and target is not None and
                 abs(float(rc) - float(target)) <= max(0.005, 0.01 * abs(float(target))))
        if agree:
            self.confirmed.append(m)
            self.send("Planner", "verdict",
                      f"{METRICS[m]['label']} confirmed: independent recheck agrees",
                      metric_id=m, verdict="confirmed", recheck_fact=p.get("fact_id"))
        else:
            self.send("Planner", "verdict",
                      f"{METRICS[m]['label']}: recheck disagrees ({rc} vs {target}) → inconclusive",
                      metric_id=m, verdict="inconclusive")

    # -- review: judge borderline signals, then approve or send the team back
    def on_review_request(self, msg):
        if self.checkpoint and not self.checkpoint_done:
            self.checkpoint_done = True
            self.held_review = msg
            self.ask_human(msg)
            return
        self.review(msg)

    # -- analyst checkpoint: the human steers, the Evaluator still recommends
    def recommendation(self, msg):
        causes = msg.payload["causes"]
        if not causes:
            return ("dig deeper", "No cause is confirmed yet, and a stockout with no cause is "
                    "not an acceptable answer. I will send the team back to dig deeper.")
        for c in causes:
            m = c["metric_id"]
            if m in COUNTER_TESTS and any(o["metric_id"] != m for o in causes):
                return ("counter-test", f"Before sign-off I want to test whether '{c['cause']}' "
                        "is a real cause or only a symptom of the other finding.")
        return ("write report", "Every candidate cause is verified. I recommend writing the report.")

    def ask_human(self, msg):
        kind, text = self.recommendation(msg)
        causes = msg.payload["causes"]
        options = [{"id": "recommended", "label": f"Go with the Evaluator: {kind}"}]
        for k in DRILL_DOWNS:
            if k not in msg.payload["visited"]:
                options.append({"id": f"dig:{k}", "label": f"Also check: {PLAIN.get(k, METRICS[k]['label']).lower()}",
                                "detail": DRILL_DOWNS[k]})
        self.send("You", "checkpoint",
                  f"Findings so far: {'; '.join(c['cause'] for c in causes) or 'no cause confirmed'}. "
                  f"My recommendation: {text}",
                  causes=[c["cause"] for c in causes], recommendation=text,
                  recommendation_kind=kind, options=options)

    def on_direction(self, msg):
        p = msg.payload
        choice = p.get("choice", "recommended")
        if choice == "text":
            choice = self.interpret(p.get("text", ""), p.get("options", []))
        held = self.held_review
        if choice.startswith("dig:"):
            m = choice[4:]
            self.loops += 1
            reason = f"You asked the team to check {METRICS[m]['label']}"
            self.judgements.append({"loop": self.loops, "dig_deeper": [m], "reason": reason,
                                    "reasoner": "you (analyst checkpoint)"})
            self.send("Planner", "dig_deeper", f"LOOP {self.loops}: {reason}",
                      metrics=[m], reason=reason, loop=self.loops, by="you")
            return
        self.review(held)

    def interpret(self, text, options):
        """Map a free-text instruction from the analyst to one of the options."""
        ids = [o["id"] for o in options]

        def fallback():
            t = text.lower()
            for key, words in (("dig:under_forecast_error_recent_pct", ("recent", "demand", "forecast", "surge")),
                               ("dig:lead_time_overrun_pct", ("transport", "lead", "delay", "carrier")),
                               ("dig:order_qty_deviation_pct", ("order", "quantity", "replenish"))):
                if key in ids and any(w in t for w in words):
                    return "", {"choice": key}
            return "", {"choice": "recommended"}

        listing = "\n".join(f"- {o['id']}: {o['label']}" for o in options)
        r = self.think("You map an analyst's instruction to exactly one option id. "
                       "Reply with JSON only.",
                       f"Instruction: {text}\nOptions:\n{listing}\n"
                       'JSON: {"choice": "<option id>"}', fallback)
        c = r.data.get("choice")
        return c if c in ids else fallback()[1]["choice"]

    def review(self, msg):
        causes = msg.payload["causes"]
        context = self.wm.context.case_context(self.case["case_id"])
        for m in list(self.borderline):
            self.judge_borderline(m, causes, context)
        self.borderline = []

        if not causes:
            options = [k for k in DRILL_DOWNS if k not in msg.payload["visited"]]
            if self.loops < config.MAX_DIG_DEEPER_LOOPS and options:
                self.loops += 1
                self.dig_deeper(options, context)
                return
            self.unexplained = True

        # Try to falsify each confirmed cause that has a counter-test, but only
        # when another confirmed cause exists that it could be a symptom of.
        for c in causes:
            m = c["metric_id"]
            others = [o for o in causes if o["metric_id"] != m]
            if m in COUNTER_TESTS and m not in self.counter_tested and others:
                self.counter_tested.add(m)
                self.awaiting = causes
                self.send("Investigator", "counter_test",
                          f"Before I accept '{c['cause']}', test it: "
                          f"{COUNTER_TESTS[m]['question']}",
                          metric_id=m, others=[o["cause"] for o in others])
                return

        self.send("Writer", "write_report",
                  f"{len(causes)} confirmed cause(s); {len(self.ruled_out)} driver(s) ruled out"
                  + (f"; {len(msg.payload.get('rollbacks', []))} rolled back"
                     if msg.payload.get("rollbacks") else ""),
                  causes=causes, unexplained=self.unexplained,
                  rollbacks=msg.payload.get("rollbacks", []),
                  challenges=self.judgements)

    def on_counter_result(self, msg):
        p = msg.payload
        m = p["metric_id"]
        causes = self.awaiting or []
        others = [o["cause"] for o in causes if o["metric_id"] != m]
        early, late = p.get("early"), p.get("late")
        thr = config.THRESHOLDS[m][1]
        label = METRICS[m]["label"]
        if early is None or late is None:
            self.send("Planner", "cause_upheld",
                      f"counter-test inconclusive; '{label}' stands", metric_id=m)
            return
        recent_onset = early < thr and late >= 2 * max(early, 0.01)
        if recent_onset:
            reason = (f"breaches were {early:.1%} in weeks 12-7 but {late:.1%} in weeks 6-1: "
                      f"they began only after '{others[0]}' started draining stock, so this "
                      f"is a symptom, not a root cause")
            self.judgements.append({"counter_test": m, "outcome": "rolled_back",
                                    "early": early, "late": late, "reason": reason})
            if m in self.confirmed:
                self.confirmed.remove(m)
            self.ruled_out.append(m)
            self.send("Planner", "rollback", f"ROLLBACK '{label}': {reason}",
                      metric_id=m, symptom_of=others[0], reason=reason,
                      early=early, late=late, fact_id=p.get("fact_id"))
        else:
            reason = (f"breaches were already {early:.1%} in weeks 12-7 (then {late:.1%}): "
                      "a chronic problem that predates the other cause, so it stands")
            self.judgements.append({"counter_test": m, "outcome": "upheld",
                                    "early": early, "late": late, "reason": reason})
            self.send("Planner", "cause_upheld", f"'{label}' survives the counter-test: {reason}",
                      metric_id=m, reason=reason)

    def judge_borderline(self, m, causes, context):
        ev = self.evidence[m]
        thr = config.THRESHOLDS[m]
        system = ("You are the Evaluator in a supply-chain root-cause team. You decide "
                  "whether a metric that sits just inside its threshold is a root cause, "
                  "a symptom of another confirmed cause, or noise. Reply with JSON only.")
        user = (f"Case facts so far:\n{context}\n\nConfirmed causes: "
                f"{[c['cause'] for c in causes] or 'none'}\n\nBorderline metric: "
                f"{METRICS[m]['label']} = {ev['value']:.1%} (threshold {thr[0]} {thr[1]:.0%}). "
                'Classify. JSON: {"classification": "symptom|noise|contributing", '
                '"reason": "one sentence"}')

        def fallback():
            if causes:
                return "", {"classification": "symptom",
                            "reason": f"Close to threshold, and consistent with the confirmed "
                                      f"cause '{causes[0]['cause']}' draining stock; treated as "
                                      "a symptom, not a separate root cause."}
            return "", {"classification": "noise",
                        "reason": "Inside threshold with no confirmed driver to explain it."}

        r = self.think(system, user, fallback)
        cls = r.data.get("classification", "noise")
        cls = cls if cls in ("symptom", "noise", "contributing") else "noise"
        self.judgements.append({"metric_id": m, "value": ev["value"],
                                "classification": cls,
                                "reason": r.data.get("reason", ""), "reasoner": r.model})
        if cls == "contributing" and "cause" in TREE.get(m, {}):
            causes.append({"metric_id": m, "cause": TREE[m]["cause"],
                           "owner": TREE[m]["owner"], "basis": "borderline, judged contributing"})
        else:
            self.ruled_out.append(m)
        self.send("Planner", "judgement",
                  f"{METRICS[m]['label']} near threshold → {cls}: {r.data.get('reason', '')[:120]}",
                  metric_id=m, classification=cls)

    def dig_deeper(self, options, context):
        c = self.case
        system = ("You are the Evaluator in a supply-chain root-cause team. A stockout "
                  "happened but no cause has been confirmed. A stockout with no cause is "
                  "not an acceptable answer: choose which extra checks the team must run. "
                  "Reply with JSON only.")
        opts = "\n".join(f"- {k}: {DRILL_DOWNS[k]}" for k in options)
        user = (f"Stockout {c['product_name']} (SKU {c['sku_id']}) at {c['dc_name']} on "
                f"{c['oos_date']}.\nFacts:\n"
                f"{context}\n\nAvailable extra checks:\n{opts}\n\nPick one or two. "
                'JSON: {"metrics": ["..."], "reason": "one sentence"}')

        def fallback():
            first = "under_forecast_error_recent_pct" if \
                "under_forecast_error_recent_pct" in options else options[0]
            return "", {"metrics": [first],
                        "reason": "Supply was healthy and the 12-week forecast error is "
                                  "small, so look for a recent demand change hidden in "
                                  "the long average."}

        r = self.think(system, user, fallback)
        picked = [m for m in r.data.get("metrics", []) if m in options][:2]
        if not picked:
            picked = fallback()[1]["metrics"]
        reason = r.data.get("reason", "") or "inconclusive first pass"
        self.judgements.append({"loop": self.loops, "dig_deeper": picked,
                                "reason": reason, "reasoner": r.model})
        self.send("Planner", "dig_deeper",
                  f"LOOP {self.loops}: no confirmed cause; not acceptable. {reason[:140]}",
                  metrics=picked, reason=reason, loop=self.loops)

    # -- sign-off: every claim in the report must match the evidence
    def on_sign_off(self, msg):
        draft = msg.payload["draft"]
        allowed = {c["cause"] for c in msg.payload["causes"]}
        issues = []
        for c in draft.get("causes", []):
            if c.get("cause") not in allowed:
                issues.append(f"Cause '{c.get('cause')}' is not a confirmed finding.")
        missing = allowed - {c.get("cause") for c in draft.get("causes", [])}
        for mcause in missing:
            issues.append(f"Confirmed cause '{mcause}' is missing from the report.")
        known = set()
        for f in self.wm.store.facts.values():
            v = f["value"]
            if isinstance(v, (int, float)) and f["case_id"] == self.case["case_id"]:
                known.add(abs(round(v * 100, 1)))
            for sv in (f.get("support") or {}).values():
                if isinstance(sv, float) and abs(sv) <= 1:
                    known.add(abs(round(sv * 100, 1)))
        for _, (_, thr) in config.THRESHOLDS.items():
            known.add(round(thr * 100, 1))
        text = json.dumps(draft, ensure_ascii=False)
        if re.search(r"(₹|\bRs\.?\s?\d|\bINR\b|\blakh\b|\$\s?\d)", text):
            issues.append("Money figures come from the impact block; remove them from the prose.")
        for num in re.findall(r"(\d+(?:\.\d+)?)\s*%", text):  # sign-insensitive
            n = float(num)
            if not any(abs(n - k) <= 0.6 for k in known):
                issues.append(f"'{num}%' does not match any measured value or threshold.")
        if issues and msg.payload.get("template"):
            # The evidence-only template is built directly from the facts; accept it
            # and record the residual issues rather than loop forever.
            self.send("Writer", "approved", "evidence-only template accepted",
                      residual_issues=issues)
        elif issues and self.revisions < config.MAX_REPORT_REVISIONS:
            self.revisions += 1
            self.send("Writer", "revise",
                      f"veto #{self.revisions}: {len(issues)} unsupported claim(s): {issues[0][:100]}",
                      issues=issues)
        elif issues:
            self.send("Writer", "revise", "too many revisions; use the evidence-only template",
                      issues=issues, force_template=True)
        else:
            self.send("Writer", "approved", "every claim traced to evidence; report approved")


# ---------------------------------------------------------------- You (the analyst)
class Human(Agent):
    """The analyst, as a member of the team. Replies arrive from the web page."""
    name = "You"
    inbox = None          # a queue the web server puts the analyst's choice into
    wait_s = 600

    def on_checkpoint(self, msg):
        import queue as _q
        reply = None
        if self.inbox is not None:
            try:
                reply = self.inbox.get(timeout=self.wait_s)
            except _q.Empty:
                reply = None
        if not reply:
            reply = {"choice": "recommended", "text": "",
                     "note": "no reply; continuing with the Evaluator's recommendation"}
        options = msg.payload.get("options", [])
        label = next((o["label"] for o in options if o["id"] == reply.get("choice")), "")
        said = reply.get("text") or label or reply.get("note", "")
        self.send("Evaluator", "direction", said, choice=reply.get("choice", "recommended"),
                  text=reply.get("text", ""), options=options)


def _lower_first(text):
    return text if text[:2].isupper() else text[:1].lower() + text[1:]


def _nice_date(iso):
    import datetime as _dt
    d = _dt.date.fromisoformat(iso)
    return f"{d.day} {d:%b}"


# ---------------------------------------------------------------- Writer
class Writer(Agent):
    name = "Writer"

    def __init__(self, *a):
        super().__init__(*a)
        self.causes, self.unexplained, self.final, self.draft = [], False, None, None
        self.rollbacks, self.challenges = [], []
        self.impact = None

    def evidence_pack(self):
        lines = []
        for f in self.wm.store.facts.values():
            if f["purpose"] not in ("primary", "drill_down") or f["case_id"] != self.case["case_id"]:
                continue
            lines.append(f"- {f['label']}: {f['value']:.1%} (threshold {f['threshold']}; "
                         f"{f['status']})" if isinstance(f["value"], float) else
                         f"- {f['label']}: {f['value']}")
        return "\n".join(lines)

    def template(self):
        facts = {f["metric_id"]: f for f in self.wm.store.facts.values()
                 if f["purpose"] in ("primary", "drill_down")}
        causes = []
        for c in self.causes:
            f = facts.get(c["metric_id"])
            ev = f"{f['label']} = {f['value']:.1%} (threshold {f['threshold']})" if f else ""
            causes.append({"cause": c["cause"], "evidence": ev,
                           "action": self.actions().get(c["cause"], "")})
        ruled = [{"driver": f["label"], "why": f"{f['value']:.1%} vs threshold "
                  f"{f['threshold']}: within normal range"}
                 for f in facts.values() if f["status"] in ("clear", "borderline")
                 and f["metric_id"] not in {c["metric_id"] for c in self.causes}
                 and isinstance(f["value"], float)]
        for rb in self.rollbacks:
            f = facts.get(rb["metric_id"])
            ruled.append({"driver": f["label"] if f else rb["metric_id"],
                          "why": f"rolled back after counter-test: {rb['reason']}"})
        c0 = self.case
        names = [c["cause"] for c in causes]
        what = (names[0] if len(names) == 1 else
                ", ".join(names[:-1]) + " and " + _lower_first(names[-1])) if names else ""
        head = (f"{what} caused the {c0.get('product_name', c0['sku_id'])} stockout at "
                f"{c0.get('dc_name', c0['dc_id'])} on {_nice_date(c0['oos_date'])}"
                if names else "No root cause could be confirmed from the available data.")
        narrative = head + "."
        imp = self.impact or {}
        if imp.get("stockout_dates") and len(imp["stockout_dates"]) > 1:
            narrative += (f" The stockout repeated on {len(imp['stockout_dates']) - 1} more day(s) in "
                          f"the following {imp['window_days']} days, so the cause is still active.")
        for rb in self.rollbacks:
            narrative += (f" The team first confirmed '{rb['cause']}', then rolled it back: "
                          f"{rb['reason']}.")
        return {"headline": head, "causes": causes, "ruled_out": ruled,
                "narrative": narrative}

    def fact_sheet(self):
        """A short, pre-digested summary for Nemotron. Nemotron Lightning always
        reasons before it answers; a long, rule-heavy prompt makes it reason past
        Nightshift's provider deadline, so the Writer hands it only the facts."""
        c = self.case
        facts = {f["metric_id"]: f for f in self.wm.store.facts.values()
                 if f["purpose"] in ("primary", "drill_down")}
        lines = [f"Product: {c['product_name']} at {c['dc_name']}, out of stock on "
                 f"{_nice_date(c['oos_date'])}."]
        for x in self.causes:
            f = facts.get(x["metric_id"])
            num = f" ({PLAIN.get(x['metric_id'], f['label']).lower()}: {f['value']:.1%})" \
                if f and isinstance(f["value"], float) else ""
            lines.append(f"Root cause: {x['cause']}{num}. Owner: {x['owner']}.")
        for rb in self.rollbacks:
            lines.append(f"Ruled out as a symptom: {rb['cause']} (it started only after the "
                         f"real cause: {rb.get('early', 0):.1%} of days before, "
                         f"{rb.get('late', 0):.1%} after).")
        for w in (self.impact or {}).get("warnings", []):
            if not w["chronic"]:
                lines.append(f"Warning sign visible {w['days_before']} days before the stockout.")
        if not self.causes:
            lines.append("No root cause could be confirmed.")
        return "\n".join(lines)

    def ask_draft(self, issues=None):
        user = ("Write a one-sentence headline and a two-sentence summary for a supply chain "
                "manager, using only these facts. No money amounts.\n"
                + self.fact_sheet() + "\n"
                + (f"Fix this: {issues[0]}\n" if issues else "")
                + 'JSON: {"headline": "...", "narrative": "..."}')
        tpl = self.template()
        r = self.think("Reply with JSON only.", user,
                       lambda: ("", {"headline": tpl["headline"], "narrative": tpl["narrative"]}),
                       max_tokens=config.WRITER_MAX_TOKENS, retries=2)
        # Nemotron writes the words; causes, evidence, next steps and ruled-out
        # drivers come straight from the verified facts.
        return {"headline": r.data.get("headline") or tpl["headline"],
                "narrative": r.data.get("narrative") or tpl["narrative"],
                "causes": tpl["causes"], "ruled_out": tpl["ruled_out"]}

    def on_write_report(self, msg):
        self.causes = sorted(msg.payload["causes"], key=self._severity, reverse=True)
        self.unexplained = msg.payload["unexplained"]
        self.rollbacks = msg.payload.get("rollbacks", [])
        self.challenges = msg.payload.get("challenges", [])
        self.send("Investigator", "impact",
                  "Before I write: what did this cost, how early was it visible, and what "
                  "would the wrong fix have cost?",
                  causes=self.causes, rollbacks=self.rollbacks)

    def on_impact_result(self, msg):
        self.impact = msg.payload.get("impact")
        self.draft = self.ask_draft()
        self.send("Evaluator", "sign_off", "draft ready; requesting sign-off",
                  draft=self.draft, causes=self.causes)

    def actions(self):
        """Concrete next step per cause, filled from the evidence."""
        imp = self.impact or {}
        facts = {f["metric_id"]: f for f in self.wm.store.facts.values()
                 if f["purpose"] in ("primary", "drill_down")}
        warn = {w["metric_id"]: w for w in imp.get("warnings", [])}
        out = {}
        for c in self.causes:
            m, f = c["metric_id"], facts.get(c["metric_id"])
            if m in ACTIONS and f and isinstance(f["value"], float):
                w = warn.get(m)
                since = ""
                if w and not w["chronic"]:
                    since = f" (visible from {_nice_date(w['since'])})"
                elif w:
                    since = f" (off target in {w['weeks_off']} of the last 12 weeks)"
                out[c["cause"]] = ACTIONS[m].format(
                    value=f["value"], since=since,
                    dc_name=imp.get("dc_name", self.case["dc_id"]),
                    sku_desc=imp.get("sku_desc", self.case["sku_id"]))
            else:
                out[c["cause"]] = f"Route to {c['owner']} for corrective action."
        return out

    def on_revise(self, msg):
        forced = bool(msg.payload.get("force_template"))
        self.draft = self.template() if forced else self.ask_draft(issues=msg.payload["issues"])
        self.send("Evaluator", "sign_off",
                  "evidence-only template; requesting sign-off" if forced
                  else "revised draft; requesting sign-off",
                  draft=self.draft, causes=self.causes, template=forced)

    def on_approved(self, msg):
        self.final = self.draft

    def _severity(self, cause):
        f = next((f for f in self.wm.store.facts.values()
                  if f["metric_id"] == cause["metric_id"]
                  and f["purpose"] in ("primary", "drill_down")),
                 None)
        if not f or not isinstance(f["value"], float):
            return 0
        direction, thr = config.THRESHOLDS[cause["metric_id"]]
        return abs(f["value"] - thr) / thr
