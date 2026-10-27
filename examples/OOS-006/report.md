# Root-cause report: Sparkfloor Floor Cleaner 1L (SKU 200389) at Delhi DC, stockout on 2026-08-01

**Sparkfloor Floor Cleaner 1L out of stock at Delhi DC on 1 Aug. after plant shipped only 90.5% of ordered quantity.**

The plant and supply planning team was owner of the shortfall, which began with a visible warning sign 14 days before the stockout. Safety stock levels were subsequently ruled out as the primary cause.

## Confirmed causes
1. **Plant short-shipped against DC orders**: Qty Fill Rate % = 90.5% (threshold below 95%). *Next step:* Raise supply shortfall with the plant: only 90% of ordered quantity shipped.

## Ruled out (with evidence)
- Under-Forecast Error %: 0.7% vs threshold above 10%: within normal range
- Lead Time Overrun %: 2.1% vs threshold above 15%: within normal range
- Safety Stock Breach Occurrences %: rolled back after counter-test: stock was below safety stock on 9.5% of days in the first 6 of the 12 weeks, but on 31.0% in the last 6: the shortfalls began only after 'Plant short-shipped against DC orders' started draining stock, so this is a symptom, not a root cause

## How the team challenged itself
- Counter-test on safety_stock_breach_pct: cause **rolled back**: stock was below safety stock on 9.5% of days in the first 6 of the 12 weeks, but on 31.0% in the last 6: the shortfalls began only after 'Plant short-shipped against DC orders' started draining stock, so this is a symptom, not a root cause

## Evidence chain

| Fact | Value | Threshold | Status | Source |
|---|---|---|---|---|
| Qty Fill On-Time % | 82.4% | below 95% | flagged | zetaris |
| Under-Forecast Error % | 0.7% | above 10% | clear | zetaris |
| Safety Stock Breach Occurrences % | 20.2% | above 20% | flagged | zetaris |
| Qty Fill On-Time % (independent recheck) | 82.4% | - | verification | zetaris |
| Safety Stock Breach Occurrences % (independent recheck) | 20.2% | - | verification | zetaris |
| Qty Fill Rate % | 90.5% | below 95% | flagged | zetaris |
| Qty On-Time % | 91.1% | below 95% | flagged | zetaris |
| Qty Fill Rate % (independent recheck) | 90.5% | - | verification | zetaris |
| Qty On-Time % (independent recheck) | 91.1% | - | verification | zetaris |
| Lead Time Overrun % | 2.1% | above 15% | clear | zetaris |
| Breach onset test (first 6 vs last 6 of the 12 weeks) | 9.5% | - | counter_test | zetaris |
| Business impact | 338 | - | impact | zetaris |

## Model calls (Meterless receipts)

| Agent | Model | Receipt | Time | Tokens |
|---|---|---|---|---|
| Planner | nvidia/nemotron-3.5-lightning-30b-a3b | rcpt_req_xfzut0ft | 16.8s | 1085 |
| Writer | nvidia/nemotron-3.5-lightning-30b-a3b | rcpt_req_15paaghv | 26.7s | 2135 |

*38 agent messages · 0 dig-deeper loop(s) · 0 report revision(s) · 2 model calls via nvidia/nemotron-3.5-lightning-30b-a3b · run OOS-006_20261027_215408*
