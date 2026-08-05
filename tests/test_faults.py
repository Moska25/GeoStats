"""The fault lab end to end, including its own safety guarantee."""

from __future__ import annotations

import pytest

from app.faults import FAULTS, FAULTS_BY_ID, defect_report, inject
from app.ingest import latest_vintage, read_rows

DATASET = "earnings_annual"


@pytest.fixture(scope="module")
def vintage_id():
    return latest_vintage(DATASET)


@pytest.fixture(scope="module")
def cpi_rows():
    return read_rows("cpi_2010_base", latest_vintage("cpi_2010_base"))


def _target(fault):
    """Dataset this fault needs, and the vintage to inject it into."""
    dataset_id = fault.requires_dataset or DATASET
    return dataset_id, latest_vintage(dataset_id)


@pytest.mark.parametrize("fault", FAULTS, ids=[f.fault_id for f in FAULTS])
def test_injection_is_caught_and_leaves_the_vintage_intact(fault, vintage_id, cpi_rows):
    dataset_id, target_vintage = _target(fault)
    result = inject(dataset_id, target_vintage, fault.fault_id, cpi_rows=cpi_rows)
    assert result["caught"], f"{fault.fault_id} was not caught by any contract"
    assert result["caught_by_target"], (
        f"{fault.fault_id} was caught, but not by {fault.targets}"
    )
    assert result["vintage_unchanged"] is True
    assert result["original_sha256"] == result["original_sha256_after_run"]


@pytest.mark.parametrize("fault", FAULTS, ids=[f.fault_id for f in FAULTS])
def test_defect_report_is_actionable(fault, vintage_id, cpi_rows):
    dataset_id, target_vintage = _target(fault)
    report = defect_report(
        inject(dataset_id, target_vintage, fault.fault_id, cpi_rows=cpi_rows)
    )
    assert fault.targets in report
    assert "Immutability check" in report
    assert "vintage untouched                : True" in report


def test_the_lab_writes_only_into_the_cache_directory(vintage_id):
    result = inject(DATASET, vintage_id, "duplicate_year")
    assert result["copy_path"].startswith("data/cache/lab")


def test_unknown_fault_is_rejected(vintage_id):
    with pytest.raises(KeyError):
        inject(DATASET, vintage_id, "not_a_fault")


def test_faults_do_not_mutate_the_row_list_they_are_given(vintage_id):
    rows = read_rows(DATASET, vintage_id)
    snapshot = [dict(r) for r in rows]
    for fault in FAULTS:
        fault.apply(rows)
    assert rows == snapshot, "a fault mutated its input instead of copying"


def test_duplicate_year_actually_adds_rows(vintage_id):
    rows = read_rows(DATASET, vintage_id)
    mutated, _ = FAULTS_BY_ID["duplicate_year"].apply(rows)
    assert len(mutated) > len(rows)


def test_drop_period_actually_removes_rows(vintage_id):
    rows = read_rows(DATASET, vintage_id)
    mutated, _ = FAULTS_BY_ID["drop_period"].apply(rows)
    assert len(mutated) < len(rows)


def test_shift_units_scales_exactly_one_period(vintage_id):
    rows = read_rows(DATASET, vintage_id)
    mutated, _ = FAULTS_BY_ID["shift_units"].apply(rows)
    changed = [
        (a, b) for a, b in zip(rows, mutated)
        if a["value"] != b["value"] and a["value"] is not None
    ]
    assert changed
    assert len({a["period"] for a, _ in changed}) == 1
    assert all(b["value"] == pytest.approx(a["value"] * 1000) for a, b in changed)


def test_every_contract_code_is_targeted_by_some_fault():
    from app.contracts import CONTRACTS

    targeted = {f.targets for f in FAULTS}
    codes = {c.code for c in CONTRACTS}
    untargeted = codes - targeted
    assert untargeted == {"JOIN"}, (
        "every contract except the cross-dataset join should have a fault; "
        f"untargeted: {untargeted}"
    )
