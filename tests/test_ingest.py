"""Vintage immutability, diffing and offline operation."""

from __future__ import annotations

import hashlib
import json

import pytest

from app.adapters import ADAPTERS
from app.faults import inject
from app.ingest import (
    VINTAGE_ROOT, VintageExists, all_datasets, diff_rows, diff_vintages,
    latest_vintage, list_vintages, read_meta, read_raw, read_rows,
    vintage_history, write_vintage,
)

REGION = "earnings_by_region"


def test_every_dataset_has_a_committed_vintage():
    for dataset_id in all_datasets():
        assert list_vintages(dataset_id), f"{dataset_id} has no vintage on disk"


def test_meta_checksum_matches_the_committed_bytes():
    for dataset_id in all_datasets():
        vintage_id = latest_vintage(dataset_id)
        meta = read_meta(dataset_id, vintage_id)
        raw = read_raw(dataset_id, vintage_id)
        assert hashlib.sha256(raw).hexdigest() == meta["sha256"]
        assert len(raw) == meta["byte_size"]
        assert meta["byte_size"] > 0, (
            "a zero-byte body is what Geostat returns without a browser UA"
        )


def test_rows_json_matches_the_row_count_in_meta():
    for dataset_id in all_datasets():
        vintage_id = latest_vintage(dataset_id)
        assert len(read_rows(dataset_id, vintage_id)) == \
            read_meta(dataset_id, vintage_id)["row_count"]


def test_every_row_is_stamped_with_its_vintage_id():
    for dataset_id in all_datasets():
        vintage_id = latest_vintage(dataset_id)
        rows = read_rows(dataset_id, vintage_id)
        assert all(r["vintage_id"] == vintage_id for r in rows)


def test_committed_vintage_files_are_read_only_on_disk():
    for dataset_id in all_datasets():
        vintage_id = latest_vintage(dataset_id)
        for name in ("raw.xlsx", "meta.json", "rows.json"):
            path = VINTAGE_ROOT / dataset_id / vintage_id / name
            assert not (path.stat().st_mode & 0o222), f"{path} is writable"


def test_writing_over_an_existing_vintage_is_refused(tmp_path):
    adapter = ADAPTERS["earnings_annual"]
    data = read_raw("earnings_annual", latest_vintage("earnings_annual"))
    write_vintage(adapter, data, 200, root=tmp_path, vintage_id="fixed")
    with pytest.raises(VintageExists):
        write_vintage(adapter, data, 200, root=tmp_path, vintage_id="fixed")


def test_write_vintage_produces_all_three_artefacts(tmp_path):
    adapter = ADAPTERS["median_earnings"]
    data = read_raw("median_earnings", latest_vintage("median_earnings"))
    meta = write_vintage(adapter, data, 200, root=tmp_path, vintage_id="v1")
    target = tmp_path / "median_earnings" / "v1"
    assert (target / "raw.xlsx").read_bytes() == data
    assert json.loads((target / "meta.json").read_text())["sha256"] == meta["sha256"]
    assert len(json.loads((target / "rows.json").read_text())) == meta["row_count"]


# -- real vintage history --------------------------------------------------

def test_region_dataset_has_a_multi_release_history():
    """Three genuinely different published releases of the same series."""
    vintages = list_vintages(REGION)
    assert len(vintages) >= 3
    digests = {read_meta(REGION, v)["sha256"] for v in vintages}
    assert len(digests) == len(vintages), "each vintage must be distinct bytes"


def test_successive_region_releases_added_years_without_revising_old_ones():
    vintages = list_vintages(REGION)
    diff = diff_vintages(REGION, vintages[0], vintages[1])
    assert diff["added"], "the later release must add periods"
    assert diff["changed"] == [], (
        "Geostat did not revise any previously published regional figure "
        "between these two releases - confirming that is as useful as "
        "catching a revision"
    )
    assert not diff["bytes_identical"]


def test_vintage_history_is_newest_first_and_diffs_against_the_predecessor():
    history = vintage_history(REGION)
    assert len(history) >= 3
    assert history[0]["vintage_id"] > history[-1]["vintage_id"]
    assert history[-1]["diff"] is None, "the oldest vintage has nothing to diff"
    assert history[0]["diff"] is not None


def test_diff_rows_detects_a_changed_value():
    old = [{"indicator_code": "i", "breakdown_code": "b", "period": "2024",
            "unit": "GEL", "value": 100.0, "is_preliminary": False}]
    new = [dict(old[0], value=110.0)]
    diff = diff_rows(old, new)
    assert len(diff["changed"]) == 1
    assert diff["changed"][0]["old_value"] == 100.0
    assert diff["changed"][0]["new_value"] == 110.0
    assert diff["changed"][0]["delta"] == pytest.approx(10.0)


def test_diff_rows_detects_added_and_removed_series():
    old = [{"indicator_code": "i", "breakdown_code": "a", "period": "2023",
            "unit": "GEL", "value": 1.0}]
    new = [{"indicator_code": "i", "breakdown_code": "b", "period": "2023",
            "unit": "GEL", "value": 2.0}]
    diff = diff_rows(old, new)
    assert len(diff["added"]) == 1 and len(diff["removed"]) == 1


def test_diff_rows_detects_a_preliminary_flag_change():
    old = [{"indicator_code": "i", "breakdown_code": "b", "period": "2025",
            "unit": "GEL", "value": 1.0, "is_preliminary": True}]
    new = [dict(old[0], is_preliminary=False)]
    assert len(diff_rows(old, new)["preliminary_flag_changes"]) == 1


# -- immutability under fault injection ------------------------------------

def test_fault_injection_cannot_mutate_a_committed_vintage():
    dataset_id, vintage_id = "earnings_annual", latest_vintage("earnings_annual")
    before = hashlib.sha256(read_raw(dataset_id, vintage_id)).hexdigest()
    rows_before = read_rows(dataset_id, vintage_id)
    for fault_id in ("duplicate_year", "shift_units", "coerce_missing",
                     "mislabel_era", "rename_column"):
        result = inject(dataset_id, vintage_id, fault_id)
        assert result["vintage_unchanged"] is True
    after = hashlib.sha256(read_raw(dataset_id, vintage_id)).hexdigest()
    assert after == before
    assert read_rows(dataset_id, vintage_id) == rows_before


# -- refresh behaviour, exercised without touching the network -------------

def test_refresh_writes_no_new_vintage_when_the_bytes_are_identical(monkeypatch):
    from app import ingest

    dataset_id = "median_earnings"
    existing = latest_vintage(dataset_id)
    data = read_raw(dataset_id, existing)
    monkeypatch.setattr(
        ADAPTERS[dataset_id], "download", lambda *a, **k: (data, 200), raising=False
    )
    before = list_vintages(dataset_id)
    result = ingest.refresh(dataset_id)
    assert result["ok"] and result["unchanged"] is True
    assert result["new_vintage"] is None
    assert list_vintages(dataset_id) == before


def test_refresh_fails_gracefully_and_leaves_vintages_untouched(monkeypatch):
    from app import ingest

    dataset_id = "median_earnings"

    def explode(*a, **k):
        raise OSError("network is unreachable")

    monkeypatch.setattr(ADAPTERS[dataset_id], "download", explode, raising=False)
    before = list_vintages(dataset_id)
    result = ingest.refresh(dataset_id)
    assert result["ok"] is False
    assert "network unavailable" in result["error"]
    assert list_vintages(dataset_id) == before


def test_refresh_treats_an_empty_body_as_a_failure(monkeypatch):
    """Geostat answers 200 with zero bytes when the User-Agent is missing.
    Recording that as a valid empty release would wipe the series."""
    from app import ingest

    dataset_id = "median_earnings"
    monkeypatch.setattr(
        ADAPTERS[dataset_id], "download", lambda *a, **k: (b"", 200), raising=False
    )
    before = list_vintages(dataset_id)
    result = ingest.refresh(dataset_id)
    assert result["ok"] is False
    assert "0 bytes" in result["error"]
    assert list_vintages(dataset_id) == before


def test_refresh_rejects_an_unknown_dataset():
    from app import ingest

    assert ingest.refresh("not_a_dataset")["ok"] is False


def test_offline_operation_needs_no_network():
    """Nothing in the read path imports httpx or opens a socket: the whole app
    runs from the committed vintages."""
    import socket

    original = socket.socket

    def forbidden(*args, **kwargs):
        raise AssertionError("the read path must not open a socket")

    socket.socket = forbidden
    try:
        for dataset_id in all_datasets():
            assert read_rows(dataset_id, latest_vintage(dataset_id))
    finally:
        socket.socket = original
