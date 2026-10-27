# Root-cause report: Herbana Shampoo 200ml (SKU 100231) at Mumbai DC, stockout on 2026-07-30

**Herbana Shampoo 200ml out of stock at Mumbai DC due to transport/logistics delays from plant.**

Herbana Shampoo 200ml went out of stock at Mumbai DC on 30 July after transport/logistics delays from the plant slowed deliveries 29.2% below the standard lead time. Although safety stock was initially flagged as insufficient for demand variability, the data showed the issue emerged only after the transport problem began, with day-to-day variability shifting from 4.8% to 42.9%, and a warning sign appeared 21 days before the stockout.

## Confirmed causes
1. **Transport delays from plant to DC**: Lead Time Overrun % = 29.2% (threshold above 15%). *Next step:* Escalate the plant-to-Mumbai DC lane with logistics: deliveries ran 29% over standard lead time (visible from 9 Jul). Fix the delays; extra safety stock would only hide them.

## Ruled out (with evidence)
- Under-Forecast Error %: 0.1% vs threshold above 10%: within normal range
- Qty Fill Rate %: 99.3% vs threshold below 95%: within normal range
- Safety Stock Breach Occurrences %: rolled back after counter-test: stock was below safety stock on 4.8% of days in the first 6 of the 12 weeks, but on 42.9% in the last 6: the shortfalls began only after 'Transport delays from plant to DC' started draining stock, so this is a symptom, not a root cause

## How the team challenged itself
- Counter-test on safety_stock_breach_pct: cause **rolled back**: stock was below safety stock on 4.8% of days in the first 6 of the 12 weeks, but on 42.9% in the last 6: the shortfalls began only after 'Transport delays from plant to DC' started draining stock, so this is a symptom, not a root cause

## Evidence chain

| Fact | Value | Threshold | Status | Source |
|---|---|---|---|---|
| Qty Fill On-Time % | 74.4% | below 95% | flagged | zetaris |
| Under-Forecast Error % | 0.1% | above 10% | clear | zetaris |
| Safety Stock Breach Occurrences % | 23.8% | above 20% | flagged | zetaris |
| Qty Fill On-Time % (independent recheck) | 74.4% | - | verification | zetaris |
| Safety Stock Breach Occurrences % (independent recheck) | 23.8% | - | verification | zetaris |
| Qty Fill Rate % | 99.3% | below 95% | clear | zetaris |
| Qty On-Time % | 74.9% | below 95% | flagged | zetaris |
| Qty On-Time % (independent recheck) | 74.9% | - | verification | zetaris |
| Lead Time Overrun % | 29.2% | above 15% | flagged | zetaris |
| Lead Time Overrun % (independent recheck) | 29.2% | - | verification | zetaris |
| Breach onset test (first 6 vs last 6 of the 12 weeks) | 4.8% | - | counter_test | zetaris |
| Business impact | 877 | - | impact | zetaris |

## Model calls (Meterless receipts)

| Agent | Model | Receipt | Time | Tokens |
|---|---|---|---|---|
| Planner | nvidia/nemotron-3.5-lightning-30b-a3b | rcpt_req_37oa28hp | 12.1s | 1129 |
| Writer | nvidia/nemotron-3.5-lightning-30b-a3b | rcpt_req_bmkyrh0r | 40.2s | 3232 |

*38 agent messages · 0 dig-deeper loop(s) · 0 report revision(s) · 2 model calls via nvidia/nemotron-3.5-lightning-30b-a3b · run OOS-001_20261027_214845*
