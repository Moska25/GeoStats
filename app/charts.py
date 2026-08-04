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


PALETTE = ["var(--accent)", "#34d399", "#fbbf24", "#f87171", "#a78bfa"]

PAD_L, PAD_R, PAD_T, PAD_B = 46, 12, 12, 26


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
        x_ticks.append((x_at(n - 1), periods[-1]))

    y_ticks = []
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        y_ticks.append((y_at(v), value_fmt.format(v)))

    return Chart(width, height, lines, x_ticks, y_ticks)


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
