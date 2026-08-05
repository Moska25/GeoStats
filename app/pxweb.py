"""A second route to the same statistics: Geostat's PX-Web JSON API.

The spreadsheets are what Geostat puts on its website and what a person
downloads. The PX-Web database at <https://pc-axis.geostat.ge/PXWeb/> is a
separate publication of overlapping series, maintained separately. Two
independent routes to the same number is the strongest check available here:
the `SOURCE_AGREEMENT` contract joins them and fails when they disagree, which
catches a parser reading the wrong column just as surely as it catches an
upstream inconsistency - and cannot be fooled by a bug that is symmetrical
across both, because there is no shared code between the two paths.

Notes on this particular installation, learned by probing it:

* `json-stat2` is advertised but returns 404. The older `json` format works.
* A query carrying a `selection` also returns 404. An empty query returns the
  whole table, so the whole table is what gets fetched and the filtering is
  done here. At 134 KB for the labour force table that is cheaper than fighting
  the query API.
* Values arrive as strings, with `".."` for a suppressed cell, and rounded to
  one decimal - the spreadsheets carry full precision. That rounding is why
  `SOURCE_AGREEMENT` compares with a tolerance rather than for equality, and
  the tolerance is set from the rounding, not tuned until it passed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import geography
from .adapters import USER_AGENT, Row, measure_code, parse_number
from .ingest import REPO_ROOT

PXWEB_ROOT = "https://pc-axis.geostat.ge/PXWeb/api/v1/en/Database"
PXWEB_BROWSE = "https://pc-axis.geostat.ge/PXWeb/pxweb/en/Database"

# PX-Web publishes one decimal place; the spreadsheets publish full precision.
# Half of the last published digit is the largest disagreement rounding alone
# can produce, so anything above it is a real difference between the sources.
ROUNDING_TOLERANCE = 0.05

# The two publications name three measures differently. These are the same
# measure under a different label, not a judgement call: "Labour force, total"
# and "Labour force" are one row of one survey, and "labor" versus "labour" is
# a spelling. Without the mapping the contract would silently compare 800 fewer
# cells and look like it had done more work than it had.
MEASURE_ALIASES = {
    "labour_force_total": "labour_force",
    "population_outside_labor_force": "population_outside_the_labour_force",
    "population_outside_labour_force": "population_outside_the_labour_force",
}


@dataclass
class PxTable:
    """One PX-Web table, and how its axes map onto this project's schema."""

    dataset_id: str            # the spreadsheet dataset this cross-checks
    path: str                  # under PXWEB_ROOT
    title: str
    measure_axis: str          # the variable holding the measure
    period_axis: str
    place_axis: str
    note: str = ""

    @property
    def url(self) -> str:
        return f"{PXWEB_ROOT}/{self.path}"

    @property
    def browse_url(self) -> str:
        return f"{PXWEB_BROWSE}/{self.path}"

    def download(self, timeout: float = 60.0) -> tuple[bytes, int]:
        """Fetch the table as one document.

        Two requests, because PX-Web splits what is needed to read a cell:
        `GET` returns the variable definitions (which label each positional
        code means) and `POST` returns the codes and values. Neither is usable
        alone, so both are captured together - a data response whose labels
        came from a different fetch is not a record of anything.
        """
        import json

        import httpx

        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            meta = client.get(self.url, headers=headers)
            if meta.status_code != 200:
                return meta.content, meta.status_code
            data = client.post(
                self.url,
                json={"query": [], "response": {"format": "json"}},
                headers=headers,
            )
            if data.status_code != 200:
                return data.content, data.status_code

        combined = {
            "metadata": meta.json(),
            "data": data.json(),
            "source_url": self.url,
        }
        return json.dumps(combined, ensure_ascii=False).encode("utf-8"), 200

    def parse(self, data: bytes) -> list[Row]:
        import json

        document = json.loads(data)
        payload = document["data"]
        variables = {v["code"]: v for v in document["metadata"]["variables"]}

        # PX-Web keys are positional codes ("0", "1", ...) into each variable's
        # own value list, and that list is only in the metadata response.
        dimensions = [c for c in payload["columns"] if c["type"] == "d"]
        order = [c["code"] for c in dimensions]
        texts = {
            code: variables.get(code, {}).get("valueTexts", [])
            for code in order
        }

        rows: list[Row] = []
        for record in payload["data"]:
            keyed = dict(zip(order, record["key"]))
            measure = _label(texts, self.measure_axis, keyed)
            period = _label(texts, self.period_axis, keyed)
            place = _label(texts, self.place_axis, keyed)
            if measure is None or period is None or place is None:
                continue
            try:
                code, name = geography.resolve(place)
            except geography.UnknownPlace:
                # A place the registry does not know is skipped rather than
                # invented; the spreadsheet side is the authority on coverage
                # and the contract compares only the cells both sources have.
                continue
            value, status, raw = parse_number(record["values"][0])
            unit = ("percent" if measure.rstrip(" .").endswith("percentage")
                    else "thousand_persons")
            code_for_measure = measure_code(measure)
            rows.append(Row(
                dataset_id=self.dataset_id,
                indicator_code=MEASURE_ALIASES.get(
                    code_for_measure, code_for_measure),
                indicator_label=measure,
                breakdown_code=code, breakdown_label=name,
                period=period, unit=unit, value=value, raw=raw, status=status,
            ))
        return rows


def _label(texts: dict, axis: str, keyed: dict) -> str | None:
    """The printed label for the code this record carries on `axis`."""
    index = keyed.get(axis)
    values = texts.get(axis) or []
    if index is None:
        return None
    try:
        return values[int(index)]
    except (ValueError, IndexError):
        return None


PX_TABLES: dict[str, PxTable] = {
    t.dataset_id: t for t in [
        PxTable(
            dataset_id="labour_force_by_region",
            path="Social Statistics/Labour/LFS_by_regions.px",
            title="Labour Force Indicators by Years and Regions",
            measure_axis="Economic Status",
            period_axis="Years",
            place_axis="Regions",
            note=(
                "The same labour force survey as the spreadsheet, published "
                "separately in the PX-Web database. Values arrive rounded to "
                "one decimal place."
            ),
        ),
    ]
}


def cross_check_rows(dataset_id: str) -> list[dict] | None:
    """Fetch the API's version of a dataset live, or `None` if no table maps."""
    table = PX_TABLES.get(dataset_id)
    if table is None:
        return None
    data, status = table.download()
    if status != 200 or not data:
        raise RuntimeError(f"PX-Web returned HTTP {status} for {table.path}")
    return [r.to_dict() for r in table.parse(data)]


# --------------------------------------------------------------------------
# committed snapshots
# --------------------------------------------------------------------------

# The API reading is captured to disk for the same reason a spreadsheet
# retrieval is: so the check runs offline, so the test suite is deterministic,
# and so "the two sources agreed" is a claim about specific bytes rather than
# about whatever the API happens to serve today. Snapshots live apart from
# `data/vintages/` because they are not a vintage of a dataset - they are a
# second reading of one, kept to be disagreed with.
SNAPSHOT_ROOT = REPO_ROOT / "data" / "pxweb"


def write_snapshot(dataset_id: str, *, root: Path | None = None) -> dict:
    """Fetch the API table and freeze it, with its provenance."""
    import hashlib
    import json
    import os
    import stat
    from datetime import datetime, timezone

    table = PX_TABLES.get(dataset_id)
    if table is None:
        raise KeyError(f"no PX-Web table maps to {dataset_id}")

    data, status = table.download()
    if status != 200 or not data:
        raise RuntimeError(f"PX-Web returned HTTP {status} for {table.path}")
    rows = table.parse(data)

    root = root or SNAPSHOT_ROOT
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    target = root / dataset_id
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{stamp}.json"
    if path.exists():
        raise FileExistsError(f"snapshot already exists: {path}")

    meta = {
        "dataset_id": dataset_id,
        "captured_at": stamp,
        "source": "pxweb",
        "source_url": table.url,
        "browse_url": table.browse_url,
        "table_title": table.title,
        "http_status": status,
        "byte_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "row_count": len(rows),
        "note": table.note,
    }
    path.write_text(
        json.dumps({"meta": meta, "payload": json.loads(data)},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return meta


def list_snapshots(dataset_id: str, root: Path | None = None) -> list[str]:
    root = root or SNAPSHOT_ROOT
    base = root / dataset_id
    if not base.is_dir():
        return []
    return sorted(p.stem for p in base.glob("*.json"))


def read_snapshot(
    dataset_id: str, stamp: str | None = None, root: Path | None = None
) -> tuple[list[dict], dict] | None:
    """The committed API reading of a dataset as rows, plus its provenance."""
    import json

    root = root or SNAPSHOT_ROOT
    stamps = list_snapshots(dataset_id, root)
    if not stamps:
        return None
    stamp = stamp or stamps[-1]
    document = json.loads((root / dataset_id / f"{stamp}.json").read_text())
    table = PX_TABLES[dataset_id]
    rows = table.parse(
        json.dumps(document["payload"], ensure_ascii=False).encode("utf-8")
    )
    return [r.to_dict() for r in rows], document["meta"]


def snapshot_rows_by_dataset(root: Path | None = None) -> dict[str, list[dict]]:
    """Every committed API reading, keyed by dataset, for the seeder."""
    out = {}
    for dataset_id in PX_TABLES:
        found = read_snapshot(dataset_id, root=root)
        if found:
            out[dataset_id] = found[0]
    return out
