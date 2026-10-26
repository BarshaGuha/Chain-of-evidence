"""
Root-cause metrics for stockout analysis (adapted from an OOS root-cause tree).

Each metric is a parameterised SQL template run through Zetaris. Templates use
Spark-style date functions (date_sub, datediff), which Zetaris Lightning SQL
supports. Placeholders:
  {sku}, {dc}        SKU and DC of the stockout
  {d}                stockout day D, as 'YYYY-MM-DD'
  {p1_days}          length of look-back period P1 in days (default 84 = 12 weeks)
  {orders}, {planning}, {wms}   fully qualified schema prefixes for each source

Every query returns one row with a column named `value` plus supporting
columns that become part of the evidence shown to the user.
"""

P1 = "BETWEEN date_sub(DATE '{d}', {p1_days}) AND date_sub(DATE '{d}', 1)"

METRICS = {
    "fill_on_time_pct": {
        "label": "Qty Fill On-Time %",
        "branch": "supply",
        "definition": "Qty accepted on time / total ordered qty, for orders "
                      "with required delivery date in P1",
        "sql": f"""
SELECT 1.0 * SUM(CASE WHEN delivery_date <= required_delivery_date
                      THEN COALESCE(accepted_qty, 0) ELSE 0 END)
       / NULLIF(SUM(ordered_qty), 0) AS value,
       COUNT(*) AS orders_in_window, SUM(ordered_qty) AS ordered_qty
FROM {{orders}}.replenishment_orders
WHERE sku_id = '{{sku}}' AND dc_id = '{{dc}}'
  AND required_delivery_date {P1}""",
    },
    "fill_rate_pct": {
        "label": "Qty Fill Rate %",
        "branch": "supply",
        "definition": "Qty accepted (any time) / total ordered qty, orders due in P1",
        "sql": f"""
SELECT 1.0 * SUM(COALESCE(accepted_qty, 0)) / NULLIF(SUM(ordered_qty), 0) AS value,
       SUM(COALESCE(accepted_qty, 0)) AS accepted_qty, SUM(ordered_qty) AS ordered_qty
FROM {{orders}}.replenishment_orders
WHERE sku_id = '{{sku}}' AND dc_id = '{{dc}}'
  AND required_delivery_date {P1}""",
    },
    "on_time_pct": {
        "label": "Qty On-Time %",
        "branch": "supply",
        "definition": "Qty accepted on time / qty accepted, orders due in P1",
        "sql": f"""
SELECT 1.0 * SUM(CASE WHEN delivery_date <= required_delivery_date
                      THEN accepted_qty ELSE 0 END)
       / NULLIF(SUM(accepted_qty), 0) AS value,
       SUM(CASE WHEN delivery_date > required_delivery_date THEN 1 ELSE 0 END) AS late_orders,
       COUNT(*) AS orders_in_window
FROM {{orders}}.replenishment_orders
WHERE sku_id = '{{sku}}' AND dc_id = '{{dc}}'
  AND required_delivery_date {P1} AND accepted_qty IS NOT NULL""",
    },
    "lead_time_overrun_pct": {
        "label": "Lead Time Overrun %",
        "branch": "supply",
        "definition": "Average of max(0, actual lead time - std lead time) / std "
                      "lead time, for orders due in P1. Orders not yet delivered "
                      "on day D count with their lead time so far (as of D)",
        "sql": f"""
SELECT AVG(1.0 * GREATEST(0, datediff(LEAST(COALESCE(delivery_date, DATE '{{d}}'), DATE '{{d}}'),
                                      dispatch_date) - std_lead_time_days)
           / std_lead_time_days) AS value,
       AVG(1.0 * datediff(LEAST(COALESCE(delivery_date, DATE '{{d}}'), DATE '{{d}}'),
                          dispatch_date)) AS avg_actual_lead_time_days,
       MAX(std_lead_time_days) AS std_lead_time_days,
       SUM(CASE WHEN COALESCE(delivery_date, DATE '{{d}}') > required_delivery_date
                THEN 1 ELSE 0 END) AS late_or_overdue_orders
FROM {{orders}}.replenishment_orders
WHERE sku_id = '{{sku}}' AND dc_id = '{{dc}}'
  AND required_delivery_date {P1}""",
    },
    "order_qty_deviation_pct": {
        "label": "Order Qty Deviation %",
        "branch": "supply",
        "definition": "1 - actual ordered qty / theoretical qty, where theoretical "
                      "= max(0, design inventory on D - inventory on D1 + forecast "
                      "over P1) and design inventory = norm days x fwd avg forecast",
        "sql": f"""
WITH actual AS (
  SELECT COALESCE(SUM(ordered_qty), 0) AS qty
  FROM {{orders}}.replenishment_orders
  WHERE sku_id = '{{sku}}' AND dc_id = '{{dc}}' AND required_delivery_date {P1}),
inv_d1 AS (
  SELECT on_hand_qty FROM {{wms}}.inventory_snapshots
  WHERE sku_id = '{{sku}}' AND dc_id = '{{dc}}'
    AND snapshot_date = date_sub(DATE '{{d}}', {{p1_days}} + 1)),
design_d AS (
  SELECT s.fwd_avg_daily_forecast * n.inventory_norm_days AS qty
  FROM {{wms}}.inventory_snapshots s
  JOIN {{wms}}.inventory_norms n ON s.sku_id = n.sku_id AND s.dc_id = n.dc_id
  WHERE s.sku_id = '{{sku}}' AND s.dc_id = '{{dc}}'
    AND s.snapshot_date = date_sub(DATE '{{d}}', 1)),
fc AS (
  SELECT SUM(forecast_qty) AS qty FROM {{planning}}.demand_daily
  WHERE sku_id = '{{sku}}' AND dc_id = '{{dc}}' AND demand_date {P1})
SELECT 1 - 1.0 * a.qty / NULLIF(GREATEST(0, dd.qty - i.on_hand_qty + f.qty), 0) AS value,
       a.qty AS actual_ordered_qty,
       GREATEST(0, dd.qty - i.on_hand_qty + f.qty) AS theoretical_order_qty
FROM actual a CROSS JOIN inv_d1 i CROSS JOIN design_d dd CROSS JOIN fc f""",
    },
    "under_forecast_error_pct": {
        "label": "Under-Forecast Error %",
        "branch": "demand",
        "definition": "(actual demand - forecast) / actual demand over P1, SKU-DC level",
        "sql": f"""
SELECT 1.0 * (SUM(actual_demand_qty) - SUM(forecast_qty))
       / NULLIF(SUM(actual_demand_qty), 0) AS value,
       SUM(actual_demand_qty) AS actual_demand_qty, SUM(forecast_qty) AS forecast_qty
FROM {{planning}}.demand_daily
WHERE sku_id = '{{sku}}' AND dc_id = '{{dc}}' AND demand_date {P1}""",
    },
    "under_forecast_error_recent_pct": {
        "label": "Under-Forecast Error % (last 4 weeks)",
        "branch": "demand",
        "definition": "Same as Under-Forecast Error %, last 28 days before D "
                      "(detects a recent surge diluted in the 12-week window)",
        "sql": """
SELECT 1.0 * (SUM(actual_demand_qty) - SUM(forecast_qty))
       / NULLIF(SUM(actual_demand_qty), 0) AS value,
       SUM(actual_demand_qty) AS actual_demand_qty, SUM(forecast_qty) AS forecast_qty
FROM {planning}.demand_daily
WHERE sku_id = '{sku}' AND dc_id = '{dc}'
  AND demand_date BETWEEN date_sub(DATE '{d}', 28) AND date_sub(DATE '{d}', 1)""",
    },
    "safety_stock_breach_pct": {
        "label": "Safety Stock Breach Occurrences %",
        "branch": "inventory_norm",
        "definition": "Share of days in P1 where days-on-hand < safety stock days",
        "sql": f"""
SELECT 1.0 * SUM(CASE WHEN s.days_on_hand < n.safety_stock_days THEN 1 ELSE 0 END)
       / NULLIF(COUNT(*), 0) AS value,
       SUM(CASE WHEN s.days_on_hand < n.safety_stock_days THEN 1 ELSE 0 END) AS breach_days,
       COUNT(*) AS days_observed, MAX(n.safety_stock_days) AS safety_stock_days
FROM {{wms}}.inventory_snapshots s
JOIN {{wms}}.inventory_norms n ON s.sku_id = n.sku_id AND s.dc_id = n.dc_id
WHERE s.sku_id = '{{sku}}' AND s.dc_id = '{{dc}}' AND s.snapshot_date {P1}""",
    },
}


# --------------------------------------------------------------------------
# Root-cause tree (minimal slice of the full OOS tree).
#   roots: one entry metric per branch
#   if_flagged / if_clear: which metrics to investigate next
#   cause: the root cause named when this metric is confirmed as flagged
# --------------------------------------------------------------------------
TREE = {
    "fill_on_time_pct": {"if_flagged": ["fill_rate_pct", "on_time_pct"],
                         "if_clear": ["order_qty_deviation_pct"]},
    "fill_rate_pct": {"cause": "Plant short-shipped against DC orders",
                      "owner": "Plant / supply planning"},
    "on_time_pct": {"if_flagged": ["lead_time_overrun_pct"]},
    "lead_time_overrun_pct": {"cause": "Transport delays from plant to DC",
                              "owner": "Transport / logistics"},
    "order_qty_deviation_pct": {"cause": "DC ordered less than needed",
                                "owner": "DC replenishment planning"},
    "under_forecast_error_pct": {"cause": "Demand was under-forecast",
                                 "owner": "Demand planning"},
    "under_forecast_error_recent_pct": {
        "cause": "Recent demand surge not reflected in the forecast",
        "owner": "Demand planning"},
    "safety_stock_breach_pct": {"cause": "Safety stock set too low for demand variability",
                                "owner": "Inventory policy / planning"},
}
ROOTS = {"supply": "fill_on_time_pct", "demand": "under_forecast_error_pct",
         "inventory_norm": "safety_stock_breach_pct"}

# Extra checks the Evaluator can ask for when the first pass is inconclusive.
DRILL_DOWNS = {
    "under_forecast_error_recent_pct":
        "Re-examine demand over the last 4 weeks: a recent surge can hide inside a 12-week average",
    "lead_time_overrun_pct":
        "Check transport lead times directly, even though aggregate fill on-time passed",
    "order_qty_deviation_pct":
        "Check whether the DC ordered enough, even though supply met the orders placed",
}

# --------------------------------------------------------------------------
# Independent verification: row-level queries whose rows are recomputed in
# Python. A finding is confirmed only if this independent recomputation
# agrees with the aggregate metric query.
# --------------------------------------------------------------------------
_ORDER_ROWS = f"""
SELECT order_id, ordered_qty, accepted_qty, dispatch_date, required_delivery_date,
       delivery_date, std_lead_time_days
FROM {{orders}}.replenishment_orders
WHERE sku_id = '{{sku}}' AND dc_id = '{{dc}}' AND required_delivery_date {P1}
ORDER BY required_delivery_date"""

_DEMAND_ROWS = f"""
SELECT demand_date, forecast_qty, actual_demand_qty
FROM {{planning}}.demand_daily
WHERE sku_id = '{{sku}}' AND dc_id = '{{dc}}' AND demand_date {P1}
ORDER BY demand_date"""

_DEMAND_ROWS_RECENT = """
SELECT demand_date, forecast_qty, actual_demand_qty
FROM {planning}.demand_daily
WHERE sku_id = '{sku}' AND dc_id = '{dc}'
  AND demand_date BETWEEN date_sub(DATE '{d}', 28) AND date_sub(DATE '{d}', 1)
ORDER BY demand_date"""

_SS_ROWS = f"""
SELECT s.snapshot_date, s.on_hand_qty, s.days_on_hand, n.safety_stock_days
FROM {{wms}}.inventory_snapshots s
JOIN {{wms}}.inventory_norms n ON s.sku_id = n.sku_id AND s.dc_id = n.dc_id
WHERE s.sku_id = '{{sku}}' AND s.dc_id = '{{dc}}' AND s.snapshot_date {P1}
ORDER BY s.snapshot_date"""


def _f(x):
    return float(x) if x not in (None, "") else None


def _as_of(delivery, d):
    return min(str(delivery)[:10], d) if delivery not in (None, "") else d


def _days(a, b):
    import datetime as _dt
    return (_dt.date.fromisoformat(str(a)[:10]) - _dt.date.fromisoformat(str(b)[:10])).days


def _fill_on_time(rows, d):
    tot = sum(_f(r["ordered_qty"]) for r in rows)
    ok = sum(_f(r["accepted_qty"]) or 0 for r in rows
             if r["delivery_date"] not in (None, "")
             and str(r["delivery_date"])[:10] <= str(r["required_delivery_date"])[:10])
    return ok / tot if tot else None


def _fill_rate(rows, d):
    tot = sum(_f(r["ordered_qty"]) for r in rows)
    return sum(_f(r["accepted_qty"]) or 0 for r in rows) / tot if tot else None


def _on_time(rows, d):
    acc = [r for r in rows if r["accepted_qty"] not in (None, "")]
    tot = sum(_f(r["accepted_qty"]) for r in acc)
    ok = sum(_f(r["accepted_qty"]) for r in acc
             if str(r["delivery_date"])[:10] <= str(r["required_delivery_date"])[:10])
    return ok / tot if tot else None


def _lt_overrun(rows, d):
    vals = [max(0, _days(_as_of(r["delivery_date"], d), r["dispatch_date"])
                - _f(r["std_lead_time_days"])) / _f(r["std_lead_time_days"]) for r in rows]
    return sum(vals) / len(vals) if vals else None


def _ufe(rows, d):
    act = sum(_f(r["actual_demand_qty"]) for r in rows)
    fc = sum(_f(r["forecast_qty"]) for r in rows)
    return (act - fc) / act if act else None


def _ss_breach(rows, d):
    if not rows:
        return None
    return sum(1 for r in rows if _f(r["days_on_hand"]) < _f(r["safety_stock_days"])) / len(rows)


def _order_total(rows, d):
    # Independent check of the numerator (actual ordered qty); the evaluator
    # compares it with the aggregate query's actual_ordered_qty.
    return sum(_f(r["ordered_qty"]) for r in rows)


VERIFY = {
    "fill_on_time_pct": (_ORDER_ROWS, _fill_on_time, "value"),
    "fill_rate_pct": (_ORDER_ROWS, _fill_rate, "value"),
    "on_time_pct": (_ORDER_ROWS, _on_time, "value"),
    "lead_time_overrun_pct": (_ORDER_ROWS, _lt_overrun, "value"),
    "order_qty_deviation_pct": (_ORDER_ROWS, _order_total, "actual_ordered_qty"),
    "under_forecast_error_pct": (_DEMAND_ROWS, _ufe, "value"),
    "under_forecast_error_recent_pct": (_DEMAND_ROWS_RECENT, _ufe, "value"),
    "safety_stock_breach_pct": (_SS_ROWS, _ss_breach, "value"),
}


# --------------------------------------------------------------------------
# Counter-tests (rollback loop). After a cause is confirmed, the Evaluator
# tries to falsify it. An inventory-norm breach that only started recently,
# while another confirmed disruption was draining stock, is a symptom of that
# disruption, not a root cause, so the cause is rolled back.
#   early window = weeks 12-7 before D, late window = weeks 6-1 before D
# --------------------------------------------------------------------------
_HALF = "date_sub(DATE '{d}', 42)"
COUNTER_TESTS = {
    "safety_stock_breach_pct": {
        "label": "Breach onset test (weeks 12-7 vs weeks 6-1)",
        "question": "were safety-stock breaches chronic, or did they only begin "
                    "once another disruption was draining stock?",
        "sql": f"""
SELECT 1.0 * SUM(CASE WHEN s.snapshot_date < {_HALF}
                       AND s.days_on_hand < n.safety_stock_days THEN 1 ELSE 0 END)
       / NULLIF(SUM(CASE WHEN s.snapshot_date < {_HALF} THEN 1 ELSE 0 END), 0) AS early_rate,
       1.0 * SUM(CASE WHEN s.snapshot_date >= {_HALF}
                       AND s.days_on_hand < n.safety_stock_days THEN 1 ELSE 0 END)
       / NULLIF(SUM(CASE WHEN s.snapshot_date >= {_HALF} THEN 1 ELSE 0 END), 0) AS late_rate,
       COUNT(*) AS days_observed
FROM {{wms}}.inventory_snapshots s
JOIN {{wms}}.inventory_norms n ON s.sku_id = n.sku_id AND s.dc_id = n.dc_id
WHERE s.sku_id = '{{sku}}' AND s.dc_id = '{{dc}}' AND s.snapshot_date {P1}""",
    },
}


# Plain-English meaning of each metric, shown in the web interface.
PLAIN = {'fill_on_time_pct': 'Ordered quantity delivered in full and on time',
         'fill_rate_pct': 'Ordered quantity the plant actually shipped',
         'on_time_pct': 'Quantity that arrived by the required date',
         'lead_time_overrun_pct': 'Deliveries slower than the standard lead time',
         'order_qty_deviation_pct': 'How far DC orders fell short of what policy needed',
         'under_forecast_error_pct': 'Demand above forecast, last 12 weeks',
         'under_forecast_error_recent_pct': 'Demand above forecast, last 4 weeks',
         'safety_stock_breach_pct': 'Days stock fell below the safety buffer'}


# --------------------------------------------------------------------------
# Business impact (asked for by the Writer before it drafts the report).
#   lost sales   demand not fulfilled in the 4 weeks from the first stockout
#   stockouts    days with zero stock in that window (does it keep happening?)
#   demand       average daily demand in P1 (sizes the naive safety-stock fix)
# Money comes from the finance system: scm_finance.sku_economics (estimated prices).
# --------------------------------------------------------------------------
IMPACT_WINDOW_DAYS = 28
_AFTER = "BETWEEN DATE '{d}' AND date_sub(DATE '{d}', -27)"
IMPACT_SQL = {
    "lost": f"""
SELECT SUM(actual_demand_qty - fulfilled_qty) AS lost_units,
       SUM(CASE WHEN actual_demand_qty > fulfilled_qty THEN 1 ELSE 0 END) AS short_days
FROM {{planning}}.demand_daily
WHERE sku_id = '{{sku}}' AND dc_id = '{{dc}}' AND demand_date {_AFTER}""",
    "stockout_days": f"""
SELECT snapshot_date FROM {{wms}}.inventory_snapshots
WHERE sku_id = '{{sku}}' AND dc_id = '{{dc}}' AND on_hand_qty = 0 AND snapshot_date {_AFTER}
ORDER BY snapshot_date""",
    "sku": """SELECT product_name FROM {planning}.skus WHERE sku_id = '{sku}'""",
    "economics": """SELECT mrp_inr, net_price_inr, unit_cost_inr
FROM {finance}.sku_economics WHERE sku_id = '{sku}'""",
    "dc": """SELECT dc_name FROM {wms}.dcs WHERE dc_id = '{dc}'""",
    "avg_demand": f"""
SELECT AVG(actual_demand_qty) AS avg_daily_demand
FROM {{planning}}.demand_daily
WHERE sku_id = '{{sku}}' AND dc_id = '{{dc}}' AND demand_date {P1}""",
}

# Early warning: the same row-level queries as the rechecks, recomputed week by
# week over P1. The onset is the first week of the final unbroken run of
# off-target weeks: "the signal was visible from here".
_DATE_FIELD = {id(_ORDER_ROWS): "required_delivery_date", id(_DEMAND_ROWS): "demand_date",
               id(_SS_ROWS): "snapshot_date"}
ONSET = {
    "fill_on_time_pct": (_ORDER_ROWS, _fill_on_time),
    "fill_rate_pct": (_ORDER_ROWS, _fill_rate),
    "on_time_pct": (_ORDER_ROWS, _on_time),
    "lead_time_overrun_pct": (_ORDER_ROWS, _lt_overrun),
    "under_forecast_error_pct": (_DEMAND_ROWS, _ufe),
    "under_forecast_error_recent_pct": (_DEMAND_ROWS, _ufe),
    "safety_stock_breach_pct": (_SS_ROWS, _ss_breach),
}


def onset(rows, sql, fn, d, direction, thr, weeks=12):
    """Return (onset_date, run_weeks, flagged_weeks): onset of the final unbroken
    run of off-target weeks, its length, and how many of the weeks were off."""
    import datetime as _dt
    field = _DATE_FIELD[id(sql)]
    D = _dt.date.fromisoformat(d)
    flags = []
    for w in range(weeks, 0, -1):                      # oldest week first
        start, end = D - _dt.timedelta(days=7 * w), D - _dt.timedelta(days=7 * (w - 1))
        part = [r for r in rows
                if start <= _dt.date.fromisoformat(str(r[field])[:10]) < end]
        v = fn(part, d) if part else None
        off = v is not None and (v < thr if direction == "below" else v > thr)
        flags.append((start, off))
    run = 0
    for _, off in reversed(flags):
        if not off:
            break
        run += 1
    total = sum(1 for _, off in flags if off)
    if not run:
        return None, 0, total
    return flags[len(flags) - run][0].isoformat(), run, total


# What a team would typically do if it trusted a symptom: the wrong fix the
# rollback prevents. Only safety stock has one here.
NAIVE_FIX = {
    "safety_stock_breach_pct":
        "raise safety stock to buffer the real cause",
}

# Concrete next steps, filled from the evidence.
ACTIONS = {
    "lead_time_overrun_pct":
        "Escalate the plant-to-{dc_name} lane with logistics: deliveries ran {value:.0%} over "
        "standard lead time{since}. Fix the delays; extra safety stock would only hide them.",
    "under_forecast_error_recent_pct":
        "Re-baseline the {sku_desc} forecast at {dc_name}: demand has run {value:.0%} above "
        "forecast over the last 4 weeks{since}. Add the surge to the next planning cycle.",
    "under_forecast_error_pct":
        "Correct the forecast bias for {sku_desc} at {dc_name}: demand ran {value:.0%} above "
        "forecast over 12 weeks{since}.",
    "safety_stock_breach_pct":
        "Review safety stock for {sku_desc} at {dc_name}: stock sat below the buffer on "
        "{value:.0%} of days{since}, so the buffer does not cover demand variability.",
    "order_qty_deviation_pct":
        "Check {dc_name}'s order quantities against policy: orders fell {value:.0%} short of "
        "what the inventory norm required.",
    "fill_rate_pct":
        "Raise supply shortfall with the plant: only {value:.0%} of ordered quantity shipped.",
}
