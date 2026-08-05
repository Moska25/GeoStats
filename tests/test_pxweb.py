"""The second source, and the contract that compares against it.

Every test here reads the committed snapshot in `data/pxweb/` rather than the
live API, for the same reason the rest of the suite reads committed vintages:
a test that depends on a remote service is testing the service.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from app import pxweb
from app.contracts import SOURCE_AGREEMENT_TOLERANCE, run_contracts
from app.ingest import latest_vintage, read_rows
from app.pxweb import PX_TABLES, list_snapshots, read_snapshot

DATASET = "labour_force_by_region"


@pytest.fixture(scope="module")
def api_rows():
    found = read_snapshot(DATASET)
    assert found, "no committed PX-Web snapshot"
    return found[0]


@pytest.fixture(scope="module")
def sheet_rows():
    return read_rows(DATASET, latest_vintage(DATASET))


def _result(results, code):
    return next(r for r in results if r.code == code)


# -- the snapshot is a real, frozen artefact -------------------------------

def test_a_snapshot_is_committed_for_every_mapped_table():
    for dataset_id in PX_TABLES:
        assert list_snapshots(dataset_id), f"{dataset_id} has no snapshot"


def test_the_snapshot_records_its_own_provenance():
    _rows, meta = read_snapshot(DATASET)
    assert meta["source"] == "pxweb"
    assert meta["source_url"].startswith("https://pc-axis.geostat.ge/")
    assert meta["http_status"] == 200
    assert len(meta["sha256"]) == 64
    assert meta["byte_size"] > 0
    assert meta["row_count"] > 0
    assert meta["note"]


def test_the_snapshot_is_read_only_on_disk():
    """Like a vintage: it is a record of what a source served at a moment."""
    stamps = list_snapshots(DATASET)
    path = pxweb.SNAPSHOT_ROOT / DATASET / f"{stamps[-1]}.json"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert not mode & stat.S_IWUSR, f"{path} is writable"


def test_the_snapshot_carries_both_halves_of_the_api_response():
    """PX-Web splits the labels and the values across two requests. A data
    response whose labels came from a different fetch is not a record."""
    stamps = list_snapshots(DATASET)
    path = pxweb.SNAPSHOT_ROOT / DATASET / f"{stamps[-1]}.json"
    document = json.loads(path.read_text())
    assert "metadata" in document["payload"]
    assert "data" in document["payload"]
    assert document["payload"]["metadata"]["variables"]


# -- parsing ---------------------------------------------------------------

def test_the_api_parses_into_the_identical_long_format(api_rows, sheet_rows):
    assert api_rows
    fields = set(sheet_rows[0])
    for row in api_rows[:50]:
        assert fields <= set(row) | {"vintage_id"}, "schema differs from the sheet"
        assert row["dataset_id"] == DATASET
        assert row["period"]
        assert row["unit"] in {"percent", "thousand_persons"}


def test_places_resolve_through_the_same_registry(api_rows):
    """Both sources land on `region.adjara`, which is the only reason they can
    be compared at all."""
    codes = {r["breakdown_code"] for r in api_rows}
    assert "region.adjara" in codes
    assert "country.georgia" in codes
    assert all(c.startswith(("region.", "country.", "aggregate.")) for c in codes)


def test_the_two_sources_share_a_substantial_number_of_cells(api_rows, sheet_rows):
    """A contract that compares nothing passes trivially. This pins the size of
    the actual overlap so a mapping regression shows up as a smaller number."""
    def index(rows):
        return {
            (r["indicator_code"], r["breakdown_code"], r["period"])
            for r in rows if r.get("value") is not None
        }

    shared = index(api_rows) & index(sheet_rows)
    assert len(shared) > 1900, f"only {len(shared)} cells overlap"


def test_measure_aliases_are_needed_and_applied(api_rows):
    """The API writes 'Labour force, total' and 'labor'; the sheet writes
    'Labour force' and 'labour'. Without the mapping ~800 cells stop joining."""
    codes = {r["indicator_code"] for r in api_rows}
    assert "labour_force" in codes
    assert "labour_force_total" not in codes
    assert "population_outside_the_labour_force" in codes
    assert "population_outside_labor_force" not in codes


# -- the contract ----------------------------------------------------------

def test_the_two_sources_agree(api_rows, sheet_rows):
    result = _result(
        run_contracts(sheet_rows, dataset_id=DATASET, api_rows=api_rows),
        "SOURCE_AGREEMENT",
    )
    assert result.passed, result.message
    assert result.checked > 1900


def test_the_largest_real_disagreement_is_pure_rounding(api_rows, sheet_rows):
    """The tolerance is derived, not tuned: PX-Web rounds to one decimal, so
    half of that is the largest gap rounding alone can produce, and the worst
    observed gap should sit right at it rather than comfortably under."""
    def index(rows):
        return {
            (r["indicator_code"], r["breakdown_code"], r["period"]): r["value"]
            for r in rows if r.get("value") is not None
        }

    sheet, api = index(sheet_rows), index(api_rows)
    gaps = [abs(sheet[k] - api[k]) for k in sheet.keys() & api.keys()]
    assert max(gaps) <= SOURCE_AGREEMENT_TOLERANCE
    assert max(gaps) > SOURCE_AGREEMENT_TOLERANCE * 0.9, (
        "the worst gap is far below the tolerance, which suggests the "
        "tolerance was set too loosely to catch anything"
    )


def test_a_drift_too_small_for_any_magnitude_check_is_caught(api_rows, sheet_rows):
    """The point of a second source: a 2% scale error is in range, is not a 10x
    step, and is invisible to every check that looks at one source."""
    from app.faults import FAULTS_BY_ID

    mutated, description = FAULTS_BY_ID["drift_from_source"].apply(sheet_rows)
    assert "1.02" in description

    after = run_contracts(mutated, dataset_id=DATASET, api_rows=api_rows)
    assert _result(after, "RANGE").passed, "the drift must stay in range"
    assert _result(after, "TEMPORAL").passed, "the drift must not look like a step"
    agreement = _result(after, "SOURCE_AGREEMENT")
    assert not agreement.passed
    assert agreement.offenders
    assert "against API" in agreement.offenders[0]["_problem"]


def test_the_contract_abstains_rather_than_passing_when_there_is_no_second_source(
    sheet_rows,
):
    result = _result(
        run_contracts(sheet_rows, dataset_id=DATASET), "SOURCE_AGREEMENT")
    assert result.passed
    assert result.checked == 0
    assert "not exercised" in result.message


def test_no_overlap_is_a_failure_not_a_pass(sheet_rows):
    """Comparing zero cells and reporting success is the failure mode this
    check most needs to avoid."""
    unrelated = [
        {**r, "indicator_code": "nothing_matches_this"} for r in sheet_rows[:20]
    ]
    result = _result(
        run_contracts(sheet_rows, dataset_id=DATASET, api_rows=unrelated),
        "SOURCE_AGREEMENT",
    )
    assert not result.passed
    assert "share no comparable cell" in result.message


# -- the seeder uses it ----------------------------------------------------

def test_the_running_application_records_the_agreement():
    from app import db

    conn = db.connect()
    row = conn.execute(
        """SELECT passed, checked, message FROM contract_runs
            WHERE code = 'SOURCE_AGREEMENT' AND dataset_id = ?
              AND vintage_id = (SELECT vintage_id FROM vintages
                                 WHERE dataset_id = ? AND is_latest = 1)""",
        (DATASET, DATASET),
    ).fetchone()
    conn.close()
    assert row is not None, "the seeder did not run SOURCE_AGREEMENT"
    assert row["passed"]
    assert row["checked"] > 1900
    assert "PX-Web" in row["message"]
