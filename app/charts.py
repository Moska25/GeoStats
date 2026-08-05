"""Hand-rolled inline SVG charts. No chart library, no CDN, no JavaScript.

Pure geometry: the functions here take numbers and return coordinates, so the
templates only interpolate strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Line:
    label: str
    colour: str
    points: list[tuple[float, float]] = field(default_factory=list)
    dashed: bool = False

    @property
    def path(self) -> str:
        return " ".join(
            f"{'M' if i == 0 else 'L'}{x:.2f},{y:.2f}"
            for i, (x, y) in enumerate(self.points)
        )


@dataclass
class Chart:
    width: int
    height: int
    lines: list[Line]
    x_ticks: list[tuple[float, str]]
    y_ticks: list[tuple[float, str]]
    empty: bool = False
    # One x per plotted period, kept so era_bands can line a band strip up with
    # the axis without re-deriving the geometry.
    x_positions: list[float] = field(default_factory=list)


# Series colours live in app.css so the theme owns them: the same hex cannot be
# legible on a dark instrument panel and on cream paper.
PALETTE = [
    "var(--series-1)", "var(--series-2)", "var(--series-3)",
    "var(--series-4)", "var(--series-5)",
]

PAD_L, PAD_R, PAD_T, PAD_B = 46, 12, 12, 26

# Roughly the width of a four-digit year at the axis font size, plus air.
MIN_TICK_GAP = 40.0


def line_chart(
    periods: list[str],
    series: dict[str, list[float | None]],
    *,
    width: int = 720,
    height: int = 260,
    y_zero: bool = False,
    value_fmt: str = "{:,.0f}",
    max_x_ticks: int = 8,
) -> Chart:
    """One x point per period, one line per named series. None means a gap."""
    values = [v for row in series.values() for v in row if v is not None]
    if not periods or not values:
        return Chart(width, height, [], [], [], empty=True)

    lo, hi = min(values), max(values)
    if y_zero:
        lo = min(lo, 0.0)
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    span = hi - lo
    lo -= span * 0.06
    hi += span * 0.06

    plot_w = width - PAD_L - PAD_R
    plot_h = height - PAD_T - PAD_B
    n = len(periods)

    def x_at(i: int) -> float:
        return PAD_L + (plot_w * i / (n - 1) if n > 1 else plot_w / 2)

    def y_at(v: float) -> float:
        return PAD_T + plot_h * (1 - (v - lo) / (hi - lo))

    lines = []
    for index, (label, row) in enumerate(series.items()):
        pts = [(x_at(i), y_at(v)) for i, v in enumerate(row) if v is not None]
        if pts:
            lines.append(Line(label, PALETTE[index % len(PALETTE)], pts))

    step = max(1, round(n / max_x_ticks))
    x_ticks = [(x_at(i), periods[i]) for i in range(0, n, step)]
    if x_ticks and x_ticks[-1][1] != periods[-1]:
        # The final period always gets a tick, but the stepped one before it may
        # be too close: on the 1970-2025 series that printed "2020" and "2025"
        # on top of each other. The last label wins, the crowded one goes.
        last_x = x_at(n - 1)
        if last_x - x_ticks[-1][0] < MIN_TICK_GAP:
            x_ticks.pop()
        x_ticks.append((last_x, periods[-1]))

    y_ticks = []
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        y_ticks.append((y_at(v), value_fmt.format(v)))

    return Chart(width, height, lines, x_ticks, y_ticks,
                 x_positions=[x_at(i) for i in range(n)])


def era_bands(
    chart: Chart,
    periods: list[str],
    unit_of: dict[str, str],
    *,
    current: str = "GEL",
) -> list[dict]:
    """Contiguous runs of one currency across the plotted periods.

    The unit comes from the observations themselves, not from a re-derivation,
    so the band names what each row is actually denominated in. Coordinates are
    in the chart's own space: both SVGs scale to the same width, so the strip
    stays aligned with the axis at any viewport.
    """
    if chart.empty or len(periods) != len(chart.x_positions) or not periods:
        return []

    runs: list[dict] = []
    for i, period in enumerate(periods):
        code = unit_of.get(period)
        if code is None:
            return []                      # an unlabelled row cannot be shaded
        if runs and runs[-1]["code"] == code:
            runs[-1]["last"] = i
        else:
            runs.append({"code": code, "first": i, "last": i})

    xs = chart.x_positions
    right = chart.width - PAD_R
    bands = []
    for run in runs:
        i, j = run["first"], run["last"]
        x0 = PAD_L if i == 0 else (xs[i - 1] + xs[i]) / 2
        x1 = right if j == len(xs) - 1 else (xs[j] + xs[j + 1]) / 2
        bands.append({
            "code": run["code"],
            "current": run["code"] == current,
            "x": x0,
            "width": max(x1 - x0, 0.0),
            "y": PAD_T,
            "height": chart.height - PAD_T - PAD_B,
            "first": periods[i],
            "last": periods[j],
        })
    return bands


def position_scale(
    points: list[tuple[str, float | None]], *, headroom: float = 0.08
) -> dict:
    """Marks on one shared 0-to-max axis, as percentages of the axis width.

    Used to place a salary against the published mean and median. Deliberately
    linear from zero: a scale that started at the smallest value would make the
    gap between two figures look like whatever the renderer chose.
    """
    values = [v for _, v in points if v is not None]
    if not values:
        return {"max": 0.0, "marks": []}
    top = max(values) * (1.0 + headroom)
    return {
        "max": top,
        "marks": [
            {"label": label, "value": value, "pct": round(value / top * 100, 2)}
            for label, value in points
            if value is not None
        ],
    }


def bar_rows(
    items: list[tuple[str, float]], *, fmt: str = "{:,.0f}"
) -> list[dict]:
    """Rows for the shared .bar component: label, value, percent of the max."""
    if not items:
        return []
    top = max(abs(v) for _, v in items) or 1.0
    return [
        {"label": label, "value": value, "text": fmt.format(value),
         "pct": round(abs(value) / top * 100, 2)}
        for label, value in items
    ]


def aligned_panels(
    periods: list[str],
    panels: list[tuple[str, list[float | None], str]],
    *,
    width: int = 720,
    height: int = 150,
) -> list[dict]:
    """One small chart per measure, all sharing the same x periods.

    This is the honest alternative to a dual axis. Two series on one pair of
    axes with different scales lets whoever chose the scales decide how the
    relationship looks: slide one axis and a correlation appears or vanishes.
    Stacking the panels keeps the x positions identical, so periods still line
    up vertically, while each measure keeps its own y scale and its own unit.
    """
    out = []
    for label, values, unit in panels:
        fmt = "{:,.1f}" if unit in {"percent", "index"} else "{:,.0f}"
        chart = line_chart(
            periods, {label: values}, width=width, height=height,
            value_fmt=fmt, max_x_ticks=8,
        )
        out.append({"label": label, "unit": unit, "chart": chart})
    return out


def small_multiples(
    series: list[tuple[str, list[str], list[float | None]]],
    *,
    width: int = 210,
    height: int = 110,
    shared_scale: bool = True,
) -> list[dict]:
    """A grid of miniature charts, one per category.

    `shared_scale` puts every panel on one y range so the panels can be
    compared by eye, which is the only reason to draw a grid of them. Per-panel
    scaling would make a 400 GEL activity and a 4,000 GEL activity draw the
    same line.
    """
    values = [v for _label, _p, row in series for v in row if v is not None]
    if not values:
        return []
    lo, hi = (min(values), max(values)) if shared_scale else (None, None)

    out = []
    for label, periods, row in series:
        if shared_scale:
            # line_chart derives its own range, so pin the range by adding two
            # invisible anchor points at the shared extremes.
            anchored = dict(main=row, _anchor=[lo] + [None] * (len(row) - 2) + [hi]
                            if len(row) > 1 else [lo])
            chart = line_chart(periods, anchored, width=width, height=height,
                               value_fmt="{:,.0f}", max_x_ticks=3)
            chart.lines = [line for line in chart.lines if line.label == "main"]
        else:
            chart = line_chart(periods, {"main": row}, width=width, height=height,
                               value_fmt="{:,.0f}", max_x_ticks=3)
        latest = next((v for v in reversed(row) if v is not None), None)
        first = next((v for v in row if v is not None), None)
        out.append({
            "label": label, "chart": chart, "latest": latest, "first": first,
            "change_pct": (
                None if not first or latest is None
                else round((latest / first - 1) * 100, 1)
            ),
        })
    return out


def dumbbell_rows(
    items: list[tuple[str, float | None, float | None]],
    *,
    left_label: str = "",
    right_label: str = "",
) -> dict:
    """Two measures of the same category on one shared axis from zero.

    Used for the hourly and monthly pay gap, where the interesting quantity is
    the distance between the two, not either value alone.
    """
    values = [v for _l, a, b in items for v in (a, b) if v is not None]
    if not values:
        return {"max": 0.0, "rows": [], "left_label": left_label,
                "right_label": right_label}
    top = max(values) * 1.08

    def pct(v):
        return None if v is None else round(v / top * 100, 2)

    return {
        "max": top,
        "left_label": left_label,
        "right_label": right_label,
        "rows": [
            {
                "label": label, "left": a, "right": b,
                "left_pct": pct(a), "right_pct": pct(b),
                "gap": None if a is None or b is None else round(b - a, 2),
            }
            for label, a, b in items
        ],
    }


def scatter(
    points: list[dict],
    *,
    width: int = 720,
    height: int = 380,
    x_label: str = "",
    y_label: str = "",
    x_fmt: str = "{:,.0f}",
    y_fmt: str = "{:,.1f}",
) -> dict:
    """Points with an optional size channel.

    Each point needs `x`, `y`, `label`, and optionally `size`. Size is mapped by
    area, not radius: a region with twice the population must cover twice the
    ink, and radius-mapping would make it look four times bigger.
    """
    usable = [p for p in points if p.get("x") is not None and p.get("y") is not None]
    if len(usable) < 2:
        return {"empty": True, "width": width, "height": height, "points": []}

    xs = [p["x"] for p in usable]
    ys = [p["y"] for p in usable]
    x_lo, x_hi = min(xs), max(xs)
    y_lo, y_hi = min(ys), max(ys)
    x_pad = (x_hi - x_lo) * 0.1 or 1.0
    y_pad = (y_hi - y_lo) * 0.1 or 1.0
    x_lo, x_hi = x_lo - x_pad, x_hi + x_pad
    y_lo, y_hi = y_lo - y_pad, y_hi + y_pad

    pad_l, pad_r, pad_t, pad_b = 52, 16, 16, 40
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    sizes = [p.get("size") or 0 for p in usable]
    size_max = max(sizes) or 1.0

    out = []
    for p in usable:
        share = (p.get("size") or 0) / size_max
        out.append({
            "label": p["label"],
            "x": p["x"], "y": p["y"], "size": p.get("size"),
            "cx": round(pad_l + plot_w * (p["x"] - x_lo) / (x_hi - x_lo), 2),
            "cy": round(pad_t + plot_h * (1 - (p["y"] - y_lo) / (y_hi - y_lo)), 2),
            # area proportional to the size channel; 4px floor keeps a small
            # region visible and clickable rather than a dot.
            "r": round(4 + 16 * (share ** 0.5), 2),
            "highlight": bool(p.get("highlight")),
        })

    x_ticks = [
        {"x": round(pad_l + plot_w * k / 4, 2),
         "label": x_fmt.format(x_lo + (x_hi - x_lo) * k / 4)}
        for k in range(5)
    ]
    y_ticks = [
        {"y": round(pad_t + plot_h * (1 - k / 4), 2),
         "label": y_fmt.format(y_lo + (y_hi - y_lo) * k / 4)}
        for k in range(5)
    ]
    return {
        "empty": False, "width": width, "height": height,
        "points": out, "x_ticks": x_ticks, "y_ticks": y_ticks,
        "x_label": x_label, "y_label": y_label,
        "plot_left": pad_l, "plot_right": width - pad_r,
        "plot_top": pad_t, "plot_bottom": height - pad_b,
    }


def stacked_rows(
    items: list[tuple[str, list[tuple[str, float | None]]]],
    *,
    fmt: str = "{:,.0f}",
) -> dict:
    """Composition bars: one row per category, one segment per component.

    Segments are percentages of that row's own total, so rows are comparable in
    shape. The absolute total is carried alongside because a composition alone
    cannot say whether the thing got bigger.
    """
    names: list[str] = []
    for _label, parts in items:
        for name, _v in parts:
            if name not in names:
                names.append(name)

    rows = []
    for label, parts in items:
        values = {name: v for name, v in parts if v is not None}
        total = sum(values.values())
        if not total:
            continue
        rows.append({
            "label": label,
            "total": total,
            "total_text": fmt.format(total),
            "segments": [
                {
                    "name": name,
                    "value": values.get(name),
                    "pct": round((values.get(name) or 0) / total * 100, 2),
                    "colour": PALETTE[names.index(name) % len(PALETTE)],
                }
                for name in names if values.get(name)
            ],
        })
    return {"names": names, "rows": rows,
            "colours": {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(names)}}


def diverging_rows(
    items: list[tuple[str, float | None]], *, fmt: str = "{:+,.0f}",
) -> dict:
    """Bars either side of a zero line, for a signed difference.

    Both directions are drawn against the same half-width so a +200 and a -200
    are the same length, which a naive max-scaled bar would not guarantee.
    """
    values = [abs(v) for _l, v in items if v is not None]
    if not values:
        return {"rows": [], "max": 0.0}
    top = max(values) or 1.0
    return {
        "max": top,
        "rows": [
            {
                "label": label, "value": value,
                "text": "n/a" if value is None else fmt.format(value),
                "pct": 0.0 if value is None else round(abs(value) / top * 50, 2),
                "negative": value is not None and value < 0,
            }
            for label, value in items
        ],
    }


# Georgia's regions laid out as an equal-area tile grid. This is a cartogram,
# not a map: every region gets one square regardless of its land area, so
# Racha-Lechkhumi is as visible as Kvemo Kartli. The rows run roughly north to
# south and the columns roughly west to east, so the layout is recognisable to
# someone who knows the country without pretending to be a boundary file.
REGION_TILES: dict[str, tuple[int, int]] = {
    "abkhazia":               (0, 0),
    "samegrelo_zemo_svaneti": (1, 0),
    "racha_lechkhumi":        (1, 2),
    "mtskheta_mtianeti":      (1, 3),
    "guria":                  (2, 0),
    "imereti":                (2, 1),
    "shida_kartli":           (2, 2),
    "kakheti":                (2, 4),
    "adjara":                 (3, 0),
    "samtskhe_javakheti":     (3, 1),
    "kvemo_kartli":           (3, 2),
    "tbilisi":                (2, 3),
}


def tile_atlas(
    values: dict[str, float | None],
    *,
    labels: dict[str, str] | None = None,
    fmt: str = "{:,.0f}",
    tile: int = 76,
    gap: int = 6,
) -> dict:
    """Equal-area tile cartogram of the regions, shaded by value.

    Shading is a relative rank position rather than a raw ratio, because the
    published regional figures are dominated by Tbilisi: a linear colour ramp
    would render eleven regions in one shade and the capital in another, which
    is a picture of the outlier, not of the country.
    """
    present = {
        code: v for code, v in values.items()
        if code in REGION_TILES and v is not None
    }
    ordered = sorted(present, key=lambda c: present[c])
    rank_of = {code: i for i, code in enumerate(ordered)}
    last = max(len(ordered) - 1, 1)

    cells = []
    for code, (row, col) in REGION_TILES.items():
        value = values.get(code)
        cells.append({
            "code": code,
            "label": (labels or {}).get(code, code.replace("_", " ").title()),
            "value": value,
            "text": "n/a" if value is None else fmt.format(value),
            "x": col * (tile + gap),
            "y": row * (tile + gap),
            "size": tile,
            # 0..1 by rank; None where the region publishes nothing this year.
            "intensity": (
                None if code not in rank_of else round(rank_of[code] / last, 3)
            ),
        })
    rows = max(r for r, _c in REGION_TILES.values()) + 1
    cols = max(c for _r, c in REGION_TILES.values()) + 1
    return {
        "cells": cells,
        "width": cols * (tile + gap) - gap,
        "height": rows * (tile + gap) - gap,
        "ranked": [
            {"code": c, "label": (labels or {}).get(c, c), "value": present[c]}
            for c in reversed(ordered)
        ],
    }
