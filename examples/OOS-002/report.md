# Root-cause report: Brightwash Liquid Detergent 1L (SKU 200118) at Delhi DC, stockout on 2026-08-20

**Brightwash Liquid Detergent 1L goes out of stock at Delhi DC on 20 August due to unreflected demand surge.**

Root cause stems from demand planning, where actual demand exceeded forecast by 17.7% over the last four weeks. A visible warning sign appeared 14 days before the stockout, highlighting the forecast gap.

## Confirmed causes
1. **Recent demand surge not reflected in the forecast**: Under-Forecast Error % (last 4 weeks) = 17.7% (threshold above 10%). *Next step:* Re-baseline the Brightwash Liquid Detergent 1L forecast at Delhi DC: demand has run 18% above forecast over the last 4 weeks (visible from 6 Aug). Add the surge to the next planning cycle.

## Ruled out (with evidence)
- Qty Fill On-Time %: 99.4% vs threshold below 95%: within normal range
- Under-Forecast Error %: 6.4% vs threshold above 10%: within normal range
- Safety Stock Breach Occurrences %: 9.5% vs threshold above 20%: within normal range
- Order Qty Deviation %: 7.4% vs threshold above 15%: within normal range
- Lead Time Overrun %: 0.0% vs threshold above 15%: within normal range

## How the team challenged itself
- Loop 1: Evaluator rejected 'no cause found' and asked for under_forecast_error_recent_pct, lead_time_overrun_pct: Recent demand surges and transport lead time deviations can persist even when aggregate metrics appear clear.

## Evidence chain

| Fact | Value | Threshold | Status | Source |
|---|---|---|---|---|
| Qty Fill On-Time % | 99.4% | below 95% | clear | zetaris |
| Under-Forecast Error % | 6.4% | above 10% | clear | zetaris |
| Safety Stock Breach Occurrences % | 9.5% | above 20% | clear | zetaris |
| Order Qty Deviation % | 7.4% | above 15% | clear | zetaris |
| Under-Forecast Error % (last 4 weeks) | 17.7% | above 10% | flagged | zetaris |
| Lead Time Overrun % | 0.0% | above 15% | clear | zetaris |
| Under-Forecast Error % (last 4 weeks) (independent recheck) | 17.7% | - | verification | zetaris |
| Business impact | 3153 | - | impact | zetaris |

## Model calls (Meterless receipts)

| Agent | Model | Receipt | Time | Tokens |
|---|---|---|---|---|
| Planner | nvidia/nemotron-3.5-lightning-30b-a3b | rcpt_req_vlc1bn4i | 15.0s | 1364 |
| Evaluator | nvidia/nemotron-3.5-lightning-30b-a3b | rcpt_req_k20d0zka | 14.4s | 1243 |
| Writer | nvidia/nemotron-3.5-lightning-30b-a3b | rcpt_req_j40yk8bc | 21.3s | 1523 |

*30 agent messages · 1 dig-deeper loop(s) · 0 report revision(s) · 3 model calls via nvidia/nemotron-3.5-lightning-30b-a3b · run OOS-002_20261027_214954*
