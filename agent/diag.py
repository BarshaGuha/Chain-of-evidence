"""Diagnose why the Writer's Nemotron call hits Nightshift's provider deadline.

    python3 -m agent.diag

Sends Writer requests to Meterless Nightshift (the new short prompt and the old one) and
prints how long each took and whether it worked. Takes 1-4 minutes.
"""
import time

import requests

from . import config

SYSTEM = ("You are the Writer in a supply-chain root-cause team. Write a headline and a short "
          "summary for a supply chain planner. Use ONLY the confirmed causes and the numbers "
          "given; copy percentages exactly. Keep your reasoning short and answer quickly. "
          "Reply with JSON only.")
USER = """Stockout: Pearlguard Toothpaste 150g (SKU 100562) at Bengaluru DC on 2026-08-06, lost demand 83 units.
Confirmed causes (most severe first): ['Transport delays from plant to DC']
Owners: ['Transport / logistics']
Evidence pack:
- Qty Fill On-Time %: 49.2% (threshold below 95%; flagged)
- Under-Forecast Error %: -1.1% (threshold above 10%; clear)
- Qty Fill Rate %: 99.0% (threshold below 95%; clear)
- Qty On-Time %: 49.7% (threshold below 95%; flagged)
- Lead Time Overrun %: 35.0% (threshold above 15%; flagged)
Rolled back during review: 'Safety stock set too low for demand variability' was rolled back: breaches were 2.4% in weeks 12-7 but 57.1% in weeks 6-1.
Do not write money amounts.

JSON: {"headline": "one sentence naming the cause(s), product and DC", "narrative": "2-3 sentences"}"""

LEAN = ("Write a one-sentence headline and a two-sentence summary for a supply chain "
        "manager, using only these facts. No money amounts.\n"
        "Product: Pearlguard Toothpaste 150g at Bengaluru DC, out of stock on 6 Aug.\n"
        "Root cause: Transport delays from plant to DC (deliveries slower than the standard "
        "lead time: 35.0%). Owner: Transport / logistics.\n"
        "Ruled out as a symptom: Safety stock set too low for demand variability (it started "
        "only after the real cause: 2.4% of days before, 57.1% after).\n"
        "Warning sign visible 35 days before the stockout.\n"
        'JSON: {"headline": "...", "narrative": "..."}')

# (label, role, system, max_tokens, user)
TESTS = [
    (f"Run {i}: Writer prompt (short fact sheet), 3500-token cap", "writer",
     "Reply with JSON only.", 3500, LEAN) for i in (1, 2, 3)
]


def main():
    url = config.METERLESS_BASE_URL.rstrip("/") + "/chat/completions"
    print(f"Nightshift: {url}\nModel: {config.METERLESS_MODEL}\n")
    for name, role, system, max_tokens, user in TESTS:
        t0 = time.time()
        try:
            r = requests.post(url, timeout=150, json={
                "model": config.METERLESS_MODEL, "max_tokens": max_tokens, "temperature": 0.2,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]},
                headers={"Authorization": "Bearer " + config.METERLESS_RUNTIME_TOKEN,
                         "Content-Type": "application/json",
                         "meterless-app": f"{config.METERLESS_APP}-diag-{role}",
                         "meterless-scope": "user"})
            p = r.json()
            secs = time.time() - t0
            if "error" in p:
                print(f"{name}\n   FAILED after {secs:.0f}s: {str(p['error'])[:160]}\n")
                continue
            text = (p["choices"][0]["message"].get("content") or "").strip()
            m = p.get("meterless", {})
            print(f"{name}\n   OK in {secs:.0f}s, {p.get('usage', {}).get('total_tokens')} tokens, "
                  f"routed to {m.get('routed_model')}\n   answer: {text[:140]!r}\n")
        except Exception as e:
            print(f"{name}\n   FAILED after {time.time() - t0:.0f}s: {e}\n")


if __name__ == "__main__":
    main()
