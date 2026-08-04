"""Analytics. Pure functions: numbers in, numbers out, no I/O, no globals.

Everything here is unit-tested against hand-computed values in
tests/test_metrics.py. The formulas are stated in the docstrings and repeated
on /methodology so the number on screen and the number in the test are the
same number.

Two methodology facts govern this whole module and are repeated in the UI:

  * Geostat earnings are GROSS, before personal income tax.
  * They are an average over paid employees: earnings fund / average number of
    paid employees / months. That is not take-home pay and not a typical
    person's salary.
"""

from __future__ import annotations

from dataclasses import dataclass

CPI_BASE_DESCRIPTION = "Geostat CPI, 2010 annual average = 100"


class MetricError(ValueError):
    """Raised when the inputs cannot support the metric being asked for."""


def _require(value, label: str) -> float:
    if value is None:
        raise MetricError(f"{label} is not available")
    v = float(value)
    if v <= 0:
        raise MetricError(f"{label} must be positive, got {v}")
    return v


# --------------------------------------------------------------------------
# deflation
# --------------------------------------------------------------------------

def deflate(nominal: float, cpi_t: float, cpi_base: float) -> float:
    """Nominal value expressed in the prices of the base year.

        real = nominal * (cpi_base / cpi_t)
    """
    cpi_t = _require(cpi_t, "CPI for the year")
    cpi_base = _require(cpi_base, "CPI for the base year")
    return float(nominal) * (cpi_base / cpi_t)


def real_earnings_index(
    nominal_t: float, nominal_base: float, cpi_t: float, cpi_base: float
) -> float:
    """Real earnings index, base year = 100.

        index = (nominal_t / nominal_base) / (cpi_t / cpi_base) * 100
    """
    nominal_t = _require(nominal_t, "nominal earnings for the year")
    nominal_base = _require(nominal_base, "nominal earnings for the base year")
    cpi_t = _require(cpi_t, "CPI for the year")
    cpi_base = _require(cpi_base, "CPI for the base year")
    return (nominal_t / nominal_base) / (cpi_t / cpi_base) * 100.0


def nominal_index(nominal_t: float, nominal_base: float) -> float:
    """Nominal earnings index, base year = 100."""
    nominal_t = _require(nominal_t, "nominal earnings for the year")
    nominal_base = _require(nominal_base, "nominal earnings for the base year")
    return nominal_t / nominal_base * 100.0


# --------------------------------------------------------------------------
# inflation
# --------------------------------------------------------------------------

def cumulative_inflation(cpi_from: float, cpi_to: float) -> float:
    """Total price change between two years, in percent.

        inflation = (cpi_to / cpi_from - 1) * 100
    """
    cpi_from = _require(cpi_from, "CPI for the start year")
    cpi_to = _require(cpi_to, "CPI for the end year")
    return (cpi_to / cpi_from - 1.0) * 100.0


def annualised_inflation(cpi_from: float, cpi_to: float, years: int) -> float:
    """Geometric mean annual inflation over `years` years, in percent."""
    if years <= 0:
        raise MetricError("the period must span at least one year")
    cpi_from = _require(cpi_from, "CPI for the start year")
    cpi_to = _require(cpi_to, "CPI for the end year")
    return ((cpi_to / cpi_from) ** (1.0 / years) - 1.0) * 100.0


def preserve_purchasing_power(
    amount: float, cpi_from: float, cpi_to: float
) -> float:
    """The nominal amount in the later year that buys what `amount` bought in
    the earlier one.

        equivalent = amount * (cpi_to / cpi_from)

    This is the exact inverse of `deflate` with the arguments reversed, which
    the round-trip test in tests/test_metrics.py pins down.
    """
    cpi_from = _require(cpi_from, "CPI for the start year")
    cpi_to = _require(cpi_to, "CPI for the end year")
    if amount < 0:
        raise MetricError("amount must not be negative")
    return float(amount) * (cpi_to / cpi_from)


# --------------------------------------------------------------------------
# growth
# --------------------------------------------------------------------------

def yoy_growth(previous: float, current: float) -> float:
    """Percent change between consecutive periods."""
    previous = _require(previous, "previous period value")
    return (float(current) / previous - 1.0) * 100.0


def real_growth(
    nominal_prev: float, nominal_cur: float, cpi_prev: float, cpi_cur: float
) -> float:
    """Percent change after removing price change.

        real growth = ((nominal_cur / nominal_prev) / (cpi_cur / cpi_prev) - 1) * 100
    """
    nominal_prev = _require(nominal_prev, "previous nominal value")
    nominal_cur = _require(nominal_cur, "current nominal value")
    cpi_prev = _require(cpi_prev, "previous CPI")
    cpi_cur = _require(cpi_cur, "current CPI")
    return ((nominal_cur / nominal_prev) / (cpi_cur / cpi_prev) - 1.0) * 100.0


# --------------------------------------------------------------------------
# distribution shape
# --------------------------------------------------------------------------

@dataclass
class MeanMedianGap:
    mean: float
    median: float
    gap_gel: float
    gap_pct: float
    ratio: float

    @property
    def caveat(self) -> str:
        return (
            "The mean is pulled up by high earners. The median is the middle "
            "paid employee. Neither is a typical take-home wage: both are gross, "
            "before personal income tax."
        )


def mean_median_gap(mean: float, median: float) -> MeanMedianGap:
    """How far the average sits above the middle of the distribution.

        gap_pct = (mean / median - 1) * 100
    """
    mean = _require(mean, "mean earnings")
    median = _require(median, "median earnings")
    return MeanMedianGap(
        mean=mean,
        median=median,
        gap_gel=mean - median,
        gap_pct=(mean / median - 1.0) * 100.0,
        ratio=mean / median,
    )


# --------------------------------------------------------------------------
# series assembly (still pure: dicts in, list of dicts out)
# --------------------------------------------------------------------------

def build_series(
    nominal: dict[str, float],
    cpi: dict[str, float],
    median: dict[str, float] | None = None,
    *,
    base_year: str | None = None,
    preliminary: set[str] | None = None,
) -> list[dict]:
    """Join nominal earnings, CPI and (optionally) median into one table.

    Years without a CPI annual average are returned with real fields set to
    None rather than dropped, so the UI can say "not deflatable" instead of
    quietly shortening the chart. That is the JOIN contract made visible.
    """
    preliminary = preliminary or set()
    median = median or {}
    joint = sorted(y for y in nominal if nominal.get(y) is not None)
    if not joint:
        return []
    deflatable = [y for y in joint if cpi.get(y)]
    base_year = base_year or (deflatable[0] if deflatable else joint[0])

    nominal_base = nominal.get(base_year)
    cpi_base = cpi.get(base_year)

    out = []
    prev_year = None
    for year in joint:
        row = {
            "period": year,
            "nominal": nominal[year],
            "cpi": cpi.get(year),
            "median": median.get(year),
            "is_preliminary": year in preliminary,
            "nominal_index": None, "real_index": None,
            "real_gel": None, "nominal_yoy": None, "real_yoy": None,
            "mean_median_ratio": None,
        }
        if nominal_base:
            row["nominal_index"] = nominal_index(nominal[year], nominal_base)
        if cpi.get(year) and cpi_base and nominal_base:
            row["real_index"] = real_earnings_index(
                nominal[year], nominal_base, cpi[year], cpi_base
            )
            row["real_gel"] = deflate(nominal[year], cpi[year], cpi_base)
        if median.get(year):
            row["mean_median_ratio"] = nominal[year] / median[year]
        if prev_year is not None:
            row["nominal_yoy"] = yoy_growth(nominal[prev_year], nominal[year])
            if cpi.get(year) and cpi.get(prev_year):
                row["real_yoy"] = real_growth(
                    nominal[prev_year], nominal[year], cpi[prev_year], cpi[year]
                )
        out.append(row)
        prev_year = year
    return out
