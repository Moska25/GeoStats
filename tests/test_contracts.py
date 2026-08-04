"""Contracts must pass on clean data and fail on the defect they target.

The second half of that sentence is the one that matters: a check that has
never been seen to fail is not a check.
"""

from __future__ import annotations

import pytest

from app.contracts import CONTRACTS_BY_CODE, pass_rate, run_contracts
from app.faults import FAULTS, FAULTS_BY_ID
from app.ingest import all_datasets, latest_vintage, list_vintages, read_rows

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

def test_every_committed_vintage_passes_every_contract_except_the_known_join_gap(cpi_rows):
    """The JOIN contract genuinely fails for 1995-1999 because the CPI series
    starts in 2000. That is a real limitation, not a check to be tuned away."""
    for dataset_id in all_datasets():
        for vintage_id in list_vintages(dataset_id):
            rows = read_rows(dataset_id, vintage_id)
            results = run_contracts(rows, dataset_id=dataset_id, cpi_rows=cpi_rows)
            failed = {r.code for r in results if not r.passed}
            assert failed <= {"JOIN"}, (
                f"{dataset_id}/{vintage_id} failed {failed}"
            )


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
    mutated, description = fault.apply(clean_rows)
    assert description, "a fault must describe what it did"

    before = run_contracts(clean_rows, dataset_id=CLEAN_DATASET, cpi_rows=cpi_rows)
    after = run_contracts(
        mutated, dataset_id=CLEAN_DATASET, cpi_rows=cpi_rows, prior_rows=clean_rows
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
    mutated, _ = fault.apply(clean_rows)
    after = run_contracts(
        mutated, dataset_id=CLEAN_DATASET, cpi_rows=cpi_rows, prior_rows=clean_rows
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
