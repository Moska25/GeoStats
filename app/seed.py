"""Rebuild the sqlite read index from the committed vintages.

Idempotent and deterministic: it wipes the derived tables and reloads every
vintage on disk, so running it twice produces exactly the same database. No
network access, no randomness, no synthetic data - every row comes from a
workbook that Geostat published and that is committed in data/vintages/.
"""

from __future__ import annotations

import json
import sys

from . import db
from .contracts import run_contracts
from .ingest import all_datasets, list_vintages, read_meta, read_rows
from .pxweb import snapshot_rows_by_dataset


def seed(verbose: bool = True, api_rows_by_dataset: dict | None = None) -> dict:
    """Rebuild the read index.

    `api_rows_by_dataset` optionally supplies the PX-Web reading of a dataset so
    SOURCE_AGREEMENT can run. It is passed in rather than fetched here because
    seeding must stay offline: the committed vintages are the source of truth
    and a rebuild cannot depend on a network round trip.
    """
    # Default to the committed API snapshots. They are files on disk like the
    # vintages are, so seeding stays offline and SOURCE_AGREEMENT is a check
    # the running application performs rather than a script somebody once ran.
    if api_rows_by_dataset is None:
        api_rows_by_dataset = snapshot_rows_by_dataset()
    conn = db.connect()
    db.reset(conn)

    cpi_dataset = "cpi_2010_base"
    cpi_latest = list_vintages(cpi_dataset)
    cpi_rows = read_rows(cpi_dataset, cpi_latest[-1]) if cpi_latest else None

    loaded = {"datasets": 0, "vintages": 0, "observations": 0, "checks": 0}
    for dataset_id in all_datasets():
        vintage_ids = list_vintages(dataset_id)
        if not vintage_ids:
            if verbose:
                print(f"  {dataset_id}: no committed vintage, skipped")
            continue
        loaded["datasets"] += 1
        prior_rows = None
        for index, vintage_id in enumerate(vintage_ids):
            meta = read_meta(dataset_id, vintage_id)
            rows = read_rows(dataset_id, vintage_id)
            is_latest = 1 if index == len(vintage_ids) - 1 else 0

            conn.execute(
                """INSERT INTO vintages (dataset_id, vintage_id, retrieved_at,
                       sha256, byte_size, http_status, row_count, source_url,
                       is_latest, meta_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (dataset_id, vintage_id, meta["retrieved_at"], meta["sha256"],
                 meta["byte_size"], meta["http_status"], meta["row_count"],
                 meta["source_url"], is_latest, json.dumps(meta)),
            )
            conn.executemany(
                """INSERT OR REPLACE INTO observations (dataset_id, indicator_code,
                       indicator_label, breakdown_code, breakdown_label, period,
                       unit, value, raw, status, is_preliminary, vintage_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    # .get on indicator_label: vintages committed before the
                    # field existed are still authoritative and must load.
                    (r["dataset_id"], r["indicator_code"],
                     r.get("indicator_label", ""), r["breakdown_code"],
                     r["breakdown_label"], r["period"], r["unit"], r["value"],
                     r["raw"], r["status"], int(bool(r["is_preliminary"])),
                     r["vintage_id"])
                    for r in rows
                ],
            )
            loaded["vintages"] += 1
            loaded["observations"] += len(rows)

            results = run_contracts(
                rows, dataset_id=dataset_id,
                cpi_rows=cpi_rows, prior_rows=prior_rows,
                api_rows=(
                    api_rows_by_dataset.get(dataset_id) if is_latest else None
                ),
            )
            conn.executemany(
                """INSERT OR REPLACE INTO contract_runs (dataset_id, vintage_id,
                       code, title, why, passed, message, checked, offenders)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                [
                    (dataset_id, vintage_id, r.code, r.title, r.why,
                     int(r.passed), r.message, r.checked,
                     json.dumps(r.offenders, ensure_ascii=False))
                    for r in results
                ],
            )
            loaded["checks"] += len(results)
            prior_rows = rows

            if verbose:
                failed = [r.code for r in results if not r.passed]
                flag = "OK  " if not failed else "FAIL"
                print(
                    f"  {flag} {dataset_id:22} {vintage_id}  "
                    f"{len(rows):5} rows  "
                    f"{len(results) - len(failed)}/{len(results)} contracts"
                    + (f"  [{', '.join(failed)}]" if failed else "")
                )
    conn.commit()
    conn.close()
    return loaded


def main() -> int:
    print("GeoStats: rebuilding sqlite index from committed vintages")
    loaded = seed()
    print(
        f"  loaded {loaded['observations']} observations across "
        f"{loaded['vintages']} vintages of {loaded['datasets']} datasets, "
        f"{loaded['checks']} contract checks recorded"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
