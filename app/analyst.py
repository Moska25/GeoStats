"""Grounded analyst. No LLM, no API key, no network.

A deterministic intent router over a closed set of approved metric functions.
It parses a question into (intent, dataset, periods, breakdown), executes one
approved metric, and returns an answer that always carries its provenance:
dataset, indicator, breakdown, period, unit, vintage id, preliminary status,
the formula used, and the source URL.

The headline feature is the refusal. Geostat publishes a mean and a median. It
does not publish a distribution, so a 90th percentile cannot be reconstructed;
it does not publish occupation crossed with region, so that cell does not
exist; it publishes gross pay, so take-home cannot be derived without a tax
model this project does not have. Every one of those questions gets a specific
explanation of what is missing rather than a plausible-looking number.

A system that answers everything is not grounded. It is guessing politely.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from . import db, metrics
from .adapters import ADAPTERS, GEL_ERA_START, currency_for_year, currency_name

CPI_DATASET = "cpi_2010_base"
CPI_INDICATOR = "cpi_annual_avg_2010_100"
CPI_BREAKDOWN = "georgia"
WAGE_DATASET = "earnings_annual"
WAGE_INDICATOR = "avg_monthly_nominal_earnings"
MEDIAN_DATASET = "median_earnings"
MEDIAN_INDICATOR = "median_monthly_earnings"
REGION_DATASET = "earnings_by_region"

GROSS_CAVEAT = (
    "Gross, before personal income tax. Computed as the earnings fund divided "
    "by the average number of paid employees divided by months - not take-home "
    "pay and not a typical person's salary."
)


@dataclass
class Answer:
    kind: str                       # "answer" | "refusal" | "unmatched"
    question: str
    intent: str
    headline: str = ""
    formula: str = ""
    explanation: str = ""
    caveat: str = ""
    provenance: list[dict] = field(default_factory=list)
    table: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def is_refusal(self) -> bool:
        return self.kind == "refusal"


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def _cpi(conn) -> dict[str, float]:
    return db.value_map(conn, CPI_DATASET, CPI_INDICATOR, CPI_BREAKDOWN)


def _wage(conn, breakdown: str = "total") -> dict[str, float]:
    return db.value_map(conn, WAGE_DATASET, WAGE_INDICATOR, breakdown)


def _median(conn, breakdown: str = "total") -> dict[str, float]:
    return db.value_map(conn, MEDIAN_DATASET, MEDIAN_INDICATOR, breakdown)


def _prov(conn, dataset_id: str, indicator: str, breakdown: str,
          period: str | list[str], unit: str) -> dict:
    vintage_id = db.latest_vintage_id(conn, dataset_id) or ""
    prelim = db.preliminary_periods(conn, dataset_id, vintage_id=vintage_id)
    periods = [period] if isinstance(period, str) else list(period)
    adapter = ADAPTERS[dataset_id]
    return {
        "dataset_id": dataset_id,
        "dataset_title": adapter.title,
        "indicator_code": indicator,
        "breakdown_code": breakdown,
        "period": ", ".join(periods),
        "unit": unit,
        "vintage_id": vintage_id,
        "is_preliminary": any(p in prelim for p in periods),
        "source_url": adapter.url,
        "source_page": adapter.source_page,
    }


def _years(question: str) -> list[str]:
    """Years mentioned, ascending.

    Ascending regardless of the order they were typed: "real earnings in 2024
    with 2010 as the base" and "from 2010 to 2024" must resolve to the same
    base year, and a base later than the comparison year is never what anyone
    means.
    """
    # Deliberately wide: a year outside the published range must reach an
    # intent and be refused there, not be silently dropped so that the question
    # gets answered about some other year.
    return sorted(set(re.findall(r"\b((?:18|19|20)\d{2})\b", question)))


def _amount(question: str) -> float | None:
    m = re.search(
        r"(\d[\d\s,]*\.?\d*)\s*(?:gel|lari|ლარი)", question
    )
    if not m:
        m = re.search(r"\b(\d{3,7}(?:\.\d+)?)\b(?!\s*(?:year|w))", question)
        if not m:
            return None
        if re.fullmatch(r"(19|20)\d{2}", m.group(1)):
            return None
    try:
        return float(m.group(1).replace(",", "").replace(" ", ""))
    except ValueError:
        return None


def _latest_year(values: dict[str, float]) -> str | None:
    years = sorted(values)
    return years[-1] if years else None


def _fmt(value: float, places: int = 2) -> str:
    return f"{value:,.{places}f}"


# --------------------------------------------------------------------------
# refusals - checked before anything else
# --------------------------------------------------------------------------

REFUSALS = [
    (
        "distribution_percentile",
        re.compile(
            r"\b(percentile|quartile|decile|p90|p10|90th|75th|25th|top\s*\d+\s*%"
            r"|bottom\s*\d+\s*%|distribution|histogram|spread of salaries"
            r"|how many (people|employees) earn)\b"
        ),
        "Geostat publishes a mean and a median for these series, and nothing "
        "else about the shape of the distribution.",
        "A percentile cannot be reconstructed from an average and a midpoint. "
        "Two populations with identical mean and median can have completely "
        "different tails. Deriving a 90th percentile here would be an invented "
        "number wearing an official source URL.",
        ["individual or grouped microdata", "published percentile tables"],
    ),
    (
        "occupation_cross",
        re.compile(r"\b(occupation|profession|job title|by role|programmer|"
                   r"teacher salary in|doctor salary in|nurse|engineer)\b"),
        "Occupation is not a dimension in any dataset ingested here.",
        "The published breakdowns are activity (NACE), region, sex, ownership "
        "and business sector. Occupation crossed with region does not exist in "
        "these files, so the cell you are asking for has no source value. It "
        "would have to be modelled, and a model is not a statistic.",
        ["occupation-coded earnings survey (e.g. a structure-of-earnings survey)"],
    ),
    (
        "net_pay",
        re.compile(r"\b(net|after tax|after-tax|take[- ]home|in hand|"
                   r"post[- ]tax|deduction)\b"),
        "These figures are gross, before personal income tax.",
        "Converting gross to net needs the income-tax rules in force each year "
        "plus pension-contribution treatment. GeoStats ingests statistics, not "
        "tax law, so it will not silently apply a rate and present the result "
        "as official.",
        ["year-by-year personal income tax and pension contribution rules"],
    ),
    (
        "forecast",
        re.compile(r"\b(forecast|predict|projection|will be|next year|"
                   r"expected in 20[3-9]\d|20[3-9]\d)\b"),
        "GeoStats reports what was published; it does not forecast.",
        "Every number in this application is traceable to a committed vintage "
        "of a Geostat workbook. A forecast has no vintage, no sha256 and no "
        "source URL, so it cannot be shown next to figures that do.",
        ["an explicit forecasting model, out of scope for this project"],
    ),
    (
        "employer_level",
        re.compile(r"\b(at [A-Z][a-z]+ (bank|company)|my company|specific "
                   r"employer|which company|company pays)\b"),
        "Employer-level pay is confidential and is not published.",
        "Statistical disclosure control exists precisely to stop aggregate "
        "releases being resolved back to individual firms.",
        ["confidential enterprise-level microdata"],
    ),
    (
        "median_by_region",
        re.compile(r"\bmedian\b.*\b(region|tbilisi|adjara|imereti|kakheti|guria)\b"
                   r"|\b(region|tbilisi|adjara)\b.*\bmedian\b"),
        "Median earnings are published by economic activity only, not by region.",
        "The regional file carries the mean alone. Taking the regional mean and "
        "calling it a median would misstate a skewed distribution by several "
        "hundred lari.",
        ["median earnings cross-tabulated by region"],
    ),
    (
        "monthly_wage",
        re.compile(r"\b(monthly|month by month|each month|per month in \w+ 20)\b"
                   r".*\b(wage|earning|salary)\b.*\b(series|trend|by month)\b"),
        "The earnings series ingested here are annual.",
        "Geostat publishes quarterly earnings as a separate release that this "
        "project has not ingested. Interpolating twelve months out of an annual "
        "average would fabricate seasonality that is not in the source.",
        ["the quarterly earnings release (listed in TODO.md as a future phase)"],
    ),
]


def _refuse(question: str, code: str, headline: str, explanation: str,
            missing: list[str]) -> Answer:
    return Answer(
        kind="refusal", question=question, intent=code,
        headline=headline, explanation=explanation, missing=missing,
        formula="no metric executed",
        caveat="A refusal is the correct answer when the aggregates cannot "
               "support the question.",
    )


# --------------------------------------------------------------------------
# intents
# --------------------------------------------------------------------------

def _intent_purchasing_power(conn, q: str, years: list[str]) -> Answer | None:
    if not re.search(r"\b(worth|purchasing power|equivalent|buy|same as|"
                     r"in today'?s money|adjusted for inflation.*\d)\b", q):
        return None
    amount = _amount(q)
    if amount is None or len(years) < 1:
        return None
    cpi = _cpi(conn)
    y_from = years[0]
    y_to = years[1] if len(years) > 1 else _latest_year(cpi)
    if y_from not in cpi or y_to not in cpi:
        return _unavailable(q, "purchasing_power", cpi, [y_from, y_to])
    equivalent = metrics.preserve_purchasing_power(amount, cpi[y_from], cpi[y_to])
    inflation = metrics.cumulative_inflation(cpi[y_from], cpi[y_to])
    return Answer(
        kind="answer", question=q, intent="purchasing_power",
        headline=(
            f"{_fmt(amount)} GEL in {y_from} needs {_fmt(equivalent)} GEL in "
            f"{y_to} to buy the same basket."
        ),
        formula=(
            f"equivalent = amount * (CPI_{y_to} / CPI_{y_from}) = "
            f"{_fmt(amount)} * ({cpi[y_to]:.4f} / {cpi[y_from]:.4f})"
        ),
        explanation=(
            f"Cumulative inflation between {y_from} and {y_to} was "
            f"{inflation:+.1f}%. Both CPI figures are annual averages of the "
            "twelve published monthly indices."
        ),
        caveat=(
            "The CPI measures a national average basket. A household whose "
            "spending is weighted differently faces a different rate."
        ),
        provenance=[
            _prov(conn, CPI_DATASET, CPI_INDICATOR, CPI_BREAKDOWN,
                  [y_from, y_to], "index_2010_100"),
        ],
        table=[
            {"label": f"CPI {y_from}", "value": f"{cpi[y_from]:.4f}"},
            {"label": f"CPI {y_to}", "value": f"{cpi[y_to]:.4f}"},
            {"label": "Cumulative inflation", "value": f"{inflation:+.2f}%"},
            {"label": f"Equivalent in {y_to}", "value": f"{_fmt(equivalent)} GEL"},
        ],
    )


def _intent_inflation(conn, q: str, years: list[str]) -> Answer | None:
    if not re.search(r"\b(inflation|price[s]? (rise|rose|increase|change)|"
                     r"cost of living)\b", q):
        return None
    cpi = _cpi(conn)
    if len(years) < 2:
        if len(years) == 1:
            y_to = years[0]
            y_from = str(int(y_to) - 1)
        else:
            return None
    else:
        y_from, y_to = years[0], years[1]
    if y_from not in cpi or y_to not in cpi:
        return _unavailable(q, "cumulative_inflation", cpi, [y_from, y_to])
    total = metrics.cumulative_inflation(cpi[y_from], cpi[y_to])
    span = int(y_to) - int(y_from)
    annualised = (
        metrics.annualised_inflation(cpi[y_from], cpi[y_to], span) if span > 0 else total
    )
    return Answer(
        kind="answer", question=q, intent="cumulative_inflation",
        headline=f"Prices rose {total:+.1f}% between {y_from} and {y_to}.",
        formula=(
            f"inflation = (CPI_{y_to} / CPI_{y_from} - 1) * 100 = "
            f"({cpi[y_to]:.4f} / {cpi[y_from]:.4f} - 1) * 100"
        ),
        explanation=(
            f"That is {annualised:+.2f}% a year compounded over {span} year(s), "
            "on the CPI with 2010 annual average = 100."
        ),
        caveat="CPI annual averages are derived here from the twelve published "
               "monthly indices; a year missing any month is excluded.",
        provenance=[_prov(conn, CPI_DATASET, CPI_INDICATOR, CPI_BREAKDOWN,
                          [y_from, y_to], "index_2010_100")],
        table=[
            {"label": f"CPI {y_from}", "value": f"{cpi[y_from]:.4f}"},
            {"label": f"CPI {y_to}", "value": f"{cpi[y_to]:.4f}"},
            {"label": "Cumulative", "value": f"{total:+.2f}%"},
            {"label": "Annualised", "value": f"{annualised:+.2f}%"},
        ],
    )


def _intent_real_wage(conn, q: str, years: list[str]) -> Answer | None:
    if not re.search(r"\b(real|inflation[- ]adjusted|constant price|in real terms)\b", q):
        return None
    wage, cpi = _wage(conn), _cpi(conn)
    deflatable = sorted(y for y in wage if y in cpi)
    if not deflatable:
        return None
    y_base = years[0] if years and years[0] in cpi and years[0] in wage else deflatable[0]
    y_now = (
        years[1] if len(years) > 1 and years[1] in wage
        else _latest_year({y: wage[y] for y in deflatable})
    )
    if y_now not in cpi or y_now not in wage:
        return _unavailable(q, "real_earnings_index", cpi, [y_base, y_now])
    index = metrics.real_earnings_index(wage[y_now], wage[y_base], cpi[y_now], cpi[y_base])
    nom_index = metrics.nominal_index(wage[y_now], wage[y_base])
    real_gel = metrics.deflate(wage[y_now], cpi[y_now], cpi[y_base])
    return Answer(
        kind="answer", question=q, intent="real_earnings_index",
        headline=(
            f"Real average earnings in {y_now} were {index:.1f} on a "
            f"{y_base} = 100 base ({index - 100:+.1f}%)."
        ),
        formula=(
            f"index = (W_{y_now} / W_{y_base}) / (CPI_{y_now} / CPI_{y_base}) * 100 = "
            f"({wage[y_now]:.2f} / {wage[y_base]:.2f}) / "
            f"({cpi[y_now]:.4f} / {cpi[y_base]:.4f}) * 100"
        ),
        explanation=(
            f"Nominal earnings rose to {nom_index:.1f} on the same base, so "
            f"{nom_index - index:.1f} index points of the nominal gain were "
            f"prices rather than pay. In {y_base} prices the {y_now} average is "
            f"{_fmt(real_gel)} GEL."
        ),
        caveat=GROSS_CAVEAT,
        provenance=[
            _prov(conn, WAGE_DATASET, WAGE_INDICATOR, "total", [y_base, y_now], "GEL"),
            _prov(conn, CPI_DATASET, CPI_INDICATOR, CPI_BREAKDOWN,
                  [y_base, y_now], "index_2010_100"),
        ],
        table=[
            {"label": f"Nominal {y_base}", "value": f"{_fmt(wage[y_base])} GEL"},
            {"label": f"Nominal {y_now}", "value": f"{_fmt(wage[y_now])} GEL"},
            {"label": "Nominal index", "value": f"{nom_index:.1f}"},
            {"label": "Real index", "value": f"{index:.1f}"},
            {"label": f"{y_now} in {y_base} prices", "value": f"{_fmt(real_gel)} GEL"},
        ],
    )


def _intent_mean_vs_median(conn, q: str, years: list[str]) -> Answer | None:
    if not re.search(r"\b(median|mean vs|average vs|typical|middle|skew|gap "
                     r"between (the )?(mean|average))\b", q):
        return None
    wage, median = _wage(conn), _median(conn)
    common = sorted(set(wage) & set(median))
    if not common:
        return None
    year = years[0] if years and years[0] in common else common[-1]
    if year not in common:
        return _unavailable(q, "mean_median_gap", {y: 1 for y in common}, [year])
    gap = metrics.mean_median_gap(wage[year], median[year])
    prelim = db.preliminary_periods(conn, WAGE_DATASET)
    return Answer(
        kind="answer", question=q, intent="mean_median_gap",
        headline=(
            f"In {year} the mean was {_fmt(gap.mean)} GEL and the median "
            f"{_fmt(gap.median)} GEL - the mean sits {gap.gap_pct:.1f}% higher."
        ),
        formula=f"gap = (mean / median - 1) * 100 = ({gap.mean:.2f} / {gap.median:.2f} - 1) * 100",
        explanation=(
            f"The middle paid employee earned {_fmt(gap.gap_gel)} GEL a month "
            f"less than the average. The mean is pulled up by high earners; the "
            "median is the better answer to 'what does a normal job pay'. Note "
            "the two come from different sources: the mean from the enterprise "
            "survey, the median from Revenue Service administrative records."
        ),
        caveat=gap.caveat,
        provenance=[
            _prov(conn, WAGE_DATASET, WAGE_INDICATOR, "total", year, "GEL"),
            _prov(conn, MEDIAN_DATASET, MEDIAN_INDICATOR, "total", year, "GEL"),
        ],
        table=[
            {"label": f"Mean {year}", "value": f"{_fmt(gap.mean)} GEL"
                + (" (preliminary)" if year in prelim else "")},
            {"label": f"Median {year}", "value": f"{_fmt(gap.median)} GEL"},
            {"label": "Gap", "value": f"{_fmt(gap.gap_gel)} GEL"},
            {"label": "Mean / median", "value": f"{gap.ratio:.3f}"},
        ],
    )


def _intent_region(conn, q: str, years: list[str]) -> Answer | None:
    if not re.search(r"\b(region|regional|tbilisi|adjara|imereti|kakheti|guria|"
                     r"kvemo kartli|shida kartli|samegrelo|racha|highest[- ]paid|"
                     r"best[- ]paid|where.*(paid|earn))\b", q):
        return None
    vintage_id = db.latest_vintage_id(conn, REGION_DATASET)
    rows = db.breakdowns(conn, REGION_DATASET, WAGE_INDICATOR, vintage_id=vintage_id)
    values: dict[str, tuple[str, float]] = {}
    year = None
    all_years = sorted({
        r["period"] for r in conn.execute(
            "SELECT DISTINCT period FROM observations WHERE dataset_id=? AND vintage_id=?",
            (REGION_DATASET, vintage_id)).fetchall()
    })
    year = years[0] if years and years[0] in all_years else (all_years[-1] if all_years else None)
    if year is None:
        return None
    for r in rows:
        if r["breakdown_code"] == "total":
            continue
        vm = db.value_map(conn, REGION_DATASET, WAGE_INDICATOR, r["breakdown_code"],
                          vintage_id=vintage_id)
        if year in vm:
            values[r["breakdown_code"]] = (r["breakdown_label"].strip(), vm[year])
    if not values:
        return _unavailable(q, "region_ranking", {y: 1 for y in all_years}, [year])
    ranked = sorted(values.values(), key=lambda t: -t[1])
    national = db.value_map(conn, REGION_DATASET, WAGE_INDICATOR, "total",
                            vintage_id=vintage_id).get(year)
    top, bottom = ranked[0], ranked[-1]
    return Answer(
        kind="answer", question=q, intent="region_ranking",
        headline=(
            f"In {year} the highest regional average was {top[0]} at "
            f"{_fmt(top[1])} GEL; the lowest was {bottom[0]} at {_fmt(bottom[1])} GEL."
        ),
        formula="direct lookup of the published regional means, ranked descending",
        explanation=(
            f"The national average that year was {_fmt(national)} GEL. "
            f"{top[0]} is {top[1] / bottom[1]:.2f}x {bottom[0]}."
            if national else f"{top[0]} is {top[1] / bottom[1]:.2f}x {bottom[0]}."
        ),
        caveat=(
            "Enterprises are counted at the location of their head office, "
            "which shifts pay toward Tbilisi relative to where the work is "
            "physically done. " + GROSS_CAVEAT
        ),
        provenance=[_prov(conn, REGION_DATASET, WAGE_INDICATOR, "all regions",
                          year, "GEL")],
        table=[{"label": name, "value": f"{_fmt(v)} GEL"} for name, v in ranked],
    )


def _intent_gender_gap(conn, q: str, years: list[str]) -> Answer | None:
    if not re.search(r"\b(gender|sex|women|men|female|male|pay gap)\b", q):
        return None
    women = _wage(conn, "sex.women")
    men = _wage(conn, "sex.men")
    common = sorted(set(women) & set(men))
    if not common:
        return None
    year = years[0] if years and years[0] in common else common[-1]
    gap_pct = (1 - women[year] / men[year]) * 100
    return Answer(
        kind="answer", question=q, intent="gender_gap",
        headline=(
            f"In {year} women averaged {_fmt(women[year])} GEL and men "
            f"{_fmt(men[year])} GEL - a gap of {gap_pct:.1f}%."
        ),
        formula=f"gap = (1 - W_women / W_men) * 100 = (1 - {women[year]:.2f} / {men[year]:.2f}) * 100",
        explanation=(
            "This is an unadjusted gap between two averages. It does not control "
            "for hours, activity, seniority or occupation, so it is not a "
            "measure of unequal pay for the same work."
        ),
        caveat=GROSS_CAVEAT,
        provenance=[
            _prov(conn, WAGE_DATASET, WAGE_INDICATOR, "sex.women", year, "GEL"),
            _prov(conn, WAGE_DATASET, WAGE_INDICATOR, "sex.men", year, "GEL"),
        ],
        table=[
            {"label": f"Women {year}", "value": f"{_fmt(women[year])} GEL"},
            {"label": f"Men {year}", "value": f"{_fmt(men[year])} GEL"},
            {"label": "Unadjusted gap", "value": f"{gap_pct:.1f}%"},
        ],
    )


def _intent_growth(conn, q: str, years: list[str]) -> Answer | None:
    if not re.search(r"\b(grow\w*|rise|rose|risen|increase\w*|change\w*|"
                     r"how much more|compared to|since)\b", q):
        return None
    if len(years) < 2:
        return None
    wage, cpi = _wage(conn), _cpi(conn)
    y0, y1 = years[0], years[1]
    if y0 not in wage or y1 not in wage:
        return _unavailable(q, "growth", wage, [y0, y1])
    nominal = metrics.yoy_growth(wage[y0], wage[y1])
    real = (
        metrics.real_growth(wage[y0], wage[y1], cpi[y0], cpi[y1])
        if y0 in cpi and y1 in cpi else None
    )
    real_text = (
        f"{real:+.1f}% in real terms" if real is not None
        else "real terms unavailable: no CPI annual average for one of these years"
    )
    return Answer(
        kind="answer", question=q, intent="growth",
        headline=(
            f"Average nominal earnings went from {_fmt(wage[y0])} GEL in {y0} to "
            f"{_fmt(wage[y1])} GEL in {y1}: {nominal:+.1f}% nominal, {real_text}."
        ),
        formula=(
            f"nominal = (W_{y1} / W_{y0} - 1) * 100; "
            f"real = ((W_{y1} / W_{y0}) / (CPI_{y1} / CPI_{y0}) - 1) * 100"
        ),
        explanation=(
            "The difference between the two is inflation. Quoting the nominal "
            "figure alone overstates how much better off employees are."
        ),
        caveat=GROSS_CAVEAT,
        provenance=[
            _prov(conn, WAGE_DATASET, WAGE_INDICATOR, "total", [y0, y1], "GEL"),
            _prov(conn, CPI_DATASET, CPI_INDICATOR, CPI_BREAKDOWN, [y0, y1],
                  "index_2010_100"),
        ],
        table=[
            {"label": f"Nominal {y0}", "value": f"{_fmt(wage[y0])} GEL"},
            {"label": f"Nominal {y1}", "value": f"{_fmt(wage[y1])} GEL"},
            {"label": "Nominal growth", "value": f"{nominal:+.2f}%"},
            {"label": "Real growth",
             "value": f"{real:+.2f}%" if real is not None else "not deflatable"},
        ],
    )


def _intent_level(conn, q: str, years: list[str]) -> Answer | None:
    """Plain 'what was the average wage in YEAR'. Also the currency-era guard."""
    if not re.search(r"\b(average|mean|wage|salary|earn|pay|earnings)\b", q):
        return None
    wage = _wage(conn)
    year = years[0] if years else _latest_year(wage)
    if year is None:
        return None
    if year not in wage:
        return _unavailable(q, "earnings_level", wage, [year])
    unit = currency_for_year(int(year))
    prelim = year in db.preliminary_periods(conn, WAGE_DATASET)
    era_note = ""
    if unit != "GEL":
        era_note = (
            f" Note the unit: in {year} Georgia's currency was the "
            f"{currency_name(unit)}, not the Lari. This value cannot be "
            "compared with any post-1995 figure, and GeoStats will not convert "
            "it - no official conversion series is published in these files."
        )
    return Answer(
        kind="answer", question=q, intent="earnings_level",
        headline=(
            f"Average monthly nominal earnings in {year}: {_fmt(wage[year])} "
            f"{unit}." + (" (preliminary)" if prelim else "")
        ),
        formula="direct lookup: earnings fund / average paid employees / months",
        explanation=(
            "Published by Geostat as the average over paid employees."
            + era_note
            + (
                " This figure is marked '**' in the source workbook, meaning "
                "preliminary: it is expected to move in a later release."
                if prelim else ""
            )
        ),
        caveat=GROSS_CAVEAT,
        provenance=[_prov(conn, WAGE_DATASET, WAGE_INDICATOR, "total", year, unit)],
        table=[
            {"label": f"Average {year}", "value": f"{_fmt(wage[year])} {unit}"},
            {"label": "Currency era", "value": currency_name(unit)},
            {"label": "Preliminary", "value": "yes" if prelim else "no"},
        ],
    )


def _unavailable(q: str, intent: str, available: dict, wanted: list[str]) -> Answer:
    years = sorted(available)
    span = f"{years[0]}-{years[-1]}" if years else "none"
    return Answer(
        kind="refusal", question=q, intent=intent,
        headline=f"No published value for {', '.join(wanted)} in this series.",
        explanation=(
            f"The committed vintage covers {span}. GeoStats will not "
            "extrapolate outside the published range."
        ),
        formula="no metric executed",
        missing=[f"published values for {', '.join(wanted)}"],
        caveat="A refusal is the correct answer when the source does not cover "
               "the period asked for.",
    )


INTENTS = [
    ("purchasing_power", _intent_purchasing_power),
    ("real_earnings_index", _intent_real_wage),
    ("cumulative_inflation", _intent_inflation),
    ("gender_gap", _intent_gender_gap),
    ("region_ranking", _intent_region),
    ("mean_median_gap", _intent_mean_vs_median),
    ("growth", _intent_growth),
    ("earnings_level", _intent_level),
]

APPROVED_METRICS = [
    ("metrics.preserve_purchasing_power", "amount * (CPI_to / CPI_from)"),
    ("metrics.real_earnings_index", "(W_t / W_base) / (CPI_t / CPI_base) * 100"),
    ("metrics.deflate", "nominal * (CPI_base / CPI_t)"),
    ("metrics.cumulative_inflation", "(CPI_to / CPI_from - 1) * 100"),
    ("metrics.annualised_inflation", "((CPI_to / CPI_from) ** (1/years) - 1) * 100"),
    ("metrics.mean_median_gap", "(mean / median - 1) * 100"),
    ("metrics.yoy_growth", "(current / previous - 1) * 100"),
    ("metrics.real_growth", "((W_t / W_p) / (CPI_t / CPI_p) - 1) * 100"),
    ("metrics.nominal_index", "W_t / W_base * 100"),
]


def ask(conn: sqlite3.Connection, question: str) -> Answer:
    """Route one question to exactly one approved metric, or refuse."""
    q = (question or "").strip()
    if not q:
        return Answer(
            kind="unmatched", question="", intent="empty",
            headline="Ask a question.",
            explanation="Try one of the worked examples below.",
        )
    lower = q.lower()

    for code, pattern, headline, explanation, missing in REFUSALS:
        if pattern.search(lower):
            return _refuse(q, code, headline, explanation, missing)

    years = _years(lower)
    for _name, handler in INTENTS:
        answer = handler(conn, lower, years)
        if answer is not None:
            answer.question = q
            return answer

    return Answer(
        kind="unmatched", question=q, intent="no_match",
        headline="No approved metric matches that question.",
        explanation=(
            "This analyst is a fixed router over "
            f"{len(APPROVED_METRICS)} approved metric functions, not a language "
            "model. If a question does not map onto one of them it gets no "
            "answer rather than an invented one. The worked examples below show "
            "the shapes it does handle."
        ),
        formula="no metric executed",
        caveat="Refusing to guess is the design, not a gap.",
    )


EXAMPLES = [
    "What was the average monthly wage in 2024?",
    "What was the average wage in 1993?",
    "How much has the average wage grown from 2018 to 2024?",
    "What are real earnings in 2024 with 2010 as the base?",
    "What is the gap between the mean and the median in 2024?",
    "What is 1000 GEL from 2015 worth in 2024?",
    "How much inflation was there between 2020 and 2024?",
    "What is the gender pay gap in 2024?",
    "Which region had the highest average pay in 2024?",
    "What is the 90th percentile salary in Georgia?",
    "What does a software engineer earn in Imereti?",
    "What is the average take-home pay after tax in 2024?",
    "What will the average wage be in 2030?",
    "What is the median wage in Adjara?",
]
