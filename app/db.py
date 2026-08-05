"""sqlite3 index over the committed vintages.

The vintages on disk are the source of truth. This database is a derived,
throwaway read index: it is gitignored, and `python -m app.seed` rebuilds it
from scratch on every run. If the two ever disagree, the vintage wins.

Plain SQL, stdlib sqlite3, no ORM.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "geostats.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS vintages (
    dataset_id   TEXT NOT NULL,
    vintage_id   TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    sha256       TEXT NOT NULL,
    byte_size    INTEGER NOT NULL,
    http_status  INTEGER NOT NULL,
    row_count    INTEGER NOT NULL,
    source_url   TEXT NOT NULL,
    is_latest    INTEGER NOT NULL DEFAULT 0,
    meta_json    TEXT NOT NULL,
    PRIMARY KEY (dataset_id, vintage_id)
);

CREATE TABLE IF NOT EXISTS observations (
    dataset_id      TEXT NOT NULL,
    indicator_code  TEXT NOT NULL,
    breakdown_code  TEXT NOT NULL,
    breakdown_label TEXT NOT NULL,
    period          TEXT NOT NULL,
    unit            TEXT NOT NULL,
    value           REAL,
    raw             TEXT NOT NULL,
    status          TEXT NOT NULL,
    is_preliminary  INTEGER NOT NULL,
    vintage_id      TEXT NOT NULL,
    PRIMARY KEY (dataset_id, indicator_code, breakdown_code, period, unit, vintage_id)
);

CREATE INDEX IF NOT EXISTS obs_lookup
    ON observations (dataset_id, vintage_id, indicator_code, breakdown_code, period);

CREATE TABLE IF NOT EXISTS contract_runs (
    dataset_id  TEXT NOT NULL,
    vintage_id  TEXT NOT NULL,
    code        TEXT NOT NULL,
    title       TEXT NOT NULL,
    why         TEXT NOT NULL,
    passed      INTEGER NOT NULL,
    message     TEXT NOT NULL,
    checked     INTEGER NOT NULL,
    offenders   TEXT NOT NULL,
    PRIMARY KEY (dataset_id, vintage_id, code)
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def bootstrap(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def reset(conn: sqlite3.Connection) -> None:
    """Idempotent seeding: wipe the derived tables, then reload."""
    conn.executescript(SCHEMA)
    for table in ("observations", "vintages", "contract_runs"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


# --------------------------------------------------------------------------
# queries used by the routes
# --------------------------------------------------------------------------

def latest_vintage_id(conn: sqlite3.Connection, dataset_id: str) -> str | None:
    row = conn.execute(
        "SELECT vintage_id FROM vintages WHERE dataset_id = ? AND is_latest = 1",
        (dataset_id,),
    ).fetchone()
    return row["vintage_id"] if row else None


def series(
    conn: sqlite3.Connection,
    dataset_id: str,
    indicator_code: str,
    breakdown_code: str,
    *,
    vintage_id: str | None = None,
) -> list[sqlite3.Row]:
    vintage_id = vintage_id or latest_vintage_id(conn, dataset_id)
    if vintage_id is None:
        return []
    return conn.execute(
        """
        SELECT period, unit, value, raw, status, is_preliminary, breakdown_label
          FROM observations
         WHERE dataset_id = ? AND vintage_id = ?
           AND indicator_code = ? AND breakdown_code = ?
         ORDER BY period
        """,
        (dataset_id, vintage_id, indicator_code, breakdown_code),
    ).fetchall()


def value_map(
    conn: sqlite3.Connection,
    dataset_id: str,
    indicator_code: str,
    breakdown_code: str,
    *,
    unit: str | None = None,
    vintage_id: str | None = None,
) -> dict[str, float]:
    rows = series(conn, dataset_id, indicator_code, breakdown_code,
                  vintage_id=vintage_id)
    return {
        r["period"]: r["value"] for r in rows
        if r["value"] is not None and (unit is None or r["unit"] == unit)
    }


def preliminary_periods(
    conn: sqlite3.Connection, dataset_id: str, *, vintage_id: str | None = None
) -> set[str]:
    vintage_id = vintage_id or latest_vintage_id(conn, dataset_id)
    rows = conn.execute(
        """SELECT DISTINCT period FROM observations
            WHERE dataset_id = ? AND vintage_id = ? AND is_preliminary = 1""",
        (dataset_id, vintage_id),
    ).fetchall()
    return {r["period"] for r in rows}


def breakdowns(
    conn: sqlite3.Connection,
    dataset_id: str,
    indicator_code: str,
    *,
    vintage_id: str | None = None,
) -> list[sqlite3.Row]:
    vintage_id = vintage_id or latest_vintage_id(conn, dataset_id)
    return conn.execute(
        """
        SELECT breakdown_code, breakdown_label, COUNT(*) AS n,
               MIN(period) AS first_period, MAX(period) AS last_period
          FROM observations
         WHERE dataset_id = ? AND vintage_id = ? AND indicator_code = ?
      GROUP BY breakdown_code, breakdown_label
      ORDER BY breakdown_code
        """,
        (dataset_id, vintage_id, indicator_code),
    ).fetchall()


def contract_results(
    conn: sqlite3.Connection, dataset_id: str, vintage_id: str | None = None
) -> list[sqlite3.Row]:
    vintage_id = vintage_id or latest_vintage_id(conn, dataset_id)
    return conn.execute(
        """SELECT * FROM contract_runs WHERE dataset_id = ? AND vintage_id = ?
            ORDER BY passed ASC, code ASC""",
        (dataset_id, vintage_id),
    ).fetchall()


def vintage_rows(conn: sqlite3.Connection, dataset_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM vintages WHERE dataset_id = ?
            ORDER BY vintage_id DESC""",
        (dataset_id,),
    ).fetchall()


def all_vintages(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM vintages ORDER BY dataset_id, vintage_id DESC"
    ).fetchall()


def summary(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """SELECT (SELECT COUNT(*) FROM observations) AS observations,
                  (SELECT COUNT(*) FROM vintages) AS vintages,
                  (SELECT COUNT(DISTINCT dataset_id) FROM vintages) AS datasets,
                  (SELECT COUNT(*) FROM contract_runs) AS checks,
                  (SELECT COUNT(*) FROM contract_runs WHERE passed = 1) AS checks_passed,
                  (SELECT MAX(retrieved_at) FROM vintages) AS last_retrieved"""
    ).fetchone()
    return dict(row)


def meta_for(conn: sqlite3.Connection, dataset_id: str, vintage_id: str) -> dict:
    row = conn.execute(
        "SELECT meta_json FROM vintages WHERE dataset_id = ? AND vintage_id = ?",
        (dataset_id, vintage_id),
    ).fetchone()
    return json.loads(row["meta_json"]) if row else {}
