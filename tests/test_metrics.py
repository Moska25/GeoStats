"""Analytics, checked against values computed by hand."""

from __future__ import annotations

import pytest

from app import metrics


# -- real earnings index ---------------------------------------------------

def test_real_earnings_index_hand_computed():
    """(2000/1000) / (150/100) * 100 = 2.0 / 1.5 * 100 = 133.333..."""
    assert metrics.real_earnings_index(2000, 1000, 150, 100) == pytest.approx(
        133.3333333, abs=1e-6
    )


def test_real_index_is_100_when_wages_track_prices_exactly():
    assert metrics.real_earnings_index(1500, 1000, 150, 100) == pytest.approx(100.0)


def test_real_index_below_100_when_prices_outrun_wages():
    assert metrics.real_earnings_index(1200, 1000, 150, 100) < 100


def test_deflate_hand_computed():
    """1000 at CPI 200, expressed in prices of a year with CPI 100 -> 500."""
    assert metrics.deflate(1000, 200, 100) == pytest.approx(500.0)


def test_nominal_index_hand_computed():
    # 1970.77 / 1068.27 = 1.8448239 -> 184.48
    assert metrics.nominal_index(1970.77, 1068.27) == pytest.approx(
        184.48239, abs=1e-4
    )


# -- inflation -------------------------------------------------------------

def test_cumulative_inflation_hand_computed():
    assert metrics.cumulative_inflation(100, 127.5) == pytest.approx(27.5)


def test_cumulative_inflation_is_negative_on_deflation():
    assert metrics.cumulative_inflation(120, 100) == pytest.approx(-16.6666667, abs=1e-6)


def test_annualised_inflation_compounds_back_to_the_total():
    rate = metrics.annualised_inflation(100, 121, 2)
    assert rate == pytest.approx(10.0, abs=1e-9)


def test_annualised_inflation_rejects_zero_span():
    with pytest.raises(metrics.MetricError):
        metrics.annualised_inflation(100, 121, 0)


# -- purchasing power ------------------------------------------------------

def test_purchasing_power_hand_computed():
    assert metrics.preserve_purchasing_power(1000, 100, 150) == pytest.approx(1500.0)


@pytest.mark.parametrize("amount,cpi_a,cpi_b", [
    (1000, 100, 150), (2282.70, 127.428492, 185.492792), (1, 99.9, 1.5),
])
def test_purchasing_power_and_deflate_round_trip(amount, cpi_a, cpi_b):
    """Inflating forward then deflating back must return the original amount."""
    forward = metrics.preserve_purchasing_power(amount, cpi_a, cpi_b)
    back = metrics.deflate(forward, cpi_b, cpi_a)
    assert back == pytest.approx(amount, rel=1e-12)


def test_purchasing_power_rejects_negative_amounts():
    with pytest.raises(metrics.MetricError):
        metrics.preserve_purchasing_power(-5, 100, 150)


# -- growth ----------------------------------------------------------------

def test_yoy_growth_hand_computed():
    assert metrics.yoy_growth(1000, 1100) == pytest.approx(10.0)


def test_real_growth_removes_price_change():
    """Nominal +20%, prices +20% -> real growth is zero."""
    assert metrics.real_growth(1000, 1200, 100, 120) == pytest.approx(0.0, abs=1e-12)


def test_real_growth_hand_computed():
    """(1200/1000) / (110/100) - 1 = 1.2/1.1 - 1 = 9.0909...%"""
    assert metrics.real_growth(1000, 1200, 100, 110) == pytest.approx(
        9.0909091, abs=1e-6
    )


def test_real_growth_can_be_negative_while_nominal_is_positive():
    assert metrics.yoy_growth(1000, 1050) > 0
    assert metrics.real_growth(1000, 1050, 100, 110) < 0


# -- mean vs median --------------------------------------------------------

def test_mean_median_gap_hand_computed():
    gap = metrics.mean_median_gap(1970.77, 1332.00)
    assert gap.gap_gel == pytest.approx(638.77, abs=0.005)
    assert gap.gap_pct == pytest.approx(47.955, abs=0.01)
    assert gap.ratio == pytest.approx(1.47955, abs=1e-5)


def test_mean_median_gap_rejects_zero_median():
    with pytest.raises(metrics.MetricError):
        metrics.mean_median_gap(1000, 0)


# -- guards ----------------------------------------------------------------

@pytest.mark.parametrize("fn,args", [
    (metrics.real_earnings_index, (None, 1000, 150, 100)),
    (metrics.deflate, (1000, None, 100)),
    (metrics.cumulative_inflation, (0, 120)),
    (metrics.yoy_growth, (0, 100)),
])
def test_metrics_refuse_unusable_inputs(fn, args):
    with pytest.raises(metrics.MetricError):
        fn(*args)


# -- series assembly -------------------------------------------------------

def test_build_series_marks_undeflatable_years_rather_than_dropping_them():
    nominal = {"1998": 55.4, "1999": 67.5, "2000": 72.3}
    cpi = {"2000": 52.0}                       # CPI does not reach back to 1998
    rows = metrics.build_series(nominal, cpi, base_year="2000")
    by_year = {r["period"]: r for r in rows}
    assert len(rows) == 3, "years without CPI must survive, not vanish"
    assert by_year["1998"]["real_index"] is None
    assert by_year["2000"]["real_index"] == pytest.approx(100.0)


def test_build_series_computes_yoy_between_consecutive_rows():
    rows = metrics.build_series({"2020": 1000.0, "2021": 1100.0}, {})
    assert rows[0]["nominal_yoy"] is None
    assert rows[1]["nominal_yoy"] == pytest.approx(10.0)


def test_build_series_carries_the_preliminary_flag():
    rows = metrics.build_series(
        {"2024": 1970.77, "2025": 2282.70}, {}, preliminary={"2025"}
    )
    assert rows[0]["is_preliminary"] is False
    assert rows[1]["is_preliminary"] is True


# -- regional index --------------------------------------------------------

def test_region_index_is_100_when_the_region_matches_the_country():
    assert metrics.region_index(1234.5, 1234.5) == pytest.approx(100.0)


def test_region_index_against_a_hand_computed_value():
    # 1,014.3 GEL against a national 1,918.6 GEL.
    # 1014.3 / 1918.6 * 100 = 52.86667361...
    assert metrics.region_index(1014.3, 1918.6) == pytest.approx(52.866674, abs=1e-6)


def test_region_index_refuses_a_missing_or_zero_national_figure():
    with pytest.raises(metrics.MetricError):
        metrics.region_index(1000.0, None)
    with pytest.raises(metrics.MetricError):
        metrics.region_index(1000.0, 0.0)
