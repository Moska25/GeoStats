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
