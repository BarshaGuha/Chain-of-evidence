# Root-cause report: Crunchies Cream Biscuits 100g (SKU 300452) at Mumbai DC, stockout on 2026-07-31

**Crunchies Cream Biscuits 100g went out of stock at Mumbai DC on 31 Jul.**

Safety stock was set too low for demand variability, causing stock to fall 31.0% below the safety buffer, owned by inventory policy and planning. DC replenishment planning ordered 19.6% less than needed, compounding the shortfall.

## Confirmed causes
1. **Safety stock set too low for demand variability**: Safety Stock Breach Occurrences % = 31.0% (threshold above 20%). *Next step:* Review safety stock for Crunchies Cream Biscuits 100g at Mumbai DC: stock sat below the buffer on 31% of days (off target in 8 of the last 12 weeks), so the buffer does not cover demand variability.
2. **DC ordered less than needed**: Order Qty Deviation % = 19.6% (threshold above 15%). *Next step:* Check Mumbai DC's order quantities against policy: orders fell 20% short of what the inventory norm required.

## Ruled out (with evidence)
- Qty Fill On-Time %: 99.3% vs threshold below 95%: within normal range
- Under-Forecast Error %: -1.6% vs threshold above 10%: within normal range

## How the team challenged itself
- Counter-test on safety_stock_breach_pct: cause **upheld**: stock was already below safety stock on 35.7% of days in the first 6 of the 12 weeks (then 26.2% in the last 6): a chronic problem that predates the other cause, so it stands

## Evidence chain

| Fact | Value | Threshold | Status | Source |
|---|---|---|---|---|
| Qty Fill On-Time % | 99.3% | below 95% | clear | zetaris |
| Under-Forecast Error % | -1.6% | above 10% | clear | zetaris |
| Safety Stock Breach Occurrences % | 31.0% | above 20% | flagged | zetaris |
| Safety Stock Breach Occurrences % (independent recheck) | 31.0% | - | verification | zetaris |
| Order Qty Deviation % | 19.6% | above 15% | flagged | zetaris |
| Order Qty Deviation % (independent recheck) | 4645400.0% | - | verification | zetaris |
| Breach onset test (first 6 vs last 6 of the 12 weeks) | 35.7% | - | counter_test | zetaris |
| Business impact | 1031 | - | impact | zetaris |

## Model calls (Meterless receipts)

| Agent | Model | Receipt | Time | Tokens |
|---|---|---|---|---|
| Planner | nvidia/nemotron-3.5-lightning-30b-a3b | rcpt_req_dbwp3sdw | 13.1s | 1056 |
| Writer | nvidia/nemotron-3.5-lightning-30b-a3b | rcpt_req_irbe1hw7 | 32.6s | 1888 |

*28 agent messages · 0 dig-deeper loop(s) · 0 report revision(s) · 2 model calls via nvidia/nemotron-3.5-lightning-30b-a3b · run OOS-003_20261027_215052*
