"""Batch refresh: one failing source must not cancel the successful ones."""

from __future__ import annotations

import pytest

from app import ingest, refresh_all
from app.adapters import ADAPTERS
from app.ingest import latest_vintage, list_vintages, read_meta


def test_dry_run_touches_nothing(tmp_path):
    before = {d: list_vintages(d) for d in ADAPTERS}
    summary = refresh_all.refresh_many(["labour_force", "cpi_yoy"], dry_run=True)
    assert summary["ok"]
    assert summary["dry_run"]
    assert summary["new_vintages"] == []
    assert {d: list_vintages(d) for d in ADAPTERS} == before


def test_unknown_dataset_is_rejected_before_any_network_call():
    summary = refresh_all.refresh_many(["labour_force", "not_a_dataset"])
    assert summary["ok"] is False
    assert "not_a_dataset" in summary["error"]
    assert summary["results"] == []


def test_one_failed_source_does_not_cancel_the_others(monkeypatch):
    """The whole point of the batch runner. Nineteen good downloads must not be
    thrown away because the twentieth timed out."""
    good, bad = "labour_force", "cpi_yoy"

    def fake_refresh(dataset_id, root=None):
        if dataset_id == bad:
            return {"ok": False, "dataset_id": dataset_id,
                    "error": "network unavailable: ConnectError: boom"}
        return {"ok": True, "dataset_id": dataset_id, "unchanged": True,
                "new_vintage": None, "message": "bytes identical"}

    monkeypatch.setattr(refresh_all, "refresh", fake_refresh)
    summary = refresh_all.refresh_many([good, bad])

    assert summary["ok"] is False
    assert summary["failed"] == [bad]
    assert summary["unchanged"] == [good]
    assert summary["attempted"] == 2


def test_an_unexpected_exception_is_contained_to_its_own_dataset(monkeypatch):
    def explode(dataset_id, root=None):
        if dataset_id == "cpi_yoy":
            raise RuntimeError("kaboom")
        return {"ok": True, "dataset_id": dataset_id, "unchanged": True}

    monkeypatch.setattr(refresh_all, "refresh", explode)
    summary = refresh_all.refresh_many(["labour_force", "cpi_yoy"])
    assert summary["failed"] == ["cpi_yoy"]
    assert summary["unchanged"] == ["labour_force"]
    assert "kaboom" in summary["results"][1]["error"]


def test_no_new_vintage_means_no_index_rebuild(monkeypatch):
    """Rebuilding the read index when nothing changed is wasted work, and worse,
    it would make an unchanged run look like a change."""
    monkeypatch.setattr(
        refresh_all, "refresh",
        lambda dataset_id, root=None: {
            "ok": True, "dataset_id": dataset_id, "unchanged": True,
        },
    )
    summary = refresh_all.refresh_many(["labour_force"])
    assert "contracts" not in summary


def test_committed_vintages_are_read_only_on_disk():
    """The batch runner writes new vintages; it must never be able to alter one
    that already exists."""
    import os
    import stat

    for dataset_id in ("labour_force", "household_income", "tourism_by_region"):
        vintage = latest_vintage(dataset_id)
        path = ingest.VINTAGE_ROOT / dataset_id / vintage / "raw.xlsx"
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert not mode & stat.S_IWUSR, f"{path} is writable"


def test_every_new_vintage_records_its_provenance():
    for dataset_id in ("earnings_quarterly", "population", "gender_pay_gap"):
        meta = read_meta(dataset_id, latest_vintage(dataset_id))
        assert meta["source_url"].startswith("https://geostat.ge/")
        assert meta["http_status"] == 200
        assert meta["byte_size"] > 0
        assert len(meta["sha256"]) == 64
        assert meta["row_count"] > 0
        assert meta["note"], "a dataset without a caveat has not been read"
