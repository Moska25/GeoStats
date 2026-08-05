"""sqlite3 index over the committed vintages.

The vintages on disk are the source of truth. This database is a derived,
throwaway read index: it is gitignored, and `python -m app.seed` rebuilds it
from scratch on every run. If the two ever disagree, the vintage wins.

Plain SQL, stdlib sqlite3, no ORM.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# The index is derived and rebuilt on every start, so it can live anywhere
# writable. GEOSTATS_DB moves it off the repo for hosts whose application
# directory is read-only (serverless), where the default path cannot be created.
DB_PATH = Path(os.environ.get("GEOSTATS_DB") or REPO_ROOT / "data" / "geostats.db")

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
    -- Printed name of the measure. Empty on the datasets whose measure is
    -- fixed and whose rows are breakdowns; carries the sheet's own wording
    -- where the measure varies down the rows instead.
    indicator_label TEXT NOT NULL DEFAULT '',
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
    """Idempotent seeding: drop the derived tables, then recreate and reload.

    Dropping rather than emptying is deliberate. This database is a read index
    derived from the committed vintages and is rebuilt on every start, so a
    schema change here costs nothing - whereas `DELETE FROM` would leave an
    older table shape in place and fail on the first new column.
    """
    for table in ("observations", "vintages", "contract_runs"):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.executescript(SCHEMA)
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


def indicators(
    conn: sqlite3.Connection, dataset_id: str, *, vintage_id: str | None = None
) -> list[sqlite3.Row]:
    """Every measure in a dataset, with the printed name where one exists."""
    vintage_id = vintage_id or latest_vintage_id(conn, dataset_id)
    return conn.execute(
        """
        SELECT indicator_code,
               MAX(indicator_label) AS indicator_label,
               COUNT(*) AS n,
               MIN(period) AS first_period, MAX(period) AS last_period,
               MIN(unit) AS unit
          FROM observations
         WHERE dataset_id = ? AND vintage_id = ?
      GROUP BY indicator_code
      ORDER BY indicator_code
        """,
        (dataset_id, vintage_id),
    ).fetchall()


def cross_section(
    conn: sqlite3.Connection,
    dataset_id: str,
    indicator_code: str,
    period: str,
    *,
    vintage_id: str | None = None,
) -> dict[str, float]:
    """One measure across every breakdown for a single period.

    This is the shape every regional view needs: a map keyed by the geography
    code, so two datasets can be compared region by region without either one
    knowing about the other.
    """
    vintage_id = vintage_id or latest_vintage_id(conn, dataset_id)
    if vintage_id is None:
        return {}
    rows = conn.execute(
        """SELECT breakdown_code, value FROM observations
            WHERE dataset_id = ? AND vintage_id = ? AND indicator_code = ?
              AND period = ? AND value IS NOT NULL""",
        (dataset_id, vintage_id, indicator_code, period),
    ).fetchall()
    return {r["breakdown_code"]: r["value"] for r in rows}


def periods_for(
    conn: sqlite3.Connection,
    dataset_id: str,
    indicator_code: str | None = None,
    *,
    vintage_id: str | None = None,
) -> list[str]:
    vintage_id = vintage_id or latest_vintage_id(conn, dataset_id)
    if vintage_id is None:
        return []
    sql = """SELECT DISTINCT period FROM observations
              WHERE dataset_id = ? AND vintage_id = ? AND value IS NOT NULL"""
    args: list = [dataset_id, vintage_id]
    if indicator_code:
        sql += " AND indicator_code = ?"
        args.append(indicator_code)
    return [r["period"] for r in conn.execute(sql + " ORDER BY period", args)]


def observations(
    conn: sqlite3.Connection,
    dataset_id: str,
    *,
    indicator_code: str | None = None,
    breakdown_code: str | None = None,
    period_from: str | None = None,
    period_to: str | None = None,
    vintage_id: str | None = None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Filtered rows for the generalised explorer and its CSV export.

    Both callers read from here so the download cannot drift from the table it
    claims to be a copy of.
    """
    vintage_id = vintage_id or latest_vintage_id(conn, dataset_id)
    if vintage_id is None:
        return []
    sql = """SELECT dataset_id, indicator_code, indicator_label, breakdown_code,
                    breakdown_label, period, unit, value, raw, status,
                    is_preliminary, vintage_id
               FROM observations
              WHERE dataset_id = ? AND vintage_id = ?"""
    args: list = [dataset_id, vintage_id]
    for column, value in (("indicator_code", indicator_code),
                          ("breakdown_code", breakdown_code)):
        if value:
            sql += f" AND {column} = ?"
            args.append(value)
    if period_from:
        sql += " AND period >= ?"
        args.append(period_from)
    if period_to:
        sql += " AND period <= ?"
        args.append(period_to)
    sql += " ORDER BY indicator_code, breakdown_code, period"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, args).fetchall()


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


def failing_checks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every red check on a latest vintage, for the health endpoint.

    Restricted to latest vintages: a superseded release failing a check is
    history, and history is exactly what this project refuses to rewrite.
    """
    return conn.execute(
        """SELECT c.dataset_id, c.vintage_id, c.code, c.message
             FROM contract_runs c
             JOIN vintages v
               ON v.dataset_id = c.dataset_id AND v.vintage_id = c.vintage_id
            WHERE c.passed = 0 AND v.is_latest = 1
            ORDER BY c.dataset_id, c.code"""
    ).fetchall()


def meta_for(conn: sqlite3.Connection, dataset_id: str, vintage_id: str) -> dict:
    row = conn.execute(
        "SELECT meta_json FROM vintages WHERE dataset_id = ? AND vintage_id = ?",
        (dataset_id, vintage_id),
    ).fetchone()
    return json.loads(row["meta_json"]) if row else {}
