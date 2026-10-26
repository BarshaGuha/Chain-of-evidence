"""Local web interface for Chain of Evidence.

  python3 -m agent.server            then open http://localhost:8765

The user asks a question ("Why did SKU-B stock out at DC2?") or picks a
stockout. The investigation runs exactly as on the command line; every agent
message is streamed to the browser as it happens (Server-Sent Events), so the
page shows the agents talking, the case board filling up, the loops and
rollbacks, and finally the signed-off report with its Meterless receipts.

Uses only the Python standard library.
"""
import json
import queue
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config
from .data_client import get_client
from .llm import Nemotron
from .main import investigate, list_events

PORT = 8765
PACE_S = float(__import__('os').environ.get('DEMO_PACE_S', '0.35'))
WEB = Path(__file__).resolve().parent / "web" / "index.html"

DATA = get_client()
LLM = Nemotron()
RUN_LOCK = threading.Lock()
INBOX = {"q": None}   # the running investigation's analyst inbox


def events():
    return [{k: (str(v)[:10] if k == "oos_date" else v) for k, v in e.items()}
            for e in list_events(DATA)]


CITY = {"mumbai": "DC1", "bombay": "DC1", "delhi": "DC2", "bengaluru": "DC3",
        "bangalore": "DC3"}


def _words(text):
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 4}


def resolve(question, evs):
    """Turn a free-text question into one stockout event, the way an analyst asks:
    by product name or brand, SKU code, city or DC, or event id. Anything vaguer
    goes to Nemotron (via Meterless), which reads the question and picks one.
    """
    q = question.lower()
    m = re.search(r"oos-?\s?(\d{3})", q)
    if m:
        hit = [e for e in evs if e["event_id"] == f"OOS-{m.group(1)}"]
        if hit:
            return hit[0], "matched the event id in your question"
    cands, how = list(evs), []
    codes = set(re.findall(r"\b\d{6}\b", q))
    if codes:
        cands = [e for e in cands if str(e["sku_id"]) in codes]
        how.append("SKU code")
    qw = _words(q)
    scored = []
    for e in cands:
        name = str(e.get("product_name") or "")
        brand = name.split()[0].lower() if name else ""
        score = len(qw & _words(name)) + (2 if brand in qw else 0)
        scored.append((score, e))
    best = max((sc for sc, _ in scored), default=0)
    if best:
        cands = [e for sc, e in scored if sc == best]
        how.append("product name")
    dcs = {CITY[w] for w in qw if w in CITY} | {f"DC{d}" for d in re.findall(r"\bdc[-\s]?(\d)\b", q)}
    if dcs:
        cands = [e for e in cands if e["dc_id"] in dcs]
        how.append("location")
    if how and len(cands) == 1:
        return cands[0], "matched the " + " and ".join(how) + " in your question"
    listing = "\n".join(f"- {e['event_id']}: {e.get('product_name')} (SKU {e['sku_id']}, "
                        f"{e.get('category', '')}) at {e.get('dc_name', e['dc_id'])}, out of stock "
                        f"on {str(e['oos_date'])[:10]}, lost {e['lost_demand_qty']} units"
                        for e in evs)
    r = LLM.ask("intake",
                "You route a supply-chain question to the stockout event it is about. "
                "Reply with JSON only.",
                f"Question: {question}\nStockout events:\n{listing}\n"
                'JSON: {"event_id": "OOS-00X or none", "reason": "short"}',
                lambda: ("", {"event_id": "none"}))
    hit = [e for e in evs if e["event_id"] == r.data.get("event_id")]
    if hit:
        return hit[0], f"Nemotron matched your question ({r.model})"
    if how and len(cands) > 1:
        return None, ("several stockouts match: " + "; ".join(
            f"{e['event_id']} {e.get('product_name')} at {e.get('dc_name')}" for e in cands)
            + ". Say which product you mean.")
    return None, "could not match the question to a recorded stockout"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            body = WEB.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/info":
            self._json({"sample_mode": config.SAMPLE_MODE, "model": config.METERLESS_MODEL,
                        "data": DATA.name, "events": events()})
        elif url.path == "/api/run":
            self.stream(parse_qs(url.query))
        elif url.path == "/api/reply":
            qs = parse_qs(url.query)
            if INBOX["q"] is None:
                self._json({"ok": False, "error": "nothing is waiting for a reply"}, 409)
            else:
                INBOX["q"].put({"choice": qs.get("choice", ["recommended"])[0],
                                "text": qs.get("text", [""])[0][:500]})
                self._json({"ok": True})
        else:
            self._json({"error": "not found"}, 404)

    def stream(self, qs):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def emit(obj):
            self.wfile.write(f"data: {json.dumps(obj, default=str)}\n\n".encode())
            self.wfile.flush()

        if not RUN_LOCK.acquire(blocking=False):
            emit({"type": "error", "message": "An investigation is already running."})
            return
        try:
            evs = events()
            event_id, question = qs.get("event", [""])[0], qs.get("q", [""])[0].strip()
            if event_id:
                ev = next((e for e in evs if e["event_id"] == event_id), None)
                how = "selected from the list"
            else:
                ev, how = resolve(question, evs)
            emit({"type": "intake", "question": question, "how": how,
                  "event": ev})
            if not ev:
                emit({"type": "error", "message": how})
                return

            q = queue.Queue()
            box = {}
            inbox = queue.Queue() if qs.get("checkpoint", ["0"])[0] == "1" else None
            INBOX["q"] = inbox

            def listen(entry):
                q.put(entry)
                if config.SAMPLE_MODE and PACE_S:   # let the offline demo animate
                    time.sleep(PACE_S)

            def work():
                try:
                    box["result"] = investigate(ev, DATA, LLM, printer=print, listener=listen,
                                              human_inbox=inbox)
                except Exception as e:  # surface any failure in the page
                    box["error"] = str(e)
                finally:
                    q.put(None)

            threading.Thread(target=work, daemon=True).start()
            while True:
                try:
                    item = q.get(timeout=10)
                except queue.Empty:
                    self.wfile.write(b": still working\n\n")   # keep-alive
                    self.wfile.flush()
                    continue
                if item is None:
                    break
                emit({"type": "message", "msg": item} if "from" in item else item)
            if "error" in box:
                emit({"type": "error", "message": box["error"]})
            else:
                r = box["result"]
                emit({"type": "done", **{k: r[k] for k in (
                    "case", "run_id", "status", "report", "confirmed_causes", "rollbacks", "chains", "impact",
                    "loops", "report_revisions", "evaluator_judgements", "messages",
                    "model_calls", "models_used", "receipts", "elapsed_s", "sample_mode", "checkpoint")}})
        except (BrokenPipeError, ConnectionResetError):
            pass  # the browser went away; the run still finishes and is logged
        finally:
            INBOX["q"] = None
            RUN_LOCK.release()


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    mode = "SAMPLE MODE (offline)" if config.SAMPLE_MODE else \
        f"LIVE: Zetaris + {config.METERLESS_MODEL} via Meterless"
    print(f"Chain of Evidence is running ({mode})")
    if config.AUTO_SAMPLE:
        print("No .env keys found, so running in SAMPLE MODE. Copy .env.example to .env "
              "and add your keys to run live on Zetaris and Nemotron.")
    print(f"Open http://localhost:{PORT} in your browser. Press Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
