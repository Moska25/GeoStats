"""Parser behaviour against the real committed workbook."""

from __future__ import annotations

import pytest

from app.adapters import (
    ADAPTERS, MISSING_MARKERS, currency_for_year, currency_name,
    parse_number, parse_period_header, slug,
)
from app.ingest import latest_vintage, read_raw

DATASET = "earnings_annual"


@pytest.fixture(scope="module")
def annual_rows():
    vintage = latest_vintage(DATASET)
    assert vintage, "no committed vintage for earnings_annual"
    return ADAPTERS[DATASET].parse(read_raw(DATASET, vintage))


@pytest.fixture(scope="module")
def totals(annual_rows):
    return {r.period: r for r in annual_rows if r.breakdown_code == "total"}


# -- the published values --------------------------------------------------

@pytest.mark.parametrize("year,expected", [
    ("2018", 1068.27), ("2019", 1129.47), ("2020", 1191.00),
    ("2021", 1304.52), ("2022", 1543.04), ("2023", 1766.82),
    ("2024", 1970.77), ("2025", 2282.70),
])
def test_published_totals_match_geostat(totals, year, expected):
    assert totals[year].value == pytest.approx(expected, abs=0.005)


def test_missing_marker_is_preserved_not_zeroed(annual_rows):
    gaps = [r for r in annual_rows if r.status == "missing"]
    assert gaps, "the workbook does contain published gaps"
    assert all(r.value is None for r in gaps)
    assert all(r.raw in MISSING_MARKERS for r in gaps)


def test_ellipsis_parses_as_missing():
    value, status, raw = parse_number("…")
    assert (value, status, raw) == (None, "missing", "…")


def test_numeric_string_cell_is_parsed(totals):
    """2010 is stored as the text '597.6', not a number, in the source sheet."""
    row = totals["2010"]
    assert row.status == "ok"
    assert row.value == pytest.approx(597.6)


def test_decimal_comma_is_refused_not_guessed():
    value, status, _raw = parse_number("1970,77")
    assert value is None
    assert status == "unparsed", "a comma must never be guessed as a separator"


# -- the preliminary marker ------------------------------------------------

def test_double_asterisk_marks_preliminary():
    assert parse_period_header("2025**") == ("2025", True)


def test_single_asterisk_is_a_footnote_not_preliminary():
    assert parse_period_header("2006*") == ("2006", False)


def test_preliminary_flag_survives_into_rows(totals):
    assert totals["2025"].is_preliminary is True
    assert totals["2024"].is_preliminary is False


# -- the currency-era trap -------------------------------------------------

@pytest.mark.parametrize("year,unit", [
    (1970, "RUB"), (1992, "RUB"), (1993, "KUP"),
    (1994, "TKUP"), (1995, "GEL"), (2025, "GEL"),
])
def test_currency_for_year(year, unit):
    assert currency_for_year(year) == unit


def test_rows_carry_the_currency_of_their_own_year(totals):
    assert totals["1992"].unit == "RUB"
    assert totals["1993"].unit == "KUP"
    assert totals["1994"].unit == "TKUP"
    assert totals["1995"].unit == "GEL"


def test_the_1994_to_1995_cliff_is_a_currency_change_not_a_wage_change(totals):
    """6151.6 -> 13.5 would be a 99.8% collapse if the units were the same."""
    ratio = totals["1995"].value / totals["1994"].value
    assert ratio < 0.01
    assert totals["1994"].unit != totals["1995"].unit


def test_currency_names_are_labelled():
    assert currency_name("KUP") == "Coupon"
    assert currency_name("TKUP") == "Thousand Coupon"


# -- structure -------------------------------------------------------------

def test_sections_become_breakdown_prefixes(annual_rows):
    codes = {r.breakdown_code for r in annual_rows}
    assert {"total", "sex.women", "sex.men",
            "type_of_ownership.public", "sector.business"} <= codes


def test_slug_is_stable():
    assert slug("Type of ownership") == "type_of_ownership"
    assert slug("Adjara A.R.") == "adjara_a_r"


def test_every_adapter_parses_its_committed_vintage():
    for dataset_id, adapter in ADAPTERS.items():
        vintage = latest_vintage(dataset_id)
        assert vintage, f"{dataset_id} has no committed vintage"
        rows = adapter.parse(read_raw(dataset_id, vintage))
        assert rows, f"{dataset_id} parsed to zero rows"
        assert all(r.period for r in rows)
        assert all(r.unit for r in rows)


def test_basket_weights_key_includes_the_coicop_level():
    """COICOP '11' is Food at level 3 and Restaurants at level 2. The code
    alone is not a unique key; the level has to be part of it."""
    vintage = latest_vintage("basket_weights")
    rows = ADAPTERS["basket_weights"].parse(read_raw("basket_weights", vintage))
    labels = {
        r.breakdown_code: r.breakdown_label for r in rows
        if r.breakdown_code.endswith(".11")
    }
    assert len(labels) == 2, "both level-2 and level-3 code 11 must survive"
    assert set(labels) == {"l2.11", "l3.11"}


def test_cpi_annual_average_only_uses_complete_years():
    vintage = latest_vintage("cpi_2010_base")
    rows = ADAPTERS["cpi_2010_base"].parse(read_raw("cpi_2010_base", vintage))
    annual = {
        r.period: r.value for r in rows
        if r.indicator_code == "cpi_annual_avg_2010_100"
        and r.breakdown_code == "georgia"
    }
    monthly_by_year: dict[str, int] = {}
    for r in rows:
        if r.indicator_code == "cpi_2010_100" and r.breakdown_code == "georgia":
            monthly_by_year[r.period[:4]] = monthly_by_year.get(r.period[:4], 0) + 1
    for year, count in monthly_by_year.items():
        if count < 12:
            assert year not in annual, f"{year} has {count} months but got an average"


def test_cpi_2010_annual_average_is_exactly_the_base():
    """The index is published with 2010 average = 100, so the derivation is
    self-checking: it must return 100 for the base year."""
    vintage = latest_vintage("cpi_2010_base")
    rows = ADAPTERS["cpi_2010_base"].parse(read_raw("cpi_2010_base", vintage))
    value = next(
        r.value for r in rows
        if r.indicator_code == "cpi_annual_avg_2010_100"
        and r.breakdown_code == "georgia" and r.period == "2010"
    )
    assert value == pytest.approx(100.0, abs=0.01)
