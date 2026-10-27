# Root-cause report: Zippy Masala Noodles 4-pack (SKU 300518) at Mumbai DC, stockout on 2026-08-27

**Zippy Masala Noodles 4-pack goes out of stock at Mumbai DC due to demand surge.**

The stockout resulted from a demand surge that exceeded forecast by 16.5% over the last four weeks, owned by the demand planning team. A warning sign appeared 14 days before the August 27th stockout at the Mumbai DC.

## Confirmed causes
1. **Recent demand surge not reflected in the forecast**: Under-Forecast Error % (last 4 weeks) = 16.5% (threshold above 10%). *Next step:* Re-baseline the Zippy Masala Noodles 4-pack forecast at Mumbai DC: demand has run 17% above forecast over the last 4 weeks (visible from 13 Aug). Add the surge to the next planning cycle.

## Ruled out (with evidence)
- Qty Fill On-Time %: 99.3% vs threshold below 95%: within normal range
- Under-Forecast Error %: 6.7% vs threshold above 10%: within normal range
- Safety Stock Breach Occurrences %: 11.9% vs threshold above 20%: within normal range
- Order Qty Deviation %: 7.0% vs threshold above 15%: within normal range
- Lead Time Overrun %: 0.0% vs threshold above 15%: within normal range

## How the team challenged itself
- Loop 1: Evaluator rejected 'no cause found' and asked for under_forecast_error_recent_pct, lead_time_overrun_pct: These two checks investigate recent demand volatility and actual transport lead times, which the primary metrics and ruled-out hypotheses did not capture.

## Evidence chain

| Fact | Value | Threshold | Status | Source |
|---|---|---|---|---|
| Qty Fill On-Time % | 99.3% | below 95% | clear | zetaris |
| Under-Forecast Error % | 6.7% | above 10% | clear | zetaris |
| Safety Stock Breach Occurrences % | 11.9% | above 20% | clear | zetaris |
| Order Qty Deviation % | 7.0% | above 15% | clear | zetaris |
| Under-Forecast Error % (last 4 weeks) | 16.5% | above 10% | flagged | zetaris |
| Lead Time Overrun % | 0.0% | above 15% | clear | zetaris |
| Under-Forecast Error % (last 4 weeks) (independent recheck) | 16.5% | - | verification | zetaris |
| Business impact | 4705 | - | impact | zetaris |

## Model calls (Meterless receipts)

| Agent | Model | Receipt | Time | Tokens |
|---|---|---|---|---|
| Planner | nvidia/nemotron-3.5-lightning-30b-a3b | rcpt_req_1c6acci0 | 36.7s | 1085 |
| Evaluator | nvidia/nemotron-3.5-lightning-30b-a3b | rcpt_req_md3pnad6 | 17.7s | 1252 |
| Writer | nvidia/nemotron-3.5-lightning-30b-a3b | rcpt_req_328a5g1z | 25.2s | 1802 |

*30 agent messages · 1 dig-deeper loop(s) · 0 report revision(s) · 3 model calls via nvidia/nemotron-3.5-lightning-30b-a3b · run OOS-005_20261027_215242*
