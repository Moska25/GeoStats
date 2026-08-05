"""Data contracts.

Each contract is a declarative check over a normalised row set. It returns
pass/fail, a message a human can act on, and the rows that offended. Contracts
run on every ingestion, on every committed vintage, and on the deliberately
corrupted copies the fault lab produces - the same code path in all three cases,
which is the only way to know the checks actually bite.

The headline check is CURRENCY_ERA. Geostat's annual earnings workbook puts
1992 (Roubles), 1993 (Coupons), 1994 (Thousand Coupons) and 1995 (Lari) in
adjacent columns. Plot them and you get a 99.95% wage collapse in 1995 that
never happened. A platform that does not encode this is producing confident
nonsense.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable

from .adapters import ADAPTERS, GEL_ERA_START, MISSING_MARKERS, currency_for_year

# Plausibility envelopes per unit. Deliberately wide: the job is to catch
# order-of-magnitude nonsense, not to second-guess the statistical office.
RANGE_BY_UNIT = {
    "GEL":  (0.01, 1_000_000.0),
    "RUB":  (0.01, 1_000_000.0),
    "KUP":  (0.01, 10_000_000.0),
    "TKUP": (0.01, 10_000_000.0),
    "index_2010_100":      (1.0, 1000.0),
    "index_prev_year_100": (1.0, 1000.0),
    "share_of_1":          (0.0, 1.0001),
    # Georgia's 15+ population is ~3.2 million, so a head count in thousands
    # cannot plausibly reach five figures.
    "thousand_persons":    (0.0, 10_000.0),
    "percent":             (0.0, 100.0),
    "persons":             (0.0, 10_000_000.0),
    "enterprises":         (0.0, 10_000_000.0),
    "thousand_visits":     (0.0, 100_000.0),
    # Household survey figures are per household per month. The upper bound is
    # deliberately far above any published Georgian figure; it exists to catch
    # an annual total pasted into a monthly column, not to judge the survey.
    "GEL_per_household_month": (0.0, 100_000.0),
    "count":               (0.0, 100_000_000.0),
}

# Ratio between consecutive periods of the same series and unit that we treat
# as "someone shifted the units", not "wages moved".
JUMP_FACTOR = 10.0

# Weights are re-derived from a household survey each year and small COICOP
# subgroups legitimately move by an order of magnitude. Temporal sanity would
# only produce noise there.
# ponytail: excluded by unit, not by dataset - revisit if a new share-valued
# dataset arrives that does need the check.
TEMPORAL_SANITY_SKIP_UNITS = {"share_of_1"}

# Residual categories exist to absorb whatever the survey could not classify.
# The LFS "not identified worker" line falls from 87 thousand in 2001 to 67
# people in 2007 and back up again; that is the bucket doing its job across two
# questionnaire redesigns, not a unit shift. Every other breakdown in these
# datasets stays under the check.
# ponytail: matched on the code, so a new dataset with its own residual line is
# covered without another entry here. Matched against the indicator as well as
# the breakdown, because the regional workbooks put the measure on the rows and
# the place on the columns - the residual lands on the other axis there.
TEMPORAL_SANITY_SKIP_FRAGMENT = "not_identified"

# A 10x step only implies a unit error if the values are big enough for 10x to
# be surprising. Property income of 0.46 GEL a month per household, one
# registered enterprise in Abkhazia, or a 0.25% adjusted pay gap can all move
# by an order of magnitude for entirely ordinary reasons, and flagging them
# produces noise that buries the real finding. Below these floors the check
# abstains rather than guesses. Monetary units carry no floor on purpose: the
# currency-era trap is exactly a large step in a large series, and that must
# always bite.
TEMPORAL_MATERIAL_FLOOR_BY_UNIT = {
    "thousand_persons": 1.0,            # a thousand people
    "GEL_per_household_month": 10.0,    # ten lari a month
    "enterprises": 10.0,
    "persons": 10.0,
    "percent": 1.0,                     # one percentage point
    "thousand_visits": 1.0,
}


@dataclass
class CheckResult:
    code: str
    title: str
    why: str
    passed: bool
    message: str
    offenders: list[dict] = field(default_factory=list)
    checked: int = 0
    skipped: bool = False

    @property
    def status(self) -> str:
        if self.skipped:
            return "skipped"
        return "pass" if self.passed else "fail"


@dataclass
class Contract:
    code: str
    title: str
    why: str
    fn: Callable
    applies_to: str = "all"     # "all" | "earnings" | "cpi"

    def run(self, ctx: dict) -> CheckResult:
        return self.fn(self, ctx)


def _ok(c: Contract, message: str, checked: int) -> CheckResult:
    return CheckResult(c.code, c.title, c.why, True, message, [], checked)


def _bad(c: Contract, message: str, offenders: list[dict], checked: int) -> CheckResult:
    return CheckResult(c.code, c.title, c.why, False, message, offenders[:40], checked)


def _annual(period: str) -> bool:
    return len(period) == 4 and period.isdigit()


def _quarterly(period: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-Q[1-4]", period))


def _quarter_range(start: str, end: str) -> set[str]:
    """Every quarter from `start` to `end` inclusive, as `YYYY-QN`."""
    out: set[str] = set()
    year, quarter = int(start[:4]), int(start[-1])
    while f"{year}-Q{quarter}" <= end:
        out.add(f"{year}-Q{quarter}")
        quarter += 1
        if quarter == 5:
            year, quarter = year + 1, 1
    return out


def _year(period: str) -> int:
    return int(period[:4])


def _is_monetary(unit: str) -> bool:
    return unit in {"GEL", "RUB", "KUP", "TKUP"}


# --------------------------------------------------------------------------
# 1. schema
# --------------------------------------------------------------------------

REQUIRED_FIELDS = [
    "dataset_id", "indicator_code", "breakdown_code", "period", "unit",
    "value", "raw", "status", "is_preliminary", "vintage_id",
]


def _schema(c: Contract, ctx: dict) -> CheckResult:
    rows = ctx["rows"]
    if not rows:
        return _bad(c, "no rows produced by the adapter", [], 0)
    offenders = []
    for row in rows:
        missing = [f for f in REQUIRED_FIELDS if f not in row]
        if missing:
            offenders.append({**row, "_problem": f"missing fields {missing}"})
    empties = [r for r in rows if not r.get("period") or not r.get("unit")]
    offenders += [{**r, "_problem": "blank period or unit"} for r in empties]
    if offenders:
        return _bad(c, f"{len(offenders)} rows have a broken schema", offenders, len(rows))
    return _ok(
        c,
        f"all {len(rows)} rows carry the {len(REQUIRED_FIELDS)} required fields",
        len(rows),
    )


# --------------------------------------------------------------------------
# 2. composite-key uniqueness
# --------------------------------------------------------------------------

def _uniqueness(c: Contract, ctx: dict) -> CheckResult:
    rows = ctx["rows"]
    counts = Counter(
        (r["dataset_id"], r["indicator_code"], r["breakdown_code"], r["period"],
         r["unit"], r.get("vintage_id", ""))
        for r in rows
    )
    dupes = {k: n for k, n in counts.items() if n > 1}
    if dupes:
        offenders = [
            {"indicator_code": k[1], "breakdown_code": k[2], "period": k[3],
             "unit": k[4], "_problem": f"appears {n} times"}
            for k, n in sorted(dupes.items())
        ]
        return _bad(
            c,
            f"{len(dupes)} composite keys are duplicated - the series is no "
            "longer addressable and any aggregate over it is double-counted",
            offenders, len(rows),
        )
    return _ok(c, f"{len(counts)} composite keys, all unique", len(rows))


# --------------------------------------------------------------------------
# 3. period coverage
# --------------------------------------------------------------------------

def _coverage(c: Contract, ctx: dict) -> CheckResult:
    rows = ctx["rows"]
    by_series: dict[tuple, set[str]] = defaultdict(set)
    for r in rows:
        by_series[(r["indicator_code"], r["breakdown_code"])].add(r["period"])

    offenders = []
    checked = 0
    for (indicator, breakdown), periods in by_series.items():
        annual = all(_annual(p) for p in periods)
        quarterly = all(_quarterly(p) for p in periods)
        if quarterly:
            quarters = sorted(periods)
            if len(quarters) < 2:
                continue
            checked += 1
            gaps = sorted(_quarter_range(quarters[0], quarters[-1]) - set(quarters))
            if gaps:
                offenders.append({
                    "indicator_code": indicator, "breakdown_code": breakdown,
                    "_problem": (
                        f"missing quarters {gaps[:8]} ({len(gaps)} total) "
                        f"between {quarters[0]} and {quarters[-1]}"
                    ),
                })
        elif annual:
            # Geostat publishes 1970/1975/1980/1985 then annually from 1986.
            # Only the Lari era has to be gapless; earlier sampling is by design.
            years = sorted(_year(p) for p in periods if _year(p) >= GEL_ERA_START)
            if len(years) < 2:
                continue
            checked += 1
            expected = set(range(years[0], years[-1] + 1))
            gaps = sorted(expected - set(years))
            if gaps:
                offenders.append({
                    "indicator_code": indicator, "breakdown_code": breakdown,
                    "_problem": f"missing years {gaps} between {years[0]} and {years[-1]}",
                })
        else:
            months = sorted(p for p in periods if re.fullmatch(r"\d{4}-\d{2}", p))
            if len(months) < 2:
                continue
            checked += 1
            start, end = months[0], months[-1]
            expected = set()
            y, m = int(start[:4]), int(start[5:])
            while f"{y}-{m:02d}" <= end:
                expected.add(f"{y}-{m:02d}")
                m += 1
                if m == 13:
                    y, m = y + 1, 1
            gaps = sorted(expected - set(months))
            if gaps:
                offenders.append({
                    "indicator_code": indicator, "breakdown_code": breakdown,
                    "_problem": f"missing periods {gaps[:8]} ({len(gaps)} total)",
                })
    if offenders:
        return _bad(
            c,
            f"{len(offenders)} series have holes in their period coverage - a "
            "growth rate computed across a hole silently spans two intervals",
            offenders, checked,
        )
    return _ok(c, f"{checked} series are gapless over their published span", checked)


# --------------------------------------------------------------------------
# 4. value range plausibility
# --------------------------------------------------------------------------

def _value_range(c: Contract, ctx: dict) -> CheckResult:
    rows = ctx["rows"]
    offenders = []
    checked = 0
    for r in rows:
        if r.get("value") is None:
            continue
        checked += 1
        bounds = RANGE_BY_UNIT.get(r["unit"])
        if bounds is None:
            offenders.append({**r, "_problem": f"no range declared for unit {r['unit']}"})
            continue
        lo, hi = bounds
        if not (lo <= r["value"] <= hi):
            offenders.append({
                **r,
                "_problem": f"{r['value']} outside plausible {lo}..{hi} for {r['unit']}",
            })
    if offenders:
        return _bad(
            c, f"{len(offenders)} values are outside the plausible range for "
            "their unit (a negative wage or a 1000x figure is a defect, not news)",
            offenders, checked,
        )
    return _ok(c, f"{checked} numeric values sit inside their unit's range", checked)


# --------------------------------------------------------------------------
# 5. currency-era consistency - the headline contract
# --------------------------------------------------------------------------

def _currency_era(c: Contract, ctx: dict) -> CheckResult:
    rows = [r for r in ctx["rows"] if _is_monetary(r["unit"]) or r["unit"] == "GEL"]
    monetary = [r for r in ctx["rows"] if _is_monetary(r["unit"])]
    if not monetary:
        return _ok(c, "dataset carries no monetary values; era check not applicable", 0)

    offenders = []
    for r in monetary:
        if not _annual(r["period"]):
            continue
        expected = currency_for_year(_year(r["period"]))
        if r["unit"] != expected:
            offenders.append({
                **r,
                "_problem": (
                    f"period {r['period']} is tagged {r['unit']} but Georgia used "
                    f"{expected} that year"
                ),
            })

    # A single series must never mix eras under one unit label: that is exactly
    # the bug where 1993 Coupons get plotted next to 1995 Lari.
    by_series = defaultdict(set)
    for r in monetary:
        if _annual(r["period"]):
            by_series[(r["indicator_code"], r["breakdown_code"], r["unit"])].add(
                currency_for_year(_year(r["period"]))
            )
    for (indicator, breakdown, unit), eras in by_series.items():
        if len(eras) > 1:
            offenders.append({
                "indicator_code": indicator, "breakdown_code": breakdown,
                "unit": unit, "period": "-",
                "_problem": (
                    f"series labelled {unit} spans currency eras {sorted(eras)}; "
                    "these values are not comparable and must not be one line"
                ),
            })
    if offenders:
        return _bad(
            c,
            f"{len(offenders)} rows mislabel their monetary era. Georgia used "
            "Rouble to 1992, Coupon in 1993, Thousand Coupon in 1994 and Lari "
            "from 1995; the columns are four different currencies.",
            offenders, len(monetary),
        )
    eras = sorted({r["unit"] for r in monetary})
    return _ok(
        c,
        f"{len(monetary)} monetary values each carry the currency actually in "
        f"force that year (eras present: {', '.join(eras)})",
        len(monetary),
    )


# --------------------------------------------------------------------------
# 6. temporal sanity
# --------------------------------------------------------------------------

def _temporal_sanity(c: Contract, ctx: dict) -> CheckResult:
    rows = ctx["rows"]
    by_series = defaultdict(list)
    for r in rows:
        if r.get("value") is None or r["unit"] in TEMPORAL_SANITY_SKIP_UNITS:
            continue
        if TEMPORAL_SANITY_SKIP_FRAGMENT in r["breakdown_code"]:
            continue
        if TEMPORAL_SANITY_SKIP_FRAGMENT in r["indicator_code"]:
            continue
        by_series[(r["indicator_code"], r["breakdown_code"], r["unit"])].append(r)

    offenders = []
    checked = 0
    for key, series in by_series.items():
        series.sort(key=lambda r: r["period"])
        floor = TEMPORAL_MATERIAL_FLOOR_BY_UNIT.get(key[2], 0.0)
        for prev, cur in zip(series, series[1:]):
            # A step to or from exactly zero is never a unit shift: unit errors
            # are multiplicative and no conversion factor produces zero. A
            # published zero means the thing did not happen that year - no
            # household in the sample sold property, no enterprise in Abkhazia
            # closed - and dividing by it or reporting it as a 1000x move says
            # nothing about data quality.
            if prev["value"] in (0, None) or cur["value"] in (0, None):
                continue
            if max(abs(prev["value"]), abs(cur["value"])) < floor:
                continue
            checked += 1
            ratio = cur["value"] / prev["value"]
            if ratio >= JUMP_FACTOR or ratio <= 1 / JUMP_FACTOR:
                offenders.append({
                    "indicator_code": key[0], "breakdown_code": key[1],
                    "unit": key[2], "period": cur["period"],
                    "value": cur["value"],
                    "_problem": (
                        f"{prev['period']}={prev['value']:.4g} -> "
                        f"{cur['period']}={cur['value']:.4g} is a {ratio:.4g}x step "
                        f"inside one unit ({key[2]})"
                    ),
                })
    if offenders:
        return _bad(
            c,
            f"{len(offenders)} consecutive-period steps exceed {JUMP_FACTOR}x "
            "within a single unit. Real wage series do not do this; unit shifts "
            "and decimal-separator mistakes do.",
            offenders, checked,
        )
    return _ok(
        c, f"{checked} consecutive-period steps all stay within {JUMP_FACTOR}x", checked
    )


# --------------------------------------------------------------------------
# 7. preliminary-flag preservation
# --------------------------------------------------------------------------

def _preliminary(c: Contract, ctx: dict) -> CheckResult:
    rows = ctx["rows"]
    by_period = defaultdict(set)
    for r in rows:
        by_period[r["period"]].add(bool(r.get("is_preliminary")))
    offenders = [
        {"period": p, "_problem": "some rows flagged preliminary and some not"}
        for p, flags in by_period.items() if len(flags) > 1
    ]

    prior = ctx.get("prior_rows")
    if prior:
        prior_prelim = {
            r["period"] for r in prior if r.get("is_preliminary")
        }
        prior_values = {
            (r["indicator_code"], r["breakdown_code"], r["period"]): r.get("value")
            for r in prior
        }
        now_prelim = {r["period"] for r in rows if r.get("is_preliminary")}
        for period in sorted(prior_prelim - now_prelim):
            same = [
                r for r in rows
                if r["period"] == period
                and prior_values.get(
                    (r["indicator_code"], r["breakdown_code"], period)
                ) == r.get("value")
            ]
            if same:
                offenders.append({
                    "period": period,
                    "_problem": (
                        "was preliminary in the previous vintage, is no longer "
                        "flagged, and the value did not change - the marker was "
                        "stripped rather than the figure finalised"
                    ),
                })
    if offenders:
        return _bad(
            c,
            f"{len(offenders)} preliminary-flag problems. The '**' marker is "
            "data: dropping it turns a provisional figure into an apparently "
            "final one.",
            offenders, len(rows),
        )
    flagged = sorted({r["period"] for r in rows if r.get("is_preliminary")})
    detail = f"preliminary periods: {', '.join(flagged)}" if flagged else \
        "no period is marked preliminary in this release"
    return _ok(c, detail, len(rows))


# --------------------------------------------------------------------------
# 8. numeric parse integrity
# --------------------------------------------------------------------------

def _parse_integrity(c: Contract, ctx: dict) -> CheckResult:
    rows = ctx["rows"]
    offenders = []
    for r in rows:
        raw = (r.get("raw") or "").strip()
        status, value = r.get("status"), r.get("value")
        if status == "ok" and value is None:
            offenders.append({**r, "_problem": "status ok but no value"})
        elif status == "missing" and value is not None:
            offenders.append({
                **r,
                "_problem": (
                    f"raw {raw!r} is a published gap marker but a value of "
                    f"{value} was recorded - a gap was coerced into a number"
                ),
            })
        elif status == "ok" and raw in MISSING_MARKERS and raw != "":
            offenders.append({
                **r, "_problem": f"raw {raw!r} is a gap marker parsed as ok",
            })
        elif status == "unparsed" and value is not None:
            offenders.append({**r, "_problem": "unparsed but carries a value"})
    if offenders:
        return _bad(
            c,
            f"{len(offenders)} rows lost parse integrity. Geostat writes '…' for "
            "not-published; turning that into 0 fabricates a statistic.",
            offenders, len(rows),
        )
    counts = Counter(r.get("status") for r in rows)
    return _ok(
        c,
        f"{counts.get('ok', 0)} parsed, {counts.get('missing', 0)} preserved as "
        f"published gaps, {counts.get('unparsed', 0)} refused",
        len(rows),
    )


# --------------------------------------------------------------------------
# 9. cross-dataset period alignment (wage / CPI join)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Identity:
    """A relationship the source itself declares between its own measures.

    Geostat prints these in the row labels: `1. Income, total (2+3)` says that
    row 1 is rows 2 and 3 added together, and the labour force sheet publishes
    both the unemployment count and the rate it implies. Checking them is how
    a parser that read the right numbers into the wrong rows gets caught: every
    individual value would sit inside its plausible range, and only the
    arithmetic between them would break.
    """

    dataset_id: str
    target: str
    parts: tuple[str, ...]
    kind: str = "sum"            # sum | ratio_percent
    note: str = ""

    def expected(self, values: dict[str, float]) -> float | None:
        if self.kind == "sum":
            return sum(values[p] for p in self.parts)
        numerator, denominator = (values[p] for p in self.parts)
        if not denominator:
            return None
        return 100.0 * numerator / denominator

    def describe(self) -> str:
        if self.kind == "sum":
            return f"{self.target} = {' + '.join(self.parts)}"
        return f"{self.target} = 100 x {self.parts[0]} / {self.parts[1]}"


IDENTITIES: list[Identity] = [
    Identity("labour_force", "labour_force", ("employed", "unemployed"),
             note="the labour force is by definition everyone working or "
                  "looking for work"),
    Identity("labour_force", "unemployment_rate_percentage",
             ("unemployed", "labour_force"), kind="ratio_percent",
             note="the published rate must be the published counts' own ratio"),
    Identity("labour_force_by_region", "labour_force",
             ("employed", "unemployed")),
    Identity("labour_force_by_region", "unemployment_rate_percentage",
             ("unemployed", "labour_force"), kind="ratio_percent"),
    Identity("household_income", "income_total",
             ("cash_income_and_transfers", "non_cash_income"),
             note="the sheet states this identity in its own row label, '1. "
                  "Income, total (2+3)'"),
    Identity("household_expenditure", "consumption_expenditure_total",
             ("cash_consumption_expenditure", "non_cash_expenditure")),
    Identity("business_demography", "enterprise_birth_rate",
             ("enterprise_births", "active_enterprises"), kind="ratio_percent"),
    Identity("business_demography", "enterprise_death_rate",
             ("enterprise_deaths", "active_enterprises"), kind="ratio_percent"),
]

# Published figures are rounded, so an identity is allowed to miss by a hair.
# The committed vintages hold to floating-point precision, so anything this
# check reports is a real break rather than a rounding artefact.
# Half the last digit PX-Web publishes. Derived from the API's rounding, not
# chosen to make the check pass: the largest observed disagreement across 2,029
# shared cells is exactly 0.05, which is what pure rounding produces.
SOURCE_AGREEMENT_TOLERANCE = 0.05

IDENTITY_ABS_TOLERANCE = 0.01
IDENTITY_REL_TOLERANCE = 0.005


def _identity(c: Contract, ctx: dict) -> CheckResult:
    dataset_id = ctx.get("dataset_id") or ""
    applicable = [i for i in IDENTITIES if i.dataset_id == dataset_id]
    if not applicable:
        return _ok(c, "no published identity is declared for this dataset", 0)

    by_cell: dict[tuple, dict[str, float]] = defaultdict(dict)
    for r in ctx["rows"]:
        if r.get("value") is None:
            continue
        by_cell[(r["breakdown_code"], r["period"])][r["indicator_code"]] = r["value"]

    offenders = []
    checked = 0
    for identity in applicable:
        needed = {identity.target, *identity.parts}
        for (breakdown, period), values in by_cell.items():
            if not needed <= values.keys():
                continue
            expected = identity.expected(values)
            if expected is None:
                continue
            checked += 1
            actual = values[identity.target]
            slack = max(IDENTITY_ABS_TOLERANCE,
                        abs(expected) * IDENTITY_REL_TOLERANCE)
            if abs(actual - expected) > slack:
                offenders.append({
                    "indicator_code": identity.target,
                    "breakdown_code": breakdown, "period": period,
                    "value": actual,
                    "_problem": (
                        f"{identity.describe()} gives {expected:.4f} but the "
                        f"file publishes {actual:.4f} "
                        f"(off by {actual - expected:+.4f})"
                    ),
                })
    if offenders:
        return _bad(
            c,
            f"{len(offenders)} published values disagree with the identity the "
            "source itself states between its own measures. Every value can be "
            "individually plausible and the arithmetic between them still wrong.",
            offenders, checked,
        )
    return _ok(
        c,
        f"{checked} cells satisfy the {len(applicable)} "
        f"{'identity' if len(applicable) == 1 else 'identities'} this dataset "
        f"declares ({'; '.join(i.describe() for i in applicable)})",
        checked,
    )


def _source_agreement(c: Contract, ctx: dict) -> CheckResult:
    """Compare this vintage against the same series from Geostat's PX-Web API.

    Two independent publications of one survey, reached by two code paths that
    share nothing: one parses a spreadsheet grid, the other reads a JSON API.
    A parser that took the wrong column would sail through every other check in
    this file - the values would be real numbers, in range, gapless, correctly
    united - and would disagree with the API immediately.

    The comparison is bounded by rounding rather than exact, because PX-Web
    publishes one decimal place and the spreadsheets carry full precision. The
    tolerance is half the last published digit, which is the largest gap
    rounding alone can produce; it is derived, not tuned.
    """
    api_rows = ctx.get("api_rows")
    if api_rows is None:
        return _ok(
            c,
            "no second source supplied for this dataset; agreement not exercised",
            0,
        )

    def index(rows):
        return {
            (r["indicator_code"], r["breakdown_code"], r["period"]): r["value"]
            for r in rows if r.get("value") is not None
        }

    sheet, api = index(ctx["rows"]), index(api_rows)
    shared = sheet.keys() & api.keys()
    if not shared:
        return _bad(
            c,
            "the two sources share no comparable cell, so nothing was checked. "
            "That is a join failure, not agreement.",
            [{"_problem": "no overlapping (indicator, breakdown, period)"}],
            0,
        )

    offenders = []
    for key in sorted(shared):
        gap = abs(sheet[key] - api[key])
        if gap > SOURCE_AGREEMENT_TOLERANCE:
            offenders.append({
                "indicator_code": key[0], "breakdown_code": key[1],
                "period": key[2], "value": sheet[key],
                "_problem": (
                    f"spreadsheet {sheet[key]:.4f} against API {api[key]:.4f}, "
                    f"a difference of {gap:.4f}"
                ),
            })
    if offenders:
        return _bad(
            c,
            f"{len(offenders)} of {len(shared)} shared cells differ between the "
            f"published spreadsheet and the PX-Web API by more than "
            f"{SOURCE_AGREEMENT_TOLERANCE}. One of the two readings is wrong "
            "and this check cannot say which.",
            offenders, len(shared),
        )
    return _ok(
        c,
        f"all {len(shared)} cells shared with the PX-Web API agree within "
        f"{SOURCE_AGREEMENT_TOLERANCE} (the API rounds to one decimal place)",
        len(shared),
    )


def _cross_alignment(c: Contract, ctx: dict) -> CheckResult:
    rows = ctx["rows"]
    cpi_rows = ctx.get("cpi_rows")
    if cpi_rows is None:
        return _ok(c, "no CPI vintage supplied; join not exercised", 0)

    cpi_years = {
        r["period"] for r in cpi_rows
        if r["indicator_code"] == "cpi_annual_avg_2010_100"
        and r["breakdown_code"] == "georgia" and r.get("value") is not None
    }
    cpi_months = {
        r["period"] for r in cpi_rows
        if r["indicator_code"] == "cpi_2010_100"
        and r["breakdown_code"] == "georgia" and r.get("value") is not None
    }
    wage_quarters = {
        r["period"] for r in rows
        if r["unit"] == "GEL" and _quarterly(r["period"])
        and r.get("value") is not None
    }
    if wage_quarters:
        # A quarter can only be deflated if all three of its months are
        # published; averaging two of them would compare a partial quarter's
        # prices with a full quarter's wages.
        unmatched = sorted(
            q for q in wage_quarters
            if not all(
                f"{q[:4]}-{month:02d}" in cpi_months
                for month in range((int(q[-1]) - 1) * 3 + 1, int(q[-1]) * 3 + 1)
            )
        )
        if unmatched:
            return _bad(
                c,
                f"{len(unmatched)} wage quarters have no complete three-month "
                "CPI window to deflate against: " + ", ".join(unmatched[:8])
                + ". Real-terms figures for those quarters cannot be computed "
                "and must not be shown.",
                [{"period": q, "_problem": "incomplete CPI quarter"}
                 for q in unmatched],
                len(wage_quarters),
            )
        return _ok(
            c,
            f"all {len(wage_quarters)} wage quarters join to a complete "
            "three-month CPI window",
            len(wage_quarters),
        )

    wage_years = {
        r["period"] for r in rows
        if r["unit"] == "GEL" and _annual(r["period"]) and r.get("value") is not None
    }
    if not wage_years:
        return _ok(c, "dataset has no Lari-era annual wage values to join", 0)

    unmatched = sorted(y for y in wage_years if y not in cpi_years)
    if unmatched:
        return _bad(
            c,
            f"{len(unmatched)} Lari-era wage years have no annual-average CPI to "
            "deflate against: " + ", ".join(unmatched) + ". Real-terms figures "
            "for those years cannot be computed and must not be shown.",
            [{"period": y, "_problem": "no CPI annual average"} for y in unmatched],
            len(wage_years),
        )
    return _ok(
        c,
        f"all {len(wage_years)} Lari-era wage years join to a CPI annual average",
        len(wage_years),
    )


CONTRACTS: list[Contract] = [
    Contract("SCHEMA", "Expected schema present",
             "A silently renamed or dropped column produces empty analytics "
             "rather than an error.", _schema),
    Contract("KEY_UNIQUE", "Composite-key uniqueness",
             "dataset+indicator+breakdown+period+unit+vintage must address "
             "exactly one observation, or every aggregate double-counts.",
             _uniqueness),
    Contract("COVERAGE", "Period coverage without gaps",
             "A missing year is invisible in a chart but doubles the interval of "
             "any growth rate computed across it.", _coverage),
    Contract("RANGE", "Value range plausibility",
             "Negative wages and 1000x figures are defects, and they are the "
             "shape a unit error takes.", _value_range),
    Contract("CURRENCY_ERA", "Unit and currency-era consistency",
             "Georgia used Rouble, Coupon, Thousand Coupon and Lari between 1991 "
             "and 1995. The workbook puts them in adjacent columns.",
             _currency_era),
    Contract("TEMPORAL", "Temporal sanity of consecutive periods",
             "A 10x or 1000x step inside one currency era is a unit shift or a "
             "decimal-separator mistake, not an economic event.", _temporal_sanity),
    Contract("PRELIM", "Preliminary-flag preservation",
             "The '**' marker tells a reader the figure will move. Stripping it "
             "is a data-quality regression that no value check would catch.",
             _preliminary),
    Contract("PARSE", "Numeric parse integrity",
             "'…' means not published. Coercing it to 0 fabricates a statistic "
             "and drags every average down.", _parse_integrity),
    Contract("JOIN", "Cross-dataset period alignment",
             "Deflating wages by CPI requires both series to cover the same "
             "years; a partial join silently shortens the real-terms chart.",
             _cross_alignment),
    Contract("SOURCE_AGREEMENT", "Agreement with the PX-Web API",
             "The same survey is published twice, as a spreadsheet and as an "
             "API. A parser reading the wrong column passes every other check "
             "and fails this one.", _source_agreement),
    Contract("IDENTITY", "Published identities between measures",
             "The source states relationships between its own rows. Checking "
             "them catches values read into the wrong row, which every "
             "single-value check passes.", _identity),
]

CONTRACTS_BY_CODE = {c.code: c for c in CONTRACTS}


# Checks that are red on the committed data because the published statistics
# really are like that. Each one is a limitation the analytics has to respect,
# and tuning the check until the page went green would hide it. The test suite
# asserts that nothing fails which is not listed here, so this table is the
# only way a red check is allowed to exist.
KNOWN_FAILURES: dict[tuple[str, str], str] = {
    ("earnings_annual", "JOIN"):
        "The CPI series begins in 2000 and earnings begin in 1995, so wages "
        "for 1995-1999 cannot be deflated at all. Those five years are shown "
        "as n/a rather than estimated.",
    ("earnings_by_sex", "JOIN"):
        "Same five undeflatable years as the headline earnings series.",
    ("earnings_by_activity", "JOIN"):
        "Same five undeflatable years as the headline earnings series.",
    ("labour_force_by_region", "COVERAGE"):
        "Geostat published the hired / self-employed / not-identified split by "
        "region up to 2009, stopped for 2010-2019, and resumed in 2020. The "
        "core indicators - employed, unemployed, and the three rates - are "
        "complete across 2003-2025; only the employment-status split has the "
        "hole, and it is the source's, not the parser's.",
    ("household_income", "TEMPORAL"):
        "Property disposal and property income are lumpy survey categories: a "
        "single household in a regional sample selling land moves the regional "
        "monthly average by an order of magnitude. Four steps are flagged and "
        "all four are published figures, not parse errors.",
    ("gender_pay_gap", "TEMPORAL"):
        "The adjusted hourly gap for service and sales workers falls from "
        "5.0% to 0.25% between 2023 and 2024. It is flagged and unexplained: "
        "treat that single cell with care rather than assuming either a defect "
        "or a real convergence.",
    ("tourism_by_region", "COVERAGE"):
        "The visitor survey was suspended from 2020-Q2 to 2021-Q4. The seven "
        "missing quarters are the pandemic, and any growth rate computed "
        "across them would silently span two years.",
    ("tourism_by_region", "TEMPORAL"):
        "Declared hotel guests in Kakheti rise 10.9x between 2009 and 2010. "
        "Whether that is a real tourism boom or a change in who declared is "
        "not stated in the file, so the check is left red.",
}


def known_failure(dataset_id: str, code: str) -> str:
    """Why this red check is expected, or '' if it is a genuine surprise."""
    return KNOWN_FAILURES.get((dataset_id, code), "")


def run_contracts(
    rows: list[dict],
    *,
    dataset_id: str = "",
    cpi_rows: list[dict] | None = None,
    prior_rows: list[dict] | None = None,
    api_rows: list[dict] | None = None,
) -> list[CheckResult]:
    ctx = {
        "rows": rows, "dataset_id": dataset_id,
        "cpi_rows": cpi_rows, "prior_rows": prior_rows,
        "api_rows": api_rows,
    }
    schema = CONTRACTS_BY_CODE["SCHEMA"].run(ctx)
    results = [schema]
    for contract in CONTRACTS:
        if contract.code == "SCHEMA":
            continue
        if not schema.passed:
            # SCHEMA gates everything downstream. A check that reads a field
            # that is no longer there cannot pass, and it must not crash the
            # run either - a broken schema is one defect, not nine.
            results.append(CheckResult(
                contract.code, contract.title, contract.why, False,
                "not evaluated: the schema check failed first, so this check "
                "would be reading fields that are not present",
                [], 0, skipped=True,
            ))
            continue
        results.append(contract.run(ctx))
    return results


def pass_rate(results: list[CheckResult]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r.passed) / len(results)


def dataset_note(dataset_id: str) -> str:
    adapter = ADAPTERS.get(dataset_id)
    return adapter.note if adapter else ""
