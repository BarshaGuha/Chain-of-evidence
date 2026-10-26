"""Configuration: thresholds, data-source names and runtime settings.

Everything secret comes from environment variables (.env). Nothing here is a
credential. SAMPLE_MODE=true runs the whole system with no credentials:
data from the bundled CSVs (SQLite) and a deterministic offline reasoner
instead of Nemotron.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:  # optional: python-dotenv
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


def _bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes")


SAMPLE_MODE = _bool("SAMPLE_MODE", False)

# ---- Power: Nemotron through Meterless Nightshift (OpenAI-compatible) ----
METERLESS_BASE_URL = os.environ.get("METERLESS_BASE_URL", "http://127.0.0.1:8088/v1")
METERLESS_RUNTIME_TOKEN = os.environ.get("METERLESS_RUNTIME_TOKEN", "")
METERLESS_MODEL = os.environ.get("METERLESS_MODEL",
                                 "nvidia/nemotron-3.5-lightning-30b-a3b")
METERLESS_APP = os.environ.get("METERLESS_APP", "chain-of-evidence")
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "3000"))
# The Writer produces the longest answer; give it room to think and still reply.
WRITER_MAX_TOKENS = int(os.environ.get("WRITER_MAX_TOKENS", "3500"))
LLM_TIMEOUT_S = int(os.environ.get("LLM_TIMEOUT_S", "120"))

# ---- Data: Zetaris REST API ----
ZETARIS_REST_URL = os.environ.get("ZETARIS_REST_URL", "http://localhost:8888/api/v1.0")
ZETARIS_ORG_ID = os.environ.get("ZETARIS_ORG_ID", "1")
ZETARIS_API_KEY = os.environ.get("ZETARIS_API_KEY", "")
ZETARIS_TIMEOUT_S = int(os.environ.get("ZETARIS_TIMEOUT_S", "90"))

# How each source system is addressed in Zetaris SQL: <source>.<table>.
# Four separate Postgres databases, each registered in Zetaris as its own
# source, so every investigation is a federated query across systems.
SOURCES = {
    "orders": os.environ.get("ZETARIS_SOURCE_ORDERS", "scm_orders"),
    "planning": os.environ.get("ZETARIS_SOURCE_PLANNING", "scm_planning"),
    "wms": os.environ.get("ZETARIS_SOURCE_WMS", "scm_wms"),
    "finance": os.environ.get("ZETARIS_SOURCE_FINANCE", "scm_finance"),
}

# ---- Investigation settings ----
P1_DAYS = int(os.environ.get("P1_DAYS", "84"))          # 12-week look-back
MAX_DIG_DEEPER_LOOPS = int(os.environ.get("MAX_DIG_DEEPER_LOOPS", "2"))
MAX_REPORT_REVISIONS = int(os.environ.get("MAX_REPORT_REVISIONS", "2"))
MAX_MESSAGES = int(os.environ.get("MAX_MESSAGES", "120"))  # safety cap
BORDERLINE_BAND = float(os.environ.get("BORDERLINE_BAND", "0.02"))  # within 2 percentage points

# Threshold per metric: (direction, value). "below" flags when value < threshold.
THRESHOLDS = {
    "fill_on_time_pct": ("below", 0.95),
    "fill_rate_pct": ("below", 0.95),
    "on_time_pct": ("below", 0.95),
    "lead_time_overrun_pct": ("above", 0.15),
    "order_qty_deviation_pct": ("above", 0.15),
    "under_forecast_error_pct": ("above", 0.10),
    "under_forecast_error_recent_pct": ("above", 0.10),
    "safety_stock_breach_pct": ("above", 0.20),
}

# Business impact: yearly cost of holding stock (prices come from scm_finance).
CARRYING_RATE = float(os.environ.get("CARRYING_RATE", "0.20"))   # 20% of value a year

LOG_DIR = ROOT / "logs"
OUTPUT_DIR = ROOT / "outputs"
DATA_DIR = ROOT / "data"
