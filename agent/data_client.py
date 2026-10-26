"""Data layer: every fact the agents use comes from a SQL query.

ZetarisClient   - the real route: SQL over the Zetaris REST API, which
                  federates the three source systems (orders, planning, WMS).
SampleClient    - SAMPLE_MODE: the same SQL against the bundled CSVs in SQLite,
                  so the project runs with no credentials or Docker.

Both return QueryResult(columns, rows, sql, ms, source).
"""
import csv
import datetime as dt
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field

from . import config


class DataError(Exception):
    pass


@dataclass
class QueryResult:
    columns: list
    rows: list
    sql: str
    ms: int
    source: str
    attempts: int = 1
    notes: list = field(default_factory=list)

    def first(self):
        """First row as a dict, with numeric strings converted to numbers."""
        if not self.rows:
            return {}
        return {c: _val(c, v) for c, v in zip(self.columns, self.rows[0])}

    def records(self, limit=None):
        rows = self.rows[:limit] if limit else self.rows
        return [{c: _val(c, v) for c, v in zip(self.columns, r)} for r in rows]


def _val(col, v):
    # Identifiers (sku_id, dc_id, ...) stay text even when they look numeric.
    if col.lower().endswith("_id"):
        return None if v is None else str(v)
    return _num(v)


def _num(v):
    if v is None or isinstance(v, (int, float)):
        return v
    try:
        f = float(v)
        return int(f) if f.is_integer() and "." not in str(v) else f
    except (TypeError, ValueError):
        return v


class ZetarisClient:
    """Runs one SQL statement through Zetaris' SQL Editor REST endpoint."""

    name = "zetaris"

    def __init__(self):
        if not config.ZETARIS_API_KEY:
            raise DataError("ZETARIS_API_KEY is missing from .env")
        import requests  # noqa: local import keeps SAMPLE_MODE dependency-free
        self._requests = requests

    def run(self, sql, retries=2):
        url = config.ZETARIS_REST_URL.rstrip("/") + "/sql-editor/sqls/run"
        last_err = None
        for attempt in range(1, retries + 2):
            t0 = time.time()
            try:
                r = self._requests.post(
                    url,
                    headers={
                        "Authorization": "Bearer " + config.ZETARIS_API_KEY,
                        "X-Org-ID": str(config.ZETARIS_ORG_ID),
                        "X-Request-ID": str(uuid.uuid4()),
                        "Content-Type": "application/json",
                    },
                    json={"queryId": str(uuid.uuid4()), "sql": sql,
                          "source": "SqlEditor", "limit": 1000},
                    timeout=config.ZETARIS_TIMEOUT_S,
                )
                if r.status_code >= 400:
                    raise DataError(f"Zetaris HTTP {r.status_code}: {r.text[:300]}")
                body = r.json()
                return QueryResult(columns=body.get("headers", []),
                                   rows=body.get("data", []), sql=sql,
                                   ms=int((time.time() - t0) * 1000),
                                   source=self.name, attempts=attempt)
            except Exception as e:  # network error, timeout, HTTP error
                last_err = e
                if attempt <= retries:
                    time.sleep(1.5 * attempt)
        raise DataError(f"Zetaris query failed after {retries + 1} attempts: {last_err}")


class SampleClient:
    """SQLite over the bundled CSVs, with Spark-style date helpers."""

    name = "sample-sqlite"
    TABLES = {
        "orders": ["replenishment_orders"],
        "planning": ["demand_daily", "skus"],
        "wms": ["inventory_snapshots", "inventory_norms", "stockout_events", "dcs"],
        "finance": ["sku_economics"],
    }

    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.create_function("date_sub", 2, _date_sub)
        self.db.create_function("datediff", 2, _datediff)
        self.db.create_function("GREATEST", -1, lambda *a: max(x for x in a if x is not None))
        self.db.create_function("LEAST", -1, lambda *a: min(x for x in a if x is not None))
        csv_dir = config.DATA_DIR / "csv"
        for tables in self.TABLES.values():
            for t in tables:
                with open(csv_dir / f"{t}.csv", newline="") as f:
                    rows = list(csv.reader(f))
                cols = rows[0]
                self.db.execute(f"CREATE TABLE {t} ({', '.join(cols)})")
                self.db.executemany(
                    f"INSERT INTO {t} VALUES ({', '.join('?' * len(cols))})",
                    [[(v if c.endswith("_id") else _num(v)) if v != "" else None
                      for c, v in zip(cols, r)] for r in rows[1:]])

    def run(self, sql, retries=0):
        t0 = time.time()
        # Spark/ANSI date literal DATE '2026-01-01' -> plain ISO string in SQLite
        s = re.sub(r"DATE\s+'(\d{4}-\d{2}-\d{2})'", r"'\1'", sql)
        # source-qualified names like scm_orders.t -> t (all tables share one SQLite db)
        for prefix in sorted(set(config.SOURCES.values()), key=len, reverse=True):
            s = s.replace(prefix + ".", "")
        try:
            cur = self.db.execute(s)
        except sqlite3.Error as e:
            raise DataError(f"sample query failed: {e}")
        cols = [d[0] for d in cur.description]
        return QueryResult(columns=cols, rows=[list(r) for r in cur.fetchall()],
                           sql=sql, ms=int((time.time() - t0) * 1000),
                           source=self.name)


def _date_sub(d, n):
    if d is None:
        return None
    return (dt.date.fromisoformat(str(d)[:10]) - dt.timedelta(days=int(n))).isoformat()


def _datediff(a, b):
    if a is None or b is None:
        return None
    return (dt.date.fromisoformat(str(a)[:10]) - dt.date.fromisoformat(str(b)[:10])).days


def get_client():
    return SampleClient() if config.SAMPLE_MODE else ZetarisClient()
