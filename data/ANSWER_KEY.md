# Answer key: planted stockout incidents

Synthetic data for Apr–Sep 2026: 12 SKUs (personal care, home care, foods) × 3 DCs (Mumbai, Delhi,
Bengaluru) = 36 SKU–DC pairs, weekly replenishment from plant PL1. Six stockouts are planted;
the other 30 pairs are healthy controls. OOS-001 to OOS-003 are the demo cases.
Look-back period P1 = 84 days (12 weeks) before the stockout day D.

## Products (`scm_planning.skus`, all brand names fictional)

| SKU | Product | Category |
|---|---|---|
| 100231 | Herbana Shampoo 200ml | Personal care / Hair care |
| 100377 | Velora Bathing Soap 4x100g | Personal care / Skin care |
| 100415 | Kesari Coconut Hair Oil 300ml | Personal care / Hair care |
| 100562 | Pearlguard Toothpaste 150g | Personal care / Oral care |
| 200118 | Brightwash Liquid Detergent 1L | Home care / Laundry |
| 200247 | Shinora Dishwash Liquid 500ml | Home care / Dishwash |
| 200389 | Sparkfloor Floor Cleaner 1L | Home care / Surface care |
| 300452 | Crunchies Cream Biscuits 100g | Foods / Biscuits |
| 300518 | Zippy Masala Noodles 4-pack | Foods / Noodles |
| 300633 | Assamique Gold Tea 500g | Foods / Beverages |
| 300741 | Grainfield Chakki Atta 5kg | Foods / Staples |
| 300866 | Sunglow Glucose Biscuits 250g | Foods / Biscuits |

DCs (`scm_wms.dcs`): DC1 Mumbai, DC2 Delhi, DC3 Bengaluru.

## Incidents (`scm_wms.stockout_events`)

| Event | SKU @ DC | Stockout day | True root cause(s) | Signals |
|---|---|---|---|---|
| OOS-001 | Herbana Shampoo 200ml (100231) @ Mumbai DC | 2026-07-30 | **Transport delays from plant** (lead-time overrun from early July) | Fill on-time 74%, on-time 75%, lead-time overrun 29%; fill rate 99% (not short-shipped); forecast error ~0% |
| OOS-002 | Brightwash Liquid Detergent 1L (200118) @ Delhi DC | 2026-08-20 | **Demand under-forecast:** sustained demand surge of about 65% from 10 Aug; forecast not updated | Supply perfect (99–100%). 12-week under-forecast only 6.4% (below threshold), **last 4 weeks 17.7%** → found only by looping to a shorter window |
| OOS-003 | Crunchies Cream Biscuits 100g (300452) @ Mumbai DC | 2026-07-31 | **Safety stock too low** (2 days, with highly volatile demand) **and DC under-ordering** (~28% below policy) | Safety-stock breaches 31% of days; order qty deviation 19.6%; supply on time; forecast unbiased |
| OOS-004 | Pearlguard Toothpaste 150g (100562) @ Bengaluru DC | 2026-08-06 | **Transport delays from plant** (3–5 day delays from 29 Jun) | Fill on-time 49%, on-time 50%, lead-time overrun 35%; fill rate 99%. Safety-stock breaches 29.8% confirmed then **rolled back** (2.4% in weeks 12–7 vs 57.1% in weeks 6–1) |
| OOS-005 | Zippy Masala Noodles 4-pack (300518) @ Mumbai DC | 2026-08-27 | **Recent demand surge** (+60% from 17 Aug) | 12-week under-forecast 6.7% (below threshold); last 4 weeks 16.5% → found by the dig-deeper loop |
| OOS-006 | Sparkfloor Floor Cleaner 1L (200389) @ Delhi DC | 2026-08-01 | **Plant short-shipped against DC orders** (~45% short from 13 Jul) | Fill on-time 82%, fill rate 90.5%; lead-time overrun 2% (not transport). Safety-stock breaches 20.2% confirmed then **rolled back** (9.5% vs 31.0%) |

## Traps (the agent should handle these correctly)

- **OOS-001, safety-stock breaches 23.8% (rollback):** above the 20% threshold, so it is first confirmed as a cause. The Evaluator's counter-test shows breaches were only 4.8% in weeks 12-7 but 42.9% in weeks 6-1: they began once the late deliveries started draining stock. It is a **symptom**, so the team **rolls it back**. It must not appear in the final report as a root cause.
- **OOS-003, safety-stock breaches 31% (counter-test passed):** breaches were already 35.7% in weeks 12-7 (then 26.2%): a chronic policy problem that predates the under-ordering, so it stands.
- **OOS-002, 12-week forecast error 6.4%:** below threshold. A naive tree walk stops at "no cause found". The agent must loop and re-examine a recent window.

## Controls (no stockout, all metrics healthy)

The other 30 SKU–DC pairs (for example Herbana Shampoo 200ml (100231) @ Delhi DC, Brightwash Liquid Detergent 1L (200118) @ Mumbai DC, Crunchies Cream Biscuits 100g (300452) @ Delhi DC): fill on-time ~99%, lead-time overrun ~0%, forecast error ~0–1%, safety-stock breaches 6–12%, order deviation ~7%. None stocks out after 15 Jul.

## Thresholds used (configurable)

| Metric | Flag if |
|---|---|
| Qty Fill On-Time % | < 95% |
| Qty Fill Rate % | < 95% |
| Qty On-Time % | < 95% |
| Lead Time Overrun % | > 15% |
| Order Qty Deviation % | > 15% |
| Under-Forecast Error % (12 weeks, and 4 weeks on drill-down) | > 10% |
| Safety Stock Breach Occurrences % | > 20% |

## Data layout (four systems)

| Database | Tables |
|---|---|
| `scm_orders` | `replenishment_orders` |
| `scm_planning` | `demand_daily`, `skus` |
| `scm_wms` | `inventory_snapshots`, `inventory_norms`, `stockout_events`, `dcs` |

## Business impact (expected)

Prices are estimates in the finance system (`scm_finance.sku_economics`) (net price = MRP less GST and trade margins).

| Case | Lost units (28 days from D) | Lost value | Stockout days | Early warning | Wrong fix avoided |
|---|---|---|---|---|---|
| OOS-001 | 877 | ₹83,315 | 4 (30 Jul, 6, 13, 20 Aug) | lead-time overrun from 9 Jul (21 days) | raise safety stock ~2,400 units = ₹1,32,000 at cost, ~₹26,400/yr to carry |
| OOS-002 | 3,153 | ₹4,72,950 | 6 | recent under-forecast from 6 Aug (14 days) | – |
| OOS-003 | 1,031 | ₹13,403 | 3 | safety-stock breaches off target in 8 of 12 weeks (chronic) | – |
| OOS-004 | 83 | ₹5,810 | 1 | lead-time overrun from 2 Jul (35 days) | ~1,300 units = ₹52,000 at cost |
| OOS-005 | 4,705 | ₹1,83,495 | 5 | recent under-forecast from 13 Aug (14 days) | – |
| OOS-006 | 338 | ₹49,010 | 4 | fill rate from 18 Jul (14 days) | ~700 units = ₹59,500 at cost |
