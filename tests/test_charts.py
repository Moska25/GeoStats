"""The chart geometry. Pure functions, so the assertions are exact."""

from __future__ import annotations

import pytest

from app import charts


# -- axis ticks ------------------------------------------------------------

def test_axis_labels_do_not_collide_at_the_end_of_a_long_series():
    """The 1970-2025 series stepped to 2020 then appended 2025 five px away."""
    chart = charts.line_chart(
        [str(y) for y in range(1970, 2026)],
        {"s": [float(y) for y in range(1970, 2026)]},
    )
    xs = sorted(x for x, _ in chart.x_ticks)
    gaps = [b - a for a, b in zip(xs, xs[1:])]
    assert chart.x_ticks[-1][1] == "2025", "the final period must be labelled"
    assert min(gaps) >= charts.MIN_TICK_GAP


def test_the_final_period_is_always_labelled():
    chart = charts.line_chart(["2019", "2020", "2021"], {"s": [1.0, 2.0, 3.0]})
    assert chart.x_ticks[-1][1] == "2021"


# -- currency-era bands ----------------------------------------------------

def test_era_bands_split_into_contiguous_runs_of_one_currency():
    periods = ["1992", "1993", "1994", "1995", "1996"]
    chart = charts.line_chart(periods, {"s": [1.0, 2.0, 3.0, 4.0, 5.0]})
    units = {"1992": "RUB", "1993": "KUP", "1994": "TKUP", "1995": "GEL", "1996": "GEL"}
    bands = charts.era_bands(chart, periods, units)

    assert [b["code"] for b in bands] == ["RUB", "KUP", "TKUP", "GEL"]
    assert [b["current"] for b in bands] == [False, False, False, True]
    assert bands[-1]["first"] == "1995" and bands[-1]["last"] == "1996"
    # the bands tile the plot without gaps or overlaps
    for left, right in zip(bands, bands[1:]):
        assert left["x"] + left["width"] == pytest.approx(right["x"])
    assert bands[0]["x"] == pytest.approx(charts.PAD_L)
    assert bands[-1]["x"] + bands[-1]["width"] == pytest.approx(
        chart.width - charts.PAD_R
    )


def test_era_bands_refuse_to_shade_a_period_with_no_recorded_unit():
    periods = ["1995", "1996"]
    chart = charts.line_chart(periods, {"s": [1.0, 2.0]})
    assert charts.era_bands(chart, periods, {"1995": "GEL"}) == []


# -- position scale --------------------------------------------------------

def test_position_scale_is_linear_from_zero_with_headroom():
    scale = charts.position_scale([("median", 1000.0), ("mean", 2000.0)])
    assert scale["max"] == pytest.approx(2160.0)          # 2000 * 1.08
    assert [m["pct"] for m in scale["marks"]] == [
        pytest.approx(46.3, abs=0.05),                    # 1000 / 2160
        pytest.approx(92.59, abs=0.05),                   # 2000 / 2160
    ]


def test_position_scale_places_the_largest_point_wherever_it_falls():
    """An amount above both published figures must still fit on the axis."""
    scale = charts.position_scale([("mean", 1970.77), ("yours", 9000.0)])
    top = max(m["pct"] for m in scale["marks"])
    assert top < 100.0, "the headroom keeps the last mark inside the rail"
    assert scale["marks"][-1]["label"] == "yours"


def test_position_scale_drops_missing_points_and_survives_all_of_them_missing():
    assert charts.position_scale([("mean", None), ("median", 900.0)])["marks"] == [
        {"label": "median", "value": 900.0, "pct": 92.59}
    ]
    assert charts.position_scale([("mean", None)]) == {"max": 0.0, "marks": []}
