"""Batch refresh across every dataset, or a named subset.

Twenty datasets means twenty chances for a network hiccup, and a run that
abandons nineteen successful downloads because the twentieth timed out is worse
than useless. Every dataset is therefore attempted independently and reported
independently: one failure is a line in the report, not the end of the run.

The sqlite read index is rebuilt only after the whole batch has been written and
validated. Rebuilding per dataset would leave the index describing a state that
never existed as a whole - half the datasets refreshed, half not - which is
exactly the sort of thing this project exists to refuse.

Usage:

    python -m app.refresh_all                       every dataset
    python -m app.refresh_all labour_force cpi_yoy  named datasets only
    python -m app.refresh_all --dry-run             report without writing
    python -m app.refresh_all --snapshots           also recapture PX-Web
"""

from __future__ import annotations

import sys

from .adapters import ADAPTERS
from .contracts import run_contracts
from .ingest import (
    all_datasets, latest_vintage, list_vintages, read_rows, refresh,
)


def refresh_many(
    dataset_ids: list[str] | None = None, *, dry_run: bool = False,
) -> dict:
    """Refresh each dataset in turn. Never raises for a single dataset's sake."""
    targets = dataset_ids or all_datasets()
    unknown = [d for d in targets if d not in ADAPTERS]
    if unknown:
        return {"ok": False, "error": f"unknown dataset(s): {', '.join(unknown)}",
                "results": []}

    results = []
    for dataset_id in targets:
        if dry_run:
            adapter = ADAPTERS[dataset_id]
            results.append({
                "dataset_id": dataset_id, "ok": True, "dry_run": True,
                "previous_vintage": latest_vintage(dataset_id),
                "message": f"would fetch {adapter.url}",
            })
            continue
        try:
            outcome = refresh(dataset_id)
        except Exception as exc:                     # noqa: BLE001 - reported
            # A refresh must not be able to take the batch down with it.
            outcome = {
                "ok": False, "dataset_id": dataset_id,
                "error": f"unexpected {type(exc).__name__}: {exc}",
            }
        results.append(outcome)

    summary = {
        "ok": all(r.get("ok") for r in results),
        "attempted": len(results),
        "new_vintages": [
            r["dataset_id"] for r in results if r.get("new_vintage")
        ],
        "unchanged": [r["dataset_id"] for r in results if r.get("unchanged")],
        "failed": [r["dataset_id"] for r in results if not r.get("ok")],
        "results": results,
        "dry_run": dry_run,
    }
    if not dry_run and summary["new_vintages"]:
        summary["contracts"] = _validate(summary["new_vintages"])
    return summary


def _validate(dataset_ids: list[str]) -> dict:
    """Run the contracts over each freshly written vintage.

    A new vintage is written before it is validated, on purpose: the bytes
    Geostat served are a fact and get recorded whether or not they pass. What
    validation decides is whether the numbers may be *used*, and the answer is
    reported rather than acted on silently.
    """
    cpi_latest = list_vintages("cpi_2010_base")
    cpi_rows = read_rows("cpi_2010_base", cpi_latest[-1]) if cpi_latest else None

    out = {}
    for dataset_id in dataset_ids:
        vintage_id = latest_vintage(dataset_id)
        if not vintage_id:
            continue
        results = run_contracts(
            read_rows(dataset_id, vintage_id),
            dataset_id=dataset_id, cpi_rows=cpi_rows,
        )
        out[dataset_id] = {
            "vintage_id": vintage_id,
            "passed": sum(1 for r in results if r.passed),
            "total": len(results),
            "failed": [r.code for r in results if not r.passed],
        }
    return out


def refresh_snapshots(dataset_ids: list[str] | None = None) -> list[dict]:
    """Capture a fresh PX-Web reading for every dataset that has a table.

    Separate from the vintage refresh because they are different artefacts: a
    vintage is what Geostat published as a file, a snapshot is what its API
    served. Both are frozen with a checksum, and neither overwrites the last
    one.
    """
    from .pxweb import PX_TABLES, write_snapshot

    targets = [d for d in (dataset_ids or PX_TABLES) if d in PX_TABLES]
    out = []
    for dataset_id in targets:
        try:
            out.append({"ok": True, "dataset_id": dataset_id,
                        "meta": write_snapshot(dataset_id)})
        except Exception as exc:                 # noqa: BLE001 - reported
            out.append({"ok": False, "dataset_id": dataset_id,
                        "error": f"{type(exc).__name__}: {exc}"})
    return out


def rebuild_index() -> dict:
    """Rebuild the sqlite read index. Imported lazily: seeding imports contracts,
    and doing it at module scope would make a refresh depend on a working
    database in order to write files that do not need one."""
    from .seed import seed
    return seed(verbose=False)


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    with_snapshots = "--snapshots" in argv
    names = [a for a in argv if not a.startswith("--")]

    print(f"GeoStats: refreshing {len(names) or len(all_datasets())} dataset(s)"
          + (" (dry run)" if dry_run else ""))
    summary = refresh_many(names or None, dry_run=dry_run)
    if "error" in summary:
        print(f"  {summary['error']}")
        return 2

    for result in summary["results"]:
        dataset_id = result.get("dataset_id", "?")
        if not result.get("ok"):
            print(f"  FAIL      {dataset_id:26} {result.get('error', '')[:90]}")
        elif result.get("dry_run"):
            print(f"  DRY       {dataset_id:26} {result['message'][:90]}")
        elif result.get("unchanged"):
            print(f"  UNCHANGED {dataset_id:26} bytes identical to "
                  f"{result['previous_vintage']}")
        else:
            print(f"  NEW       {dataset_id:26} {result['new_vintage']}")

    for dataset_id, check in (summary.get("contracts") or {}).items():
        flag = "OK  " if not check["failed"] else "RED "
        print(f"  {flag}      {dataset_id:26} {check['passed']}/{check['total']}"
              + (f"  {check['failed']}" if check["failed"] else ""))

    if with_snapshots and not dry_run:
        for result in refresh_snapshots(names or None):
            if result["ok"]:
                meta = result["meta"]
                print(f"  SNAPSHOT  {result['dataset_id']:26} "
                      f"{meta['row_count']} rows  sha {meta['sha256'][:12]}")
            else:
                print(f"  SNAP FAIL {result['dataset_id']:26} {result['error'][:70]}")

    if (summary["new_vintages"] or with_snapshots) and not dry_run:
        loaded = rebuild_index()
        print(f"  index rebuilt: {loaded['observations']} observations across "
              f"{loaded['vintages']} vintages of {loaded['datasets']} datasets")
    elif not dry_run:
        print("  no new vintages; index left alone")

    print(f"  {len(summary['new_vintages'])} new, "
          f"{len(summary['unchanged'])} unchanged, {len(summary['failed'])} failed")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
