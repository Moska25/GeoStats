"""Contracts must pass on clean data and fail on the defect they target.

The second half of that sentence is the one that matters: a check that has
never been seen to fail is not a check.
"""

from __future__ import annotations

import pytest

from app.contracts import (
    CONTRACTS_BY_CODE, KNOWN_FAILURES, known_failure, pass_rate, run_contracts,
)
from app.faults import FAULTS, FAULTS_BY_ID
from app.ingest import all_datasets, latest_vintage, list_vintages, read_rows
from app.pxweb import read_snapshot


def _api_rows(dataset_id):
    """The committed PX-Web snapshot, so the suite stays offline."""
    found = read_snapshot(dataset_id)
    return found[0] if found else None

CLEAN_DATASET = "earnings_annual"


@pytest.fixture(scope="module")
def clean_rows():
    return read_rows(CLEAN_DATASET, latest_vintage(CLEAN_DATASET))


@pytest.fixture(scope="module")
def cpi_rows():
    return read_rows("cpi_2010_base", latest_vintage("cpi_2010_base"))


def _result(results, code):
    return next(r for r in results if r.code == code)


# -- clean data ------------------------------------------------------------

def test_every_committed_vintage_only_fails_checks_that_are_documented(cpi_rows):
    """A red check is allowed only if `KNOWN_FAILURES` explains why.

    Every entry there is a real limitation of the published statistics - the
    CPI starting five years after the wage series, a survey suspended through
    the pandemic - and the alternative to failing is tuning the check until the
    page goes green, which would hide the limitation instead of stating it.
    Anything failing that is *not* listed is a regression and fails this test.
    """
    for dataset_id in all_datasets():
        for vintage_id in list_vintages(dataset_id):
            rows = read_rows(dataset_id, vintage_id)
            results = run_contracts(rows, dataset_id=dataset_id, cpi_rows=cpi_rows)
            failed = {r.code for r in results if not r.passed}
            undocumented = {
                code for code in failed if not known_failure(dataset_id, code)
            }
            assert not undocumented, (
                f"{dataset_id}/{vintage_id} failed {sorted(undocumented)} with "
                "no entry in KNOWN_FAILURES explaining why"
            )


def test_every_documented_failure_still_actually_fails():
    """Guard the other direction: a stale entry in `KNOWN_FAILURES` is a licence
    for a genuine regression to hide behind an explanation that no longer
    applies."""
    cpi = read_rows("cpi_2010_base", latest_vintage("cpi_2010_base"))
    still_failing = set()
    for dataset_id in all_datasets():
        vintage_id = latest_vintage(dataset_id)
        if not vintage_id:
            continue
        results = run_contracts(
            read_rows(dataset_id, vintage_id),
            dataset_id=dataset_id, cpi_rows=cpi,
        )
        still_failing |= {
            (dataset_id, r.code) for r in results if not r.passed
        }
    stale = set(KNOWN_FAILURES) - still_failing
    assert not stale, f"KNOWN_FAILURES documents checks that now pass: {stale}"


def test_clean_data_passes_the_currency_era_contract(clean_rows):
    result = _result(run_contracts(clean_rows, dataset_id=CLEAN_DATASET), "CURRENCY_ERA")
    assert result.passed
    assert "RUB" in result.message and "GEL" in result.message


def test_clean_data_has_no_duplicate_keys(clean_rows):
    assert _result(run_contracts(clean_rows), "KEY_UNIQUE").passed


def test_pass_rate_is_a_fraction(clean_rows):
    results = run_contracts(clean_rows, dataset_id=CLEAN_DATASET)
    assert 0.0 <= pass_rate(results) <= 1.0
    assert pass_rate([]) == 0.0


def test_preliminary_contract_reports_the_flagged_period(clean_rows):
    result = _result(run_contracts(clean_rows), "PRELIM")
    assert result.passed
    assert "2025" in result.message


# -- each fault trips the contract it targets ------------------------------

@pytest.mark.parametrize("fault", FAULTS, ids=[f.fault_id for f in FAULTS])
def test_each_fault_trips_its_target_contract(fault, clean_rows, cpi_rows):
    dataset_id = fault.requires_dataset or CLEAN_DATASET
    rows = (clean_rows if dataset_id == CLEAN_DATASET
            else read_rows(dataset_id, latest_vintage(dataset_id)))
    mutated, description = fault.apply(rows)
    assert description, "a fault must describe what it did"

    api = _api_rows(dataset_id)
    before = run_contracts(
        rows, dataset_id=dataset_id, cpi_rows=cpi_rows, api_rows=api)
    after = run_contracts(
        mutated, dataset_id=dataset_id, cpi_rows=cpi_rows, prior_rows=rows,
        api_rows=api,
    )

    was_passing = _result(before, fault.targets).passed
    assert was_passing, f"{fault.targets} must pass before {fault.fault_id} is applied"

    now = _result(after, fault.targets)
    assert not now.passed, (
        f"{fault.fault_id} did not trip {fault.targets}: {now.message}"
    )
    assert now.message, "a failing contract must explain itself"


@pytest.mark.parametrize("fault", FAULTS, ids=[f.fault_id for f in FAULTS])
def test_each_fault_reports_offending_rows_or_gates_downstream(fault, clean_rows, cpi_rows):
    dataset_id = fault.requires_dataset or CLEAN_DATASET
    rows = (clean_rows if dataset_id == CLEAN_DATASET
            else read_rows(dataset_id, latest_vintage(dataset_id)))
    mutated, _ = fault.apply(rows)
    after = run_contracts(
        mutated, dataset_id=dataset_id, cpi_rows=cpi_rows, prior_rows=rows,
        api_rows=_api_rows(dataset_id),
    )
    result = _result(after, fault.targets)
    assert result.offenders, f"{fault.targets} failed without naming any row"


def test_schema_failure_gates_downstream_checks_instead_of_crashing(clean_rows):
    mutated, _ = FAULTS_BY_ID["rename_column"].apply(clean_rows)
    results = run_contracts(mutated, dataset_id=CLEAN_DATASET)
    assert not _result(results, "SCHEMA").passed
    gated = [r for r in results if r.skipped]
    assert len(gated) == len(CONTRACTS_BY_CODE) - 1
    assert all("not evaluated" in r.message for r in gated)


def test_currency_era_fault_names_the_eras_it_found(clean_rows):
    mutated, _ = FAULTS_BY_ID["mislabel_era"].apply(clean_rows)
    result = _result(run_contracts(mutated), "CURRENCY_ERA")
    assert not result.passed
    assert "Rouble" in result.message


def test_coercing_gaps_to_zero_is_caught_by_parse_integrity(clean_rows):
    mutated, _ = FAULTS_BY_ID["coerce_missing"].apply(clean_rows)
    result = _result(run_contracts(mutated), "PARSE")
    assert not result.passed
    assert any("gap marker" in o["_problem"] for o in result.offenders)


def test_stripping_the_preliminary_marker_needs_the_previous_vintage_to_detect(clean_rows):
    """With no prior vintage the strip is invisible; with one it is caught.
    That is the argument for keeping vintages at all."""
    mutated, _ = FAULTS_BY_ID["strip_preliminary"].apply(clean_rows)
    without_history = _result(run_contracts(mutated), "PRELIM")
    with_history = _result(run_contracts(mutated, prior_rows=clean_rows), "PRELIM")
    assert without_history.passed
    assert not with_history.passed


def test_temporal_sanity_ignores_the_1993_currency_boundary(clean_rows):
    """1992 (Rouble) to 1993 (Coupon) is an 18x step, but across two units, so
    the temporal check must not fire on it."""
    result = _result(run_contracts(clean_rows), "TEMPORAL")
    assert result.passed
    assert result.checked > 0


# -- percentage indicators are bounded 0 to 100 ---------------------------

def test_a_rate_above_100_is_out_of_range_and_the_row_is_named():
    """An unemployment rate of 150% is what a ratio against the wrong
    denominator looks like. Every value in the row stays a plausible number;
    only the bound catches it."""
    rows = read_rows("labour_force", latest_vintage("labour_force"))
    clean = _result(run_contracts(rows, dataset_id="labour_force"), "RANGE")
    assert clean.passed

    mutated, description = FAULTS_BY_ID["impossible_rate"].apply(rows)
    assert "150" in description
    result = _result(run_contracts(mutated, dataset_id="labour_force"), "RANGE")
    assert not result.passed
    assert result.offenders
    offender = result.offenders[0]
    assert offender["value"] == 150.0
    assert offender["unit"] == "percent"
    assert "0.0..100.0" in offender["_problem"] or "100" in offender["_problem"]


def test_every_percentage_series_sits_inside_its_bounds():
    """Across every committed vintage, not just the one the fault targets."""
    for dataset_id in all_datasets():
        vintage_id = latest_vintage(dataset_id)
        if not vintage_id:
            continue
        for row in read_rows(dataset_id, vintage_id):
            if row["unit"] == "percent" and row["value"] is not None:
                assert 0.0 <= row["value"] <= 100.0, (
                    f"{dataset_id} {row['indicator_code']} {row['period']} "
                    f"= {row['value']}"
                )


# -- quarters ------------------------------------------------------------

def test_annual_and_quarterly_rows_do_not_collide_on_the_composite_key():
    """`2024` and `2024-Q1` are different periods of the same indicator. If the
    key folded them together, a quarterly series would silently overwrite the
    annual one it belongs to."""
    quarterly = read_rows("earnings_quarterly", latest_vintage("earnings_quarterly"))
    annual = read_rows("earnings_by_activity", latest_vintage("earnings_by_activity"))
    combined = quarterly + annual
    keys = [
        (r["dataset_id"], r["indicator_code"], r["breakdown_code"],
         r["period"], r["unit"])
        for r in combined
    ]
    assert len(keys) == len(set(keys))
    # the same indicator really does appear at both grains
    indicators = {r["indicator_code"] for r in quarterly}
    assert indicators & {r["indicator_code"] for r in annual}
    assert _result(run_contracts(combined), "KEY_UNIQUE").passed


def test_coverage_detects_a_missing_quarter():
    rows = read_rows("earnings_quarterly", latest_vintage("earnings_quarterly"))
    assert _result(run_contracts(rows, dataset_id="earnings_quarterly"), "COVERAGE").passed

    victim = "2018-Q3"
    holed = [r for r in rows if r["period"] != victim]
    assert len(holed) < len(rows), f"{victim} must exist to be removed"
    result = _result(run_contracts(holed, dataset_id="earnings_quarterly"), "COVERAGE")
    assert not result.passed
    assert any(victim in o["_problem"] for o in result.offenders)


def test_quarter_periods_are_canonical_whatever_the_sheet_wrote():
    """The workbook switches from `2007_I` to `2008 IV` partway across one
    header row. Both must land on the same canonical form."""
    from app.adapters import parse_period_header

    assert parse_period_header("2007_I") == ("2007-Q1", False)
    assert parse_period_header("2008 IV") == ("2008-Q4", False)
    assert parse_period_header("2024_III") == ("2024-Q3", False)
    assert parse_period_header("2024") == ("2024", False)
