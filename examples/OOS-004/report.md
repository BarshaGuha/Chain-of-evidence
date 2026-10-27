# Root-cause report: Pearlguard Toothpaste 150g (SKU 100562) at Bengaluru DC, stockout on 2026-08-06

**Pearlguard Toothpaste 150g goes out of stock at Bengaluru DC on 6 Aug due to transport delays.**

Root cause is transport delays from plant to DC, with deliveries performing at 35.0% of the standard lead time under logistics ownership. A warning sign appeared 35 days before the stockout, and safety stock inadequacy was ruled out, as the issue only emerged after the true cause took effect (2.4% of days before, 57.1% after).

## Confirmed causes
1. **Transport delays from plant to DC**: Lead Time Overrun % = 35.0% (threshold above 15%). *Next step:* Escalate the plant-to-Bengaluru DC lane with logistics: deliveries ran 35% over standard lead time (visible from 2 Jul). Fix the delays; extra safety stock would only hide them.

## Ruled out (with evidence)
- Under-Forecast Error %: -1.1% vs threshold above 10%: within normal range
- Qty Fill Rate %: 99.0% vs threshold below 95%: within normal range
- Safety Stock Breach Occurrences %: rolled back after counter-test: stock was below safety stock on 2.4% of days in the first 6 of the 12 weeks, but on 57.1% in the last 6: the shortfalls began only after 'Transport delays from plant to DC' started draining stock, so this is a symptom, not a root cause

## How the team challenged itself
- Counter-test on safety_stock_breach_pct: cause **rolled back**: stock was below safety stock on 2.4% of days in the first 6 of the 12 weeks, but on 57.1% in the last 6: the shortfalls began only after 'Transport delays from plant to DC' started draining stock, so this is a symptom, not a root cause

## Evidence chain

| Fact | Value | Threshold | Status | Source |
|---|---|---|---|---|
| Qty Fill On-Time % | 49.2% | below 95% | flagged | zetaris |
| Under-Forecast Error % | -1.1% | above 10% | clear | zetaris |
| Safety Stock Breach Occurrences % | 29.8% | above 20% | flagged | zetaris |
| Qty Fill On-Time % (independent recheck) | 49.2% | - | verification | zetaris |
| Safety Stock Breach Occurrences % (independent recheck) | 29.8% | - | verification | zetaris |
| Qty Fill Rate % | 99.0% | below 95% | clear | zetaris |
| Qty On-Time % | 49.7% | below 95% | flagged | zetaris |
| Qty On-Time % (independent recheck) | 49.7% | - | verification | zetaris |
| Lead Time Overrun % | 35.0% | above 15% | flagged | zetaris |
| Lead Time Overrun % (independent recheck) | 35.0% | - | verification | zetaris |
| Breach onset test (first 6 vs last 6 of the 12 weeks) | 2.4% | - | counter_test | zetaris |
| Business impact | 83 | - | impact | zetaris |

## Model calls (Meterless receipts)

| Agent | Model | Receipt | Time | Tokens |
|---|---|---|---|---|
| Planner | nvidia/nemotron-3.5-lightning-30b-a3b | rcpt_req_27gpbncv | 13.7s | 1234 |
| Writer | nvidia/nemotron-3.5-lightning-30b-a3b | rcpt_req_7w05g147 | 32.3s | 2214 |

*38 agent messages · 0 dig-deeper loop(s) · 0 report revision(s) · 2 model calls via nvidia/nemotron-3.5-lightning-30b-a3b · run OOS-004_20261027_215147*
