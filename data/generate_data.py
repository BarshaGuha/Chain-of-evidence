"""
Chain of Evidence - synthetic supply chain dataset for stockout root-cause analysis.

Simulates daily inventory for 12 SKUs x 3 distribution centres (DCs), Apr-Sep 2026,
with weekly replenishment from one plant. Six stockout incidents are planted,
each with a known true root cause (see ANSWER_KEY.md):

  OOS-001  SKU-A @ DC1  transport delays (lead-time overrun)       the demo cases
  OOS-002  SKU-B @ DC2  recent demand surge the forecast missed
  OOS-003  SKU-C @ DC1  safety stock too low + DC under-ordering
  OOS-004  SKU-F @ DC3  transport delays                            more of the network
  OOS-005  SKU-H @ DC1  recent demand surge
  OOS-006  SKU-K @ DC2  plant short-shipping

The other 30 SKU-DC pairs are healthy controls (no stockout). The first six
pairs are generated first, in the original order, so the three demo cases are
identical to earlier versions of this dataset.

Three "systems", one Postgres database each (Zetaris joins across them):
  scm_orders    replenishment_orders            (order mgmt + transport)
  scm_planning  demand_daily                    (forecast vs actual demand)
  scm_wms       inventory_snapshots, inventory_norms, stockout_events

Python standard library only; deterministic (fixed seed).
Outputs: seed_orders.sql, seed_planning.sql, seed_wms.sql, seed_finance.sql and csv/*.csv
"""

import csv
import datetime as dt
import os
import random

random.seed(7)
HERE = os.path.dirname(os.path.abspath(__file__))
CSV_DIR = os.path.join(HERE, "csv")
os.makedirs(CSV_DIR, exist_ok=True)
for old in os.listdir(CSV_DIR):
    os.remove(os.path.join(CSV_DIR, old))

START, END = dt.date(2026, 4, 1), dt.date(2026, 9, 30)
PLANT = "PL1"

SKUS = {
    "SKU-A": "Herbal shampoo 200ml",
    "SKU-B": "Liquid detergent 1L",
    "SKU-C": "Cream biscuits 100g",
    "SKU-D": "Toilet soap 4x100g",
    "SKU-E": "Coconut hair oil 300ml",
    "SKU-F": "Toothpaste 150g",
    "SKU-G": "Dishwash liquid 500ml",
    "SKU-H": "Instant noodles 4-pack",
    "SKU-I": "Tea 500g",
    "SKU-J": "Wheat flour (atta) 5kg",
    "SKU-K": "Floor cleaner 1L",
    "SKU-L": "Glucose biscuits 250g",
}
CATEGORY = {"SKU-A": "Personal care", "SKU-D": "Personal care", "SKU-E": "Personal care",
            "SKU-F": "Personal care", "SKU-B": "Home care", "SKU-G": "Home care",
            "SKU-K": "Home care", "SKU-C": "Foods", "SKU-H": "Foods", "SKU-I": "Foods",
            "SKU-J": "Foods", "SKU-L": "Foods"}
DCS = {"DC1": "Mumbai DC", "DC2": "Delhi DC", "DC3": "Bengaluru DC"}

# Per SKU-DC settings. Defaults describe a healthy, well-run pair.
DEFAULT = dict(base=400, noise=0.12, ss_days=5, norm_days=14, std_lt=4,
               order_factor=1.0, surge_from=None, surge=1.0,
               delay_from=None, delay_days=(0, 0), short_ship=0.0, short_from=None)
PAIRS = {
    ("SKU-A", "DC1"): dict(base=520, delay_from=dt.date(2026, 7, 6),
                           delay_days=(4, 7)),                     # Incident 1
    ("SKU-A", "DC2"): dict(base=380),
    ("SKU-B", "DC1"): dict(base=300),
    ("SKU-B", "DC2"): dict(base=450, surge_from=dt.date(2026, 8, 10),
                           surge=1.65),                            # Incident 2
    ("SKU-C", "DC1"): dict(base=600, noise=0.45, ss_days=2,
                           order_factor=0.72),                     # Incident 3
    ("SKU-C", "DC2"): dict(base=350),
}
# The rest of the network: base demand per SKU at Mumbai, scaled by DC size.
BASE = {"SKU-A": 520, "SKU-B": 450, "SKU-C": 600, "SKU-D": 480, "SKU-E": 260,
        "SKU-F": 540, "SKU-G": 330, "SKU-H": 820, "SKU-I": 240, "SKU-J": 300,
        "SKU-K": 210, "SKU-L": 900}
DC_SCALE = {"DC1": 1.0, "DC2": 0.85, "DC3": 0.7}
INCIDENTS = {
    ("SKU-F", "DC3"): dict(delay_from=dt.date(2026, 6, 29), delay_days=(3, 5)),   # OOS-004
    ("SKU-H", "DC1"): dict(surge_from=dt.date(2026, 8, 17), surge=1.6),           # OOS-005
    ("SKU-K", "DC2"): dict(short_ship=0.45, short_from=dt.date(2026, 7, 13)),     # OOS-006
}
for _sku in SKUS:
    for _dc in DCS:
        if (_sku, _dc) not in PAIRS:
            PAIRS[(_sku, _dc)] = dict(base=round(BASE[_sku] * DC_SCALE[_dc]),
                                      std_lt=5 if _dc == "DC3" else 4,
                                      **INCIDENTS.get((_sku, _dc), {}))


def cfg(pair):
    c = dict(DEFAULT)
    c.update(PAIRS[pair])
    return c


def days(a, b):
    d = a
    while d <= b:
        yield d
        d += dt.timedelta(days=1)


orders, demand_rows, snapshots, norms, events = [], [], [], [], []
order_seq = 10000

for (sku, dc), _ in PAIRS.items():
    c = cfg((sku, dc))
    norms.append({"sku_id": sku, "dc_id": dc,
                  "safety_stock_days": c["ss_days"],
                  "inventory_norm_days": c["norm_days"],
                  "std_lead_time_days": c["std_lt"]})

    # Forecast = base level with mild weekly pattern (planning never sees surge)
    fc = {d: round(c["base"] * (1.08 if d.weekday() in (4, 5) else 0.97))
          for d in days(START, END + dt.timedelta(days=30))}

    def actual_demand(d):
        level = c["base"] * (1.08 if d.weekday() in (4, 5) else 0.97)
        if c["surge_from"] and d >= c["surge_from"]:
            level *= c["surge"]
        return max(0, round(level * random.uniform(1 - c["noise"], 1 + c["noise"])))

    on_hand = round(c["base"] * (c["ss_days"] + 7))
    pipeline = []          # (arrival_date, qty, order_index)
    oos_logged = False
    for d in days(START, END):
        # 1) receipts
        arriving = [p for p in pipeline if p[0] == d]
        for _, q, idx in arriving:
            on_hand += q
        pipeline = [p for p in pipeline if p[0] != d]

        # 2) weekly replenishment order on Mondays
        if d.weekday() == 0:
            lt = c["std_lt"]
            fwd = sum(fc[d + dt.timedelta(days=i)] for i in range(1, 8)) / 7
            target = fwd * (c["ss_days"] + 7 + lt + 1)
            on_order = sum(q for _, q, _ in pipeline)
            qty = max(0, round((target - on_hand - on_order) * c["order_factor"]))
            if qty > 0:
                order_seq += 1
                dispatch = d + dt.timedelta(days=1)
                required = dispatch + dt.timedelta(days=lt)
                delay = 0
                if c["delay_from"] and d >= c["delay_from"]:
                    delay = random.randint(*c["delay_days"])
                elif random.random() < 0.08:
                    delay = 1            # occasional normal one-day slip
                delivered = required + dt.timedelta(days=delay)
                short = c["short_ship"] if (c["short_from"] is None
                                            or d >= c["short_from"]) else 0.0
                accepted = round(qty * (1 - short) * random.uniform(0.985, 1.0))
                orders.append({
                    "order_id": f"RO-{order_seq}", "sku_id": sku, "dc_id": dc,
                    "plant_id": PLANT, "order_date": d.isoformat(),
                    "ordered_qty": qty,
                    "required_delivery_date": required.isoformat(),
                    "std_lead_time_days": lt,
                    "dispatch_date": dispatch.isoformat(),
                    "delivery_date": (delivered.isoformat()
                                      if delivered <= END else None),
                    "accepted_qty": accepted if delivered <= END else None,
                    "status": "DELIVERED" if delivered <= END else "IN_TRANSIT",
                })
                pipeline.append((delivered, accepted, len(orders) - 1))

        # 3) demand
        dem = actual_demand(d)
        served = min(on_hand, dem)
        on_hand -= served
        demand_rows.append({"demand_date": d.isoformat(), "sku_id": sku,
                            "dc_id": dc, "forecast_qty": fc[d],
                            "actual_demand_qty": dem,
                            "fulfilled_qty": served})

        # 4) end-of-day snapshot
        avg_fc = sum(fc[d + dt.timedelta(days=i)] for i in range(1, 8)) / 7
        snapshots.append({"snapshot_date": d.isoformat(), "sku_id": sku,
                          "dc_id": dc, "on_hand_qty": on_hand,
                          "fwd_avg_daily_forecast": round(avg_fc, 1),
                          "days_on_hand": round(on_hand / avg_fc, 2)})
        if on_hand == 0 and not oos_logged and d > dt.date(2026, 7, 15):
            events.append({"event_id": f"OOS-{len(events) + 1:03d}",
                           "sku_id": sku, "dc_id": dc,
                           "oos_date": d.isoformat(),
                           "lost_demand_qty": dem - served})
            oos_logged = True

# ------------------------------------------------------------------ outputs
def write_csv(name, rows):
    with open(os.path.join(CSV_DIR, name + ".csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def sql_val(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def inserts(table, rows):
    cols = ", ".join(rows[0].keys())
    out = []
    for i in range(0, len(rows), 250):
        vals = ",\n".join("(" + ", ".join(sql_val(v) for v in r.values()) + ")"
                          for r in rows[i:i + 250])
        out.append(f"INSERT INTO {table} ({cols}) VALUES\n{vals};")
    return "\n".join(out)


# Product master. The simulation uses short internal keys (SKU-A ...); the
# systems store real-looking material numbers and product names. All brand
# names are fictional.
PRODUCTS = {  # key: (sku code, product name, brand, sub-category, pack size)
    "SKU-A": ("100231", "Herbana Shampoo 200ml", "Herbana", "Hair care", "200 ml"),
    "SKU-B": ("200118", "Brightwash Liquid Detergent 1L", "Brightwash", "Laundry", "1 L"),
    "SKU-C": ("300452", "Crunchies Cream Biscuits 100g", "Crunchies", "Biscuits", "100 g"),
    "SKU-D": ("100377", "Velora Bathing Soap 4x100g", "Velora", "Skin care", "4 x 100 g"),
    "SKU-E": ("100415", "Kesari Coconut Hair Oil 300ml", "Kesari", "Hair care", "300 ml"),
    "SKU-F": ("100562", "Pearlguard Toothpaste 150g", "Pearlguard", "Oral care", "150 g"),
    "SKU-G": ("200247", "Shinora Dishwash Liquid 500ml", "Shinora", "Dishwash", "500 ml"),
    "SKU-H": ("300518", "Zippy Masala Noodles 4-pack", "Zippy", "Noodles", "4 x 70 g"),
    "SKU-I": ("300633", "Assamique Gold Tea 500g", "Assamique", "Beverages", "500 g"),
    "SKU-J": ("300741", "Grainfield Chakki Atta 5kg", "Grainfield", "Staples", "5 kg"),
    "SKU-K": ("200389", "Sparkfloor Floor Cleaner 1L", "Sparkfloor", "Surface care", "1 L"),
    "SKU-L": ("300866", "Sunglow Glucose Biscuits 250g", "Sunglow", "Biscuits", "250 g"),
}
CODE = {k: v[0] for k, v in PRODUCTS.items()}
for _rows in (orders, demand_rows, snapshots, norms, events):
    for _r in _rows:
        _r["sku_id"] = CODE[_r["sku_id"]]

sku_rows = [{"sku_id": code, "product_name": name, "brand": brand,
             "category": CATEGORY[k], "sub_category": sub, "pack_size": pack}
            for k, (code, name, brand, sub, pack) in PRODUCTS.items()]

# Finance / ERP: estimated prices per unit (INR). MRP from Indian e-commerce
# listings (Oct 2026); net price = what the company earns after GST and trade
# margins (~63-65% of MRP); unit cost = estimate, used to value inventory.
# Approximate MRPs for typical Indian brands of each product; edit to taste.
ECONOMICS = {"SKU-A": (150, 95, 55), "SKU-B": (235, 150, 90), "SKU-C": (20, 13, 9),
             "SKU-D": (180, 115, 68), "SKU-E": (170, 108, 62), "SKU-F": (110, 70, 40),
             "SKU-G": (115, 73, 43), "SKU-H": (60, 39, 27), "SKU-I": (290, 185, 120),
             "SKU-J": (285, 195, 160), "SKU-K": (225, 145, 85), "SKU-L": (30, 20, 15)}
econ_rows = [{"sku_id": CODE[k], "mrp_inr": m, "net_price_inr": n, "unit_cost_inr": c}
             for k, (m, n, c) in ECONOMICS.items()]
dc_rows = [{"dc_id": k, "dc_name": v} for k, v in DCS.items()]

DBS = {
    "seed_orders.sql": ("scm_orders", """
DROP TABLE IF EXISTS replenishment_orders CASCADE;
CREATE TABLE replenishment_orders (order_id TEXT PRIMARY KEY, sku_id TEXT,
  dc_id TEXT, plant_id TEXT, order_date DATE, ordered_qty INTEGER,
  required_delivery_date DATE, std_lead_time_days INTEGER, dispatch_date DATE,
  delivery_date DATE, accepted_qty INTEGER, status TEXT);
""", [("replenishment_orders", orders)]),
    "seed_planning.sql": ("scm_planning", """
DROP TABLE IF EXISTS demand_daily, skus CASCADE;
CREATE TABLE skus (sku_id TEXT PRIMARY KEY, product_name TEXT, brand TEXT,
  category TEXT, sub_category TEXT, pack_size TEXT);
CREATE TABLE demand_daily (demand_date DATE, sku_id TEXT, dc_id TEXT,
  forecast_qty INTEGER, actual_demand_qty INTEGER, fulfilled_qty INTEGER,
  PRIMARY KEY (demand_date, sku_id, dc_id));
""", [("skus", sku_rows), ("demand_daily", demand_rows)]),
    "seed_finance.sql": ("scm_finance", """
DROP TABLE IF EXISTS sku_economics CASCADE;
CREATE TABLE sku_economics (sku_id TEXT PRIMARY KEY, mrp_inr NUMERIC,
  net_price_inr NUMERIC, unit_cost_inr NUMERIC);
""", [("sku_economics", econ_rows)]),
    "seed_wms.sql": ("scm_wms", """
DROP TABLE IF EXISTS inventory_snapshots, inventory_norms, stockout_events, dcs CASCADE;
CREATE TABLE dcs (dc_id TEXT PRIMARY KEY, dc_name TEXT);
CREATE TABLE inventory_norms (sku_id TEXT, dc_id TEXT, safety_stock_days NUMERIC,
  inventory_norm_days NUMERIC, std_lead_time_days INTEGER,
  PRIMARY KEY (sku_id, dc_id));
CREATE TABLE inventory_snapshots (snapshot_date DATE, sku_id TEXT, dc_id TEXT,
  on_hand_qty INTEGER, fwd_avg_daily_forecast NUMERIC, days_on_hand NUMERIC,
  PRIMARY KEY (snapshot_date, sku_id, dc_id));
CREATE TABLE stockout_events (event_id TEXT PRIMARY KEY, sku_id TEXT,
  dc_id TEXT, oos_date DATE, lost_demand_qty INTEGER);
""", [("dcs", dc_rows), ("inventory_norms", norms),
      ("inventory_snapshots", snapshots), ("stockout_events", events)]),
}

for fname, (db, ddl, tables) in DBS.items():
    with open(os.path.join(HERE, fname), "w") as f:
        f.write(f"-- database: {db}\n{ddl}")
        for t, rows in tables:
            f.write("\n" + inserts(t, rows) + "\n")
            write_csv(t, rows)

for old in ("seed_erp.sql", "seed_contracts.sql"):
    p = os.path.join(HERE, old)
    if os.path.exists(p):
        os.remove(p)

print(f"orders={len(orders)} demand={len(demand_rows)} "
      f"snapshots={len(snapshots)} stockouts={len(events)}")
for e in events:
    print("  ", e)
