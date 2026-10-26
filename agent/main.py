"""Run a stockout investigation.

  python -m agent.main --list            list stockout events
  python -m agent.main --event OOS-002   investigate one stockout
  python -m agent.main --all             investigate every stockout

Writes:
  logs/<run>/trace.jsonl          every agent-to-agent message
  logs/<run>/world_model.jsonl    every fact with provenance (World Model engine)
  logs/<run>/receipts.jsonl       one Meterless receipt summary per model call
  outputs/<event>.json / .md      the signed-off root-cause report
"""
import argparse
import datetime as dt
import json
import sys
import time

from . import config
from .agents import Bus, Evaluator, Human, Investigator, Planner, Writer
from .data_client import get_client
from .llm import Nemotron
from .metrics import PLAIN
from .world_model import WorldModel


def list_events(data):
    # One federated query across three systems: the stockout log (WMS), the
    # product master (planning) and prices (finance).
    w, p, f = config.SOURCES["wms"], config.SOURCES["planning"], config.SOURCES["finance"]
    sql = (f"SELECT e.event_id, e.sku_id, s.product_name, s.category, e.dc_id, d.dc_name, "
           f"e.oos_date, e.lost_demand_qty, e.lost_demand_qty * x.net_price_inr AS lost_value_inr "
           f"FROM {w}.stockout_events e "
           f"JOIN {p}.skus s ON s.sku_id = e.sku_id "
           f"JOIN {w}.dcs d ON d.dc_id = e.dc_id "
           f"LEFT JOIN {f}.sku_economics x ON x.sku_id = e.sku_id ORDER BY e.event_id")
    return data.run(sql).records()


def investigate(event, data, llm, printer=print, listener=None, human_inbox=None):
    run_id = f"{event['event_id']}_{dt.datetime.now():%Y%m%d_%H%M%S}"
    run_dir = config.LOG_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    case = {"case_id": event["event_id"], "sku_id": event["sku_id"],
            "product_name": event.get("product_name") or event["sku_id"],
            "dc_id": event["dc_id"], "dc_name": event.get("dc_name") or event["dc_id"],
            "oos_date": str(event["oos_date"])[:10],
            "lost_demand_qty": event["lost_demand_qty"]}

    wm = WorldModel(run_dir / "world_model.jsonl")
    wm.store.upsert_entity(case["case_id"], "stockout_case", **case)
    receipts = []
    bus = Bus(run_dir / "trace.jsonl", printer=printer, listener=listener)
    agents = [cls(case, wm, llm, data, receipts)
              for cls in (Planner, Investigator, Evaluator, Writer)]
    for a in agents:
        bus.register(a)
    planner, _, evaluator, writer = agents
    if human_inbox is not None:               # analyst checkpoint (web interface)
        you = Human(case, wm, llm, data, receipts)
        you.inbox = human_inbox
        bus.register(you)
        evaluator.checkpoint = True
    if listener:
        listener({"type": "case", "case": case, "run_id": run_id})

    t0 = time.time()
    printer(f"\n=== Investigating {case['case_id']}: {case['product_name']} (SKU {case['sku_id']}) "
            f"at {case['dc_name']}, "
            f"stockout on {case['oos_date']} ===")
    bus.send("System", "Planner", "case_opened",
             f"{case['product_name']} (SKU {case['sku_id']}) at {case['dc_name']} out of stock "
             f"on {case['oos_date']}",
             **case)
    steps = bus.run()

    with open(run_dir / "receipts.jsonl", "w") as f:
        for r in receipts:
            f.write(json.dumps(r, default=str) + "\n")

    report = writer.final or writer.template()
    facts = [f for f in wm.store.facts.values()]
    result = {
        "case": case, "run_id": run_id,
        "status": "approved" if writer.final else "fallback_template",
        "report": report,
        "confirmed_causes": writer.causes,
        "rollbacks": planner.rollbacks,
        "chains": chains(planner, wm, writer.causes),
        "impact": writer.impact,
        "loops": evaluator.loops, "report_revisions": evaluator.revisions,
        "checkpoint": evaluator.checkpoint,
        "evaluator_judgements": evaluator.judgements,
        "evidence": [{k: f[k] for k in ("fact_id", "label", "branch", "purpose", "value",
                                        "threshold", "status", "support", "provenance")}
                     for f in facts],
        "messages": steps,
        "model_calls": len(receipts),
        "receipts": [{k: r[k] for k in ("agent", "model", "receipt_id", "latency_ms",
                                         "tokens", "fallback")} for r in receipts],
        "models_used": sorted({r["model"] for r in receipts}),
        "elapsed_s": round(time.time() - t0, 1),
        "sample_mode": config.SAMPLE_MODE,
    }
    out_json = config.OUTPUT_DIR / f"{case['case_id']}.json"
    out_json.write_text(json.dumps(result, indent=2, default=str))
    (config.OUTPUT_DIR / f"{case['case_id']}.md").write_text(to_markdown(result))
    printer(f"=== Done in {result['elapsed_s']}s: {steps} messages, {evaluator.loops} "
            f"dig-deeper loop(s), {len(planner.rollbacks)} rollback(s), "
            f"{evaluator.revisions} report revision(s), "
            f"{len(receipts)} model call(s) via {', '.join(result['models_used'])}")
    printer(receipt_table(result["receipts"]))
    printer(f"Report: {out_json}\nTrace:  {run_dir}/trace.jsonl")
    return result


def chains(planner, wm, causes):
    """For each confirmed cause: the chain of evidence from tree root to cause."""
    facts = {f["metric_id"]: f for f in wm.store.facts.values()
             if f["purpose"] in ("primary", "drill_down")}
    out = []
    for c in causes:
        steps = []
        for m in planner.chain(c["metric_id"]):
            f = facts.get(m)
            if f:
                steps.append({"metric_id": m, "label": f["label"], "branch": f["branch"],
                              "plain": PLAIN.get(m, ""),
                              "value": f["value"], "threshold": f["threshold"],
                              "status": f["status"]})
        out.append({"cause": c["cause"], "owner": c.get("owner"), "steps": steps})
    return out


def receipt_table(receipts):
    """Readable summary of every model call and its Meterless receipt."""
    lines = ["", "Model calls (Meterless receipts):",
             f"  {'Agent':<11} {'Model':<38} {'Receipt':<20} {'Time':>6} {'Tokens':>7}"]
    for r in receipts:
        model = r["model"] + (" (fallback)" if r["fallback"] else "")
        lines.append(f"  {r['agent']:<11} {model:<38} {r['receipt_id'] or '-':<20} "
                     f"{r['latency_ms'] / 1000:>5.1f}s {r['tokens'] or '-':>7}")
    return "\n".join(lines) + "\n"


def pct(v):
    return f"{v:.1%}" if isinstance(v, float) else str(v)


def to_markdown(r):
    c, rep = r["case"], r["report"]
    lines = [f"# Root-cause report: {c['product_name']} (SKU {c['sku_id']}) at {c['dc_name']}, "
             f"stockout on {c['oos_date']}",
             "", f"**{rep.get('headline', '')}**", "", rep.get("narrative", ""), "",
             "## Confirmed causes"]
    for i, x in enumerate(rep.get("causes", []), 1):
        lines.append(f"{i}. **{x.get('cause')}**: {x.get('evidence', '')}. "
                     f"*Next step:* {x.get('action', '')}")
    if not rep.get("causes"):
        lines.append("None confirmed.")
    lines += ["", "## Ruled out (with evidence)"]
    for x in rep.get("ruled_out", []):
        lines.append(f"- {x.get('driver')}: {x.get('why')}")
    if r["evaluator_judgements"]:
        lines += ["", "## How the team challenged itself"]
        for j in r["evaluator_judgements"]:
            if "dig_deeper" in j:
                lines.append(f"- Loop {j['loop']}: Evaluator rejected 'no cause found' and "
                             f"asked for {', '.join(j['dig_deeper'])}: {j['reason']}")
            elif "counter_test" in j:
                verb = ("**rolled back**" if j["outcome"] == "rolled_back"
                        else "**upheld**")
                lines.append(f"- Counter-test on {j['counter_test']}: cause {verb}: "
                             f"{j['reason']}")
            else:
                lines.append(f"- Borderline {j['metric_id']} ({pct(j['value'])}) judged "
                             f"**{j['classification']}**: {j['reason']}")
    lines += ["", "## Evidence chain", "", "| Fact | Value | Threshold | Status | Source |",
              "|---|---|---|---|---|"]
    for e in r["evidence"]:
        lines.append(f"| {e['label']} | {pct(e['value'])} | {e['threshold']} | "
                     f"{e['status']} | {e['provenance']['source']} |")
    lines += ["", "## Model calls (Meterless receipts)", "",
              "| Agent | Model | Receipt | Time | Tokens |", "|---|---|---|---|---|"]
    for x in r["receipts"]:
        lines.append(f"| {x['agent']} | {x['model']}{' (fallback)' if x['fallback'] else ''} "
                     f"| {x['receipt_id'] or '-'} | {x['latency_ms'] / 1000:.1f}s | "
                     f"{x['tokens'] or '-'} |")
    lines += ["", f"*{r['messages']} agent messages · {r['loops']} dig-deeper loop(s) · "
              f"{r['report_revisions']} report revision(s) · {r['model_calls']} model calls "
              f"via {', '.join(r['models_used'])} · run {r['run_id']}*"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Chain of Evidence stockout investigator")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--event")
    g.add_argument("--all", action="store_true")
    args = ap.parse_args(argv)

    data = get_client()
    events = list_events(data)
    if args.list:
        for e in events:
            print(f"{e['event_id']}  {e['sku_id']}  {e['product_name']:<32} {e['dc_name']:<13} "
                  f"{str(e['oos_date'])[:10]}  "
                  f"{e['lost_demand_qty']:>4} units short that day  "
                  f"₹{float(e.get('lost_value_inr') or 0):>9,.0f} lost")
        return 0
    llm = Nemotron()
    chosen = events if args.all else [e for e in events if e["event_id"] == args.event]
    if not chosen:
        print(f"No stockout event {args.event}. Use --list.")
        return 1
    for e in chosen:
        investigate(e, data, llm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
