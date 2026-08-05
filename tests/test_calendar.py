"""Release expectations, derived from the data rather than scraped.

Geostat's release calendar is rendered client-side and exposes no
machine-readable feed, so there is no date to fetch. These tests pin the thing
that *is* knowable: a dataset's cadence, taken from its own published periods,
and whether the period it should be covering has appeared.
"""

from __future__ import annotations

from datetime import date

import pytest

from app import calendar as release_calendar
from app import db
from app.adapters import ADAPTERS
from app.calendar import infer_cadence, next_period, next_release, scheduled_date


@pytest.fixture(scope="module")
def conn():
    connection = db.connect()
    db.bootstrap(connection)
    yield connection
    connection.close()


# -- cadence inference -----------------------------------------------------

@pytest.mark.parametrize("periods,expected", [
    (["2023", "2024", "2025"], "annual"),
    (["2024-Q1", "2024-Q2"], "quarterly"),
    (["2024-11", "2024-12"], "monthly"),
    ([], "irregular"),
    (["not-a-period"], "irregular"),
])
def test_cadence_is_inferred_from_the_periods_themselves(periods, expected):
    assert infer_cadence(periods) == expected


@pytest.mark.parametrize("period,cadence,expected", [
    ("2024", "annual", "2025"),
    ("2024-Q1", "quarterly", "2024-Q2"),
    ("2024-Q4", "quarterly", "2025-Q1"),
    ("2024-01", "monthly", "2024-02"),
    ("2024-12", "monthly", "2025-01"),
    ("2024", "quarterly", None),
    ("2024", "irregular", None),
])
def test_next_period_rolls_over_correctly(period, cadence, expected):
    assert next_period(period, cadence) == expected


# -- overdue detection -----------------------------------------------------

def test_a_finished_period_that_never_appeared_is_overdue():
    expectation = next_release("x", ["2023", "2024"], today=date(2026, 8, 5))
    assert expectation.overdue
    assert expectation.expected_period == "2025"
    assert "2025 expected" in expectation.summary


def test_a_period_still_in_progress_is_not_overdue():
    """A 2026 annual figure is not late in the middle of 2026. Flagging it
    would produce a permanent warning that means nothing."""
    expectation = next_release("x", ["2024", "2025"], today=date(2026, 8, 5))
    assert not expectation.overdue
    assert expectation.expected_period == "2026"
    assert "current" in expectation.summary


def test_quarterly_overdue_detection():
    late = next_release("x", ["2025-Q1", "2025-Q2"], today=date(2026, 8, 5))
    assert late.cadence == "quarterly"
    assert late.overdue
    fine = next_release("x", ["2026-Q1", "2026-Q2"], today=date(2026, 8, 5))
    assert not fine.overdue


def test_a_dataset_with_no_periods_yields_nothing():
    assert next_release("x", []) is None


def test_behind_by_counts_whole_periods():
    expectation = next_release("x", ["2022"], today=date(2026, 8, 5))
    assert expectation.behind_by >= 3


# -- there is no calendar feed, and the module says so ---------------------

def test_scheduled_date_returns_none_with_a_reason_not_an_invented_date():
    """The honest answer. Asserting '15 March' when no schedule was read would
    be exactly the fabrication the rest of the project refuses."""
    value, reason = scheduled_date("earnings_annual")
    assert value is None
    assert "no machine-readable feed" in reason
    assert "derived" in reason


def test_an_unknown_dataset_gets_a_different_reason():
    """'We did not look' and 'there is nothing to look at' are different
    claims."""
    _value, known = scheduled_date("earnings_annual")
    _value, unknown = scheduled_date("not_a_dataset")
    assert known != unknown
    assert "not a known dataset" in unknown


# -- against the committed vintages ---------------------------------------

def test_every_dataset_yields_an_expectation(conn):
    for dataset_id in ADAPTERS:
        periods = db.periods_for(conn, dataset_id)
        expectation = next_release(dataset_id, periods)
        assert expectation is not None, dataset_id
        assert expectation.cadence != "irregular", dataset_id
        assert expectation.expected_period, dataset_id
        assert expectation.basis


def test_the_headline_earnings_series_is_ahead_of_its_breakdowns(conn):
    """A real property of the source, not of this code: Geostat publishes the
    headline annual figure a year before the detailed breakdowns."""
    headline = next_release(
        "earnings_annual", db.periods_for(conn, "earnings_annual"))
    by_region = next_release(
        "earnings_by_region", db.periods_for(conn, "earnings_by_region"))
    assert headline.latest_period > by_region.latest_period


def test_overdue_datasets_are_flagged_on_the_reliability_page():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        body = client.get("/reliability", params={"lang": "en"}).text
    assert "have not published the period" in body
    assert "expected, newest published is" in body
    # and the page says why there is no date attached
    assert "rendered client-side" in body
