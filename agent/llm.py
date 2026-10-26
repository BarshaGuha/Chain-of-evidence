"""Power layer: every model call goes through Meterless Nightshift.

Nightshift exposes an OpenAI-compatible endpoint and routes to NVIDIA Nemotron.
Each response carries a signed Meterless compute receipt; we keep the receipt
summary (model actually used, latency, receipt id) as evidence in the logs.

If SAMPLE_MODE is on, or a call fails after retries, the caller-supplied
deterministic fallback is used and the result is marked as such, so the run
completes and the logs show exactly what happened.
"""
import json
import re
import time
from dataclasses import dataclass, field

from . import config


@dataclass
class LLMResult:
    text: str
    data: dict = field(default_factory=dict)   # parsed JSON, if asked for
    model: str = ""
    receipt_id: str = ""
    latency_ms: int = 0
    tokens: int = 0
    fallback: bool = False
    error: str = ""
    receipt: dict = field(default_factory=dict)  # full Meterless receipt


def _extract_json(text):
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


class Nemotron:
    def __init__(self):
        self.calls = 0
        if not config.SAMPLE_MODE:
            import requests
            self._requests = requests
            if not config.METERLESS_RUNTIME_TOKEN:
                raise RuntimeError("METERLESS_RUNTIME_TOKEN is missing from .env")

    def ask(self, role, system, user, fallback, want_json=True, retries=1, max_tokens=None):
        """Ask Nemotron (as `role`). `fallback()` must return (text, data).

        Nemotron Lightning is a reasoning model: it "thinks" before it answers,
        and the thinking counts against max_tokens. If it runs out of budget it
        returns an empty answer, so on an empty response we retry with double
        the budget instead of giving up.
        """
        self.calls += 1
        if config.SAMPLE_MODE:
            text, data = fallback()
            return LLMResult(text=text, data=data or {}, model="offline-reasoner",
                             fallback=True, error="SAMPLE_MODE")
        url = config.METERLESS_BASE_URL.rstrip("/") + "/chat/completions"
        body = {
            "model": config.METERLESS_MODEL,
            "max_tokens": max_tokens or config.LLM_MAX_TOKENS,
            "temperature": 0.2,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        last = ""
        for attempt in range(retries + 1):
            t0 = time.time()
            try:
                r = self._requests.post(
                    url, json=body, timeout=config.LLM_TIMEOUT_S,
                    headers={"Authorization": "Bearer " + config.METERLESS_RUNTIME_TOKEN,
                             "Content-Type": "application/json",
                             "meterless-app": f"{config.METERLESS_APP}-{role}",
                             "meterless-scope": "user"})
                payload = r.json()
                if r.status_code >= 400 or "error" in payload:
                    raise RuntimeError(str(payload.get("error", payload))[:300])
                text = (payload["choices"][0]["message"].get("content") or "").strip()
                if not text:
                    raise RuntimeError("empty_response")
                data = _extract_json(text) if want_json else {}
                if want_json and data is None:
                    raise ValueError("model did not return valid JSON")
                m = payload.get("meterless", {})
                return LLMResult(
                    text=text, data=data or {},
                    model=m.get("routed_model") or payload.get("model", ""),
                    receipt_id=m.get("receipt_id", ""),
                    latency_ms=int((time.time() - t0) * 1000),
                    tokens=payload.get("usage", {}).get("total_tokens", 0),
                    receipt=m)
            except Exception as e:  # rate limit, timeout, bad JSON ...
                last = str(e)
                # Nemotron Lightning thinks before it answers. Out of budget (empty
                # answer): allow a little more. Past Nightshift's ~40 s provider
                # deadline: ask for less. The cap is a ceiling, not a target.
                if "empty_response" in last:
                    body["max_tokens"] = min(int(body["max_tokens"] * 1.4), 4500)
                elif "deadline" in last or "timed out" in last.lower():
                    body["max_tokens"] = max(2000, int(body["max_tokens"] * 0.7))
                time.sleep(2 * (attempt + 1))
        text, data = fallback()
        return LLMResult(text=text, data=data or {}, model="offline-reasoner",
                         fallback=True, error=last[:300])
