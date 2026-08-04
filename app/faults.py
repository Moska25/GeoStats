"""Fault-injection lab.

Every fault is applied to a COPY of a committed vintage in data/cache/lab/,
never to the vintage itself. `inject` records the sha256 of the original raw
file before and after the run and reports whether they match, so the
immutability claim is verified on every single injection rather than asserted
in a README.

A contract you have never seen fail is a contract you have not tested. Each
fault below targets exactly one contract and is named for the real-world
mistake it imitates.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .contracts import run_contracts
from .ingest import (
    REPO_ROOT, copy_vintage_to, read_raw, read_rows, VINTAGE_ROOT, diff_rows,
)

LAB_DIR = REPO_ROOT / "data" / "cache" / "lab"


@dataclass
class Fault:
    fault_id: str
    name: str
    real_world: str          # the mistake this imitates
    targets: str             # contract code expected to catch it
    apply: Callable[[list[dict]], tuple[list[dict], str]]


# --------------------------------------------------------------------------
# mutations - each returns (rows, description of what it did)
# --------------------------------------------------------------------------

def _pick_period(rows: list[dict], prefer_last: bool = True) -> str | None:
    periods = sorted({r["period"] for r in rows if r.get("value") is not None})
    if not periods:
        return None
    return periods[-1] if prefer_last else periods[0]


def _duplicate_year(rows):
    period = _pick_period(rows)
    dupes = [copy.deepcopy(r) for r in rows if r["period"] == period]
    return rows + dupes, (
        f"appended a second copy of every row for period {period} "
        f"({len(dupes)} rows), as a re-run of an append-only loader would"
    )


def _shift_units(rows):
    period = _pick_period(rows)
    out = copy.deepcopy(rows)
    n = 0
    for r in out:
        if r["period"] == period and r.get("value") is not None:
            r["value"] *= 1000.0
            n += 1
    return out, (
        f"multiplied all {n} values in period {period} by 1000, as a thousands/"
        "units mix-up between two releases would"
    )


def _drop_period(rows):
    periods = sorted({r["period"] for r in rows})
    if len(periods) < 3:
        return rows, "not enough periods to drop one"
    victim = periods[len(periods) // 2]
    out = [r for r in rows if r["period"] != victim]
    return out, (
        f"deleted every row for period {victim} ({len(rows) - len(out)} rows), "
        "as a filter that silently excluded a sheet row would"
    )


def _rename_column(rows):
    out = copy.deepcopy(rows)
    for r in out:
        r["units"] = r.pop("unit")
    return out, (
        "renamed the 'unit' field to 'units' throughout, as an upstream schema "
        "change or a careless refactor would"
    )


def _decimal_comma(rows):
    period = _pick_period(rows)
    out = copy.deepcopy(rows)
    n = 0
    for r in out:
        if r["period"] == period and r.get("value") is not None:
            european = f"{r['value']:.2f}".replace(".", ",")
            # A naive reader treats the comma as a thousands separator.
            r["raw"] = european
            r["value"] = float(european.replace(",", ""))
            n += 1
    return out, (
        f"reformatted {n} values in period {period} as European decimals "
        f"(1970,77) and parsed the comma as a thousands separator"
    )


def _strip_preliminary(rows):
    out = copy.deepcopy(rows)
    n = 0
    for r in out:
        if r.get("is_preliminary"):
            r["is_preliminary"] = False
            n += 1
    if n == 0:
        return out, "this vintage has no preliminary rows to strip"
    return out, (
        f"cleared the preliminary flag on {n} rows while leaving the values "
        "untouched, as a tidy-up that dropped the '**' marker would"
    )


def _negative_wage(rows):
    out = copy.deepcopy(rows)
    for r in out:
        if r.get("value") is not None and r["value"] > 0:
            r["value"] = -abs(r["value"])
            return out, (
                f"negated a single value: {r['breakdown_label']} {r['period']} "
                f"is now {r['value']:.2f} {r.get('unit', '')}, as a sign error "
                "in a delta calculation would"
            )
    return out, "no positive value available to negate"


def _coerce_missing(rows):
    out = copy.deepcopy(rows)
    n = 0
    for r in out:
        if r.get("status") == "missing":
            r["value"] = 0.0
            r["status"] = "ok"
            n += 1
    if n == 0:
        return out, "this vintage has no published gaps to coerce"
    return out, (
        f"turned {n} published gaps ('…') into 0.0 and marked them parsed, as "
        "a pandas fillna(0) would"
    )


def _mislabel_era(rows):
    out = copy.deepcopy(rows)
    n = 0
    for r in out:
        if r.get("unit") in {"RUB", "KUP", "TKUP"}:
            r["unit"] = "GEL"
            n += 1
    if n == 0:
        return out, "this dataset has no pre-1995 rows to mislabel"
    return out, (
        f"relabelled {n} Rouble/Coupon rows as GEL, which is exactly what "
        "happens when the currency footnote is not read"
    )


FAULTS: list[Fault] = [
    Fault("duplicate_year", "Duplicate a year",
          "An append-only loader re-run after a partial failure.",
          "KEY_UNIQUE", _duplicate_year),
    Fault("shift_units", "Shift units by 1000x",
          "One release publishes thousands of lari, the next publishes lari.",
          "TEMPORAL", _shift_units),
    Fault("drop_period", "Drop a period",
          "A row filter that quietly excluded a sheet row.",
          "COVERAGE", _drop_period),
    Fault("rename_column", "Rename a required column",
          "Upstream renames a column, or a refactor renames a field.",
          "SCHEMA", _rename_column),
    Fault("decimal_comma", "Swap decimal point for comma",
          "A European-locale export read as if it were US-formatted.",
          "TEMPORAL", _decimal_comma),
    Fault("strip_preliminary", "Strip the preliminary marker",
          "A cleanup step that removed '**' as if it were formatting noise.",
          "PRELIM", _strip_preliminary),
    Fault("negative_wage", "Insert a negative wage",
          "A sign error in a year-on-year delta written back to the level.",
          "RANGE", _negative_wage),
    Fault("coerce_missing", "Coerce published gaps to zero",
          "df.fillna(0) applied to a column containing '…'.",
          "PARSE", _coerce_missing),
    Fault("mislabel_era", "Mislabel the currency era",
          "Treating 1970-1994 columns as lari because the footnote was skipped.",
          "CURRENCY_ERA", _mislabel_era),
]

FAULTS_BY_ID = {f.fault_id: f for f in FAULTS}


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------

def inject(
    dataset_id: str,
    vintage_id: str,
    fault_id: str,
    *,
    root: Path | None = None,
    lab_dir: Path | None = None,
    cpi_rows: list[dict] | None = None,
) -> dict:
    """Apply a fault to a copy of a vintage and report what the contracts did."""
    root = root or VINTAGE_ROOT
    lab_dir = lab_dir or LAB_DIR
    fault = FAULTS_BY_ID.get(fault_id)
    if fault is None:
        raise KeyError(f"unknown fault {fault_id!r}")

    sha_before = hashlib.sha256(read_raw(dataset_id, vintage_id, root)).hexdigest()
    original = read_rows(dataset_id, vintage_id, root)

    work = copy_vintage_to(dataset_id, vintage_id, lab_dir, root)
    mutated, description = fault.apply(original)
    (work / "rows.json").write_text(
        json.dumps(mutated, ensure_ascii=False) + "\n"
    )

    before = run_contracts(original, dataset_id=dataset_id, cpi_rows=cpi_rows)
    after = run_contracts(
        mutated, dataset_id=dataset_id, cpi_rows=cpi_rows, prior_rows=original
    )

    before_failed = {r.code for r in before if not r.passed}
    after_failed = {r.code for r in after if not r.passed and not r.skipped}
    newly_failed = sorted(after_failed - before_failed)
    gated = sorted(r.code for r in after if r.skipped)

    sha_after = hashlib.sha256(read_raw(dataset_id, vintage_id, root)).hexdigest()

    caught_by_target = fault.targets in newly_failed
    return {
        "dataset_id": dataset_id,
        "vintage_id": vintage_id,
        "fault_id": fault.fault_id,
        "fault_name": fault.name,
        "real_world": fault.real_world,
        "targets": fault.targets,
        "description": description,
        "caught": bool(newly_failed),
        "caught_by_target": caught_by_target,
        "newly_failed": newly_failed,
        "gated": gated,
        "already_failing": sorted(before_failed),
        "results_before": before,
        "results_after": after,
        "row_delta": len(mutated) - len(original),
        "diff": diff_rows(original, mutated),
        "copy_path": str(work.relative_to(REPO_ROOT)),
        "original_sha256": sha_before,
        "original_sha256_after_run": sha_after,
        "vintage_unchanged": sha_before == sha_after,
    }


def defect_report(result: dict) -> str:
    """The text an on-call engineer would want pasted into the ticket."""
    lines = [
        f"DEFECT  {result['dataset_id']} / {result['vintage_id']}",
        f"Injected fault : {result['fault_name']} ({result['fault_id']})",
        f"Imitates       : {result['real_world']}",
        f"Mutation       : {result['description']}",
        f"Rows changed   : {len(result['diff']['changed'])} changed, "
        f"{len(result['diff']['added'])} added, "
        f"{len(result['diff']['removed'])} removed",
        "",
        f"Expected to trip: {result['targets']}",
        f"Actually tripped: {', '.join(result['newly_failed']) or 'nothing'}",
        f"Gated downstream: {', '.join(result['gated']) or 'none'}",
        f"Outcome         : "
        + ("DETECTED" if result["caught_by_target"] else
           ("DETECTED BY ANOTHER CONTRACT" if result["caught"] else "MISSED")),
        "",
    ]
    for check in result["results_after"]:
        if check.code in result["newly_failed"]:
            lines.append(f"[{check.code}] {check.title}")
            lines.append(f"  {check.message}")
            for offender in check.offenders[:5]:
                bits = {
                    k: v for k, v in offender.items()
                    if k in ("breakdown_code", "period", "unit", "value", "_problem")
                }
                lines.append(f"    - {bits}")
            lines.append("")
    lines += [
        "Immutability check",
        f"  committed raw.xlsx sha256 before : {result['original_sha256']}",
        f"  committed raw.xlsx sha256 after  : {result['original_sha256_after_run']}",
        f"  vintage untouched                : {result['vintage_unchanged']}",
        f"  mutation written to              : {result['copy_path']}",
    ]
    return "\n".join(lines)
