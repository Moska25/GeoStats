"""FastAPI routes. Thin on purpose - all the logic lives in importable modules.

Port 8013.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import calendar as release_calendar
from . import charts, db, geography, i18n, ingest, metrics
from .adapters import (
    ADAPTERS, GEL_ERA_START, currency_name, series_breaks, spans_a_break,
)
from .analyst import APPROVED_METRICS, EXAMPLES, ask
from .contracts import CONTRACTS, known_failure
from .faults import FAULTS, FAULTS_BY_ID, defect_report, inject
from .pxweb import PX_TABLES, list_snapshots, read_snapshot
from .refresh_all import refresh_many
from .seed import seed

BASE_DIR = Path(__file__).resolve().parent
PROJECT_NAME = "GeoStats"
PORT = 8013

# A deployed copy of this site is a read-only publication: it serves the
# vintages committed in the repository and never reaches out to Geostat. Live
# refresh is a maintainer's action, taken locally, whose result is a new
# immutable vintage to review and commit - not something a visitor can trigger.
ALLOW_REFRESH = os.environ.get("GEOSTATS_ALLOW_REFRESH") == "1"

WAGE_DATASET = "earnings_annual"
WAGE_INDICATOR = "avg_monthly_nominal_earnings"
MEDIAN_DATASET = "median_earnings"
MEDIAN_INDICATOR = "median_monthly_earnings"
CPI_DATASET = "cpi_2010_base"
CPI_INDICATOR = "cpi_annual_avg_2010_100"
REGION_DATASET = "earnings_by_region"
LABOUR_DATASET = "labour_force"
LABOUR_REGION_DATASET = "labour_force_by_region"
QUARTERLY_DATASET = "earnings_quarterly"
GPG_DATASET = "gender_pay_gap"
INCOME_DATASET = "household_income"
EXPENDITURE_DATASET = "household_expenditure"
POPULATION_DATASET = "population"
BUSINESS_DATASET = "business_demography"
TOURISM_DATASET = "tourism_by_region"

NAV = [
    ("/", "nav.overview"),
    ("/work", "nav.work"),
    ("/households", "nav.households"),
    ("/regions", "nav.regions"),
    ("/explorer", "nav.explorer"),
    ("/reliability", "nav.reliability"),
    ("/case-study", "nav.case_study"),
]

# Kept out of the primary navigation but reachable from context and the footer.
SECONDARY_NAV = [
    ("/salary", "nav.salary"),
    ("/ask", "nav.ask"),
    ("/lab", "nav.lab"),
    ("/methodology", "nav.methodology"),
]

BREAKDOWN_CHOICES = [
    ("total", "Total"),
    ("sex.women", "Women"),
    ("sex.men", "Men"),
    ("type_of_ownership.public", "Public sector"),
    ("type_of_ownership.non_public", "Non-public sector"),
    ("sector.business", "Business sector"),
    ("sector.non_business", "Non-business sector"),
]

app = FastAPI(title=PROJECT_NAME, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
# Stylesheet cache-buster: browsers hold onto /static/app.css across a restyle,
# so the mtime of the newest stylesheet rides along as ?v=.
templates.env.globals["static_v"] = str(
    int(max(p.stat().st_mtime for p in (BASE_DIR / "static").glob("*.css")))
)

if not db.DB_PATH.exists():
    seed(verbose=False)

conn = db.connect()
db.bootstrap(conn)


# --------------------------------------------------------------------------
# shell
# --------------------------------------------------------------------------

def shell(request: Request, active: str, **extra) -> dict:
    """Everything _layout.html needs, in one place."""
    lang = i18n.normalise(
        request.query_params.get("lang") or request.cookies.get("lang")
    )
    t = i18n.translator(lang)
    # The masthead carries a real dateline: a publication states when its
    # figures were pulled, and this one can, because every vintage is stamped.
    stats = db.summary(conn)
    ctx = {
        "request": request,
        "project_name": PROJECT_NAME,
        "project_tagline": t("tagline"),
        "edition_date": (stats["last_retrieved"] or "")[:10],
        "edition_vintages": stats["vintages"],
        "nav": [(href, t(key)) for href, key in NAV],
        "secondary_nav": [(href, t(key)) for href, key in SECONDARY_NAV],
        "active": active,
        "footer_note": t("footer.note"),
        "page_description": (
            "Official Georgian wage, price, labour force and household "
            "statistics from Geostat, kept as immutable vintages and checked "
            "against data contracts before anything is plotted."
        ),
        "t": t,
        "lang": lang,
        "languages": i18n.LANGUAGES,
        "lang_note": i18n.untranslated_note(lang),
        "port": PORT,
    }
    ctx.update(extra)
    return ctx


@app.exception_handler(404)
def not_found(request: Request, exc: HTTPException):
    """A wrong URL should still be a page, and still say which pages exist."""
    response = render("404.html", shell(request, "", path=request.url.path))
    response.status_code = 404
    return response


def render(name: str, ctx: dict) -> HTMLResponse:
    response = templates.TemplateResponse(ctx["request"], name, ctx)
    lang = ctx.get("lang")
    if lang:
        response.set_cookie("lang", lang, max_age=31536000, samesite="lax")
    return response


def _lang_qs(request: Request) -> str:
    lang = request.query_params.get("lang")
    return f"?lang={lang}" if lang else ""


# --------------------------------------------------------------------------
# shared data helpers
# --------------------------------------------------------------------------

def wage_map(breakdown: str = "total") -> dict[str, float]:
    return db.value_map(conn, WAGE_DATASET, WAGE_INDICATOR, breakdown)


def cpi_map() -> dict[str, float]:
    return db.value_map(conn, CPI_DATASET, CPI_INDICATOR, "georgia")


def median_map() -> dict[str, float]:
    return db.value_map(conn, MEDIAN_DATASET, MEDIAN_INDICATOR, "total")


def gel_era_years(values: dict[str, float]) -> list[str]:
    return sorted(y for y in values if int(y) >= GEL_ERA_START)


def labour_map(indicator: str, breakdown: str = "country.georgia") -> dict[str, float]:
    return db.value_map(conn, LABOUR_DATASET, indicator, breakdown)


def deflate_series(
    nominal: dict[str, float], cpi: dict[str, float], base_year: str
) -> dict[str, float]:
    """Nominal by year expressed in `base_year` prices, dropping years the CPI
    cannot reach. Dropping rather than extrapolating is the whole point: the
    CPI starts in 2000 and no amount of wanting a longer chart changes that."""
    base = cpi.get(base_year)
    if not base:
        return {}
    return {
        year: metrics.deflate(value, cpi[year], base)
        for year, value in nominal.items()
        if year in cpi
    }


def _pct_change(values: dict[str, float], first: str, last: str) -> float | None:
    if first not in values or last not in values or not values[first]:
        return None
    return (values[last] / values[first] - 1) * 100


def contract_totals() -> dict:
    row = conn.execute(
        """SELECT COUNT(*) AS n, SUM(passed) AS ok FROM contract_runs
            WHERE (dataset_id, vintage_id) IN
                  (SELECT dataset_id, vintage_id FROM vintages WHERE is_latest = 1)"""
    ).fetchone()
    total = row["n"] or 0
    ok = row["ok"] or 0
    return {"total": total, "passed": ok, "failed": total - ok,
            "rate": (ok / total * 100) if total else 0.0}


# --------------------------------------------------------------------------
# / overview
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def overview(request: Request):
    wage, cpi, median = wage_map(), cpi_map(), median_map()
    prelim = db.preliminary_periods(conn, WAGE_DATASET)
    gel_years = gel_era_years(wage)
    latest = gel_years[-1] if gel_years else None
    latest_median_year = max(median) if median else None

    base_year = "2010"
    series = metrics.build_series(
        {y: wage[y] for y in gel_years}, cpi, median,
        base_year=base_year, preliminary=prelim,
    )
    deflatable = [r for r in series if r["real_index"] is not None]

    gap = None
    if latest_median_year and latest_median_year in wage:
        gap = metrics.mean_median_gap(wage[latest_median_year], median[latest_median_year])

    # The naive-versus-honest chart: the whole published column set treated as
    # one series, next to the same data restricted to the Lari era.
    all_years = sorted(wage)
    naive = charts.line_chart(
        all_years, {"All published columns as one series": [wage[y] for y in all_years]},
        height=200, value_fmt="{:,.0f}",
    )
    honest = charts.line_chart(
        gel_years, {"Lari era only (1995 onward)": [wage[y] for y in gel_years]},
        height=200, value_fmt="{:,.0f}",
    )

    real_chart = charts.line_chart(
        [r["period"] for r in deflatable],
        {
            "Nominal index": [r["nominal_index"] for r in deflatable],
            "Real index": [r["real_index"] for r in deflatable],
        },
        height=250, value_fmt="{:,.0f}",
    )

    era_rows = [
        {"period": y, "value": wage[y],
         "unit": next(r["unit"] for r in db.series(
             conn, WAGE_DATASET, WAGE_INDICATOR, "total") if r["period"] == y)}
        for y in ["1991", "1992", "1993", "1994", "1995", "1996"] if y in wage
    ]

    # -- the labour market beside real wages -------------------------------
    # Two panels rather than one chart with two axes, for the reason /work
    # spells out: a shared pair of axes lets the choice of scales decide
    # whether the lines appear to move together.
    unemployment = labour_map("unemployment_rate_percentage")
    employment_rate = labour_map("employment_rate_percentage")
    real_by_year = deflate_series(wage, cpi, base_year)
    labour_years = [y for y in sorted(unemployment) if y in real_by_year]
    labour_panels = charts.aligned_panels(
        labour_years,
        [
            (f"Real earnings, {base_year} prices (GEL/month)",
             [real_by_year.get(y) for y in labour_years], "GEL"),
            ("Unemployment rate (%)",
             [unemployment.get(y) for y in labour_years], "percent"),
        ],
        height=160,
    )
    labour_break = spans_a_break(
        LABOUR_DATASET, labour_years[0], labour_years[-1]
    ) if labour_years else None

    latest_real = deflatable[-1] if deflatable else None
    findings = _overview_findings(
        wage, median, cpi, base_year, latest, latest_median_year, deflatable
    )
    return render("index.html", shell(
        request, "/",
        findings=findings,
        labour_panels=labour_panels, labour_years=labour_years,
        labour_break=labour_break,
        unemployment=unemployment, employment_rate=employment_rate,
        labour_adapter=ADAPTERS[LABOUR_DATASET],
        labour_vintage=db.latest_vintage_id(conn, LABOUR_DATASET),
        latest_year=latest,
        latest_wage=wage.get(latest),
        latest_is_preliminary=latest in prelim if latest else False,
        latest_median_year=latest_median_year,
        latest_median=median.get(latest_median_year),
        gap=gap,
        base_year=base_year,
        latest_real=latest_real,
        naive_chart=naive, honest_chart=honest, real_chart=real_chart,
        era_rows=era_rows,
        currency_name=currency_name,
        summary=db.summary(conn),
        totals=contract_totals(),
        cpi_first=min(cpi) if cpi else None,
        cpi_last=max(cpi) if cpi else None,
        wage_first=min(wage) if wage else None,
        source_url=ADAPTERS[WAGE_DATASET].url,
        source_page=ADAPTERS[WAGE_DATASET].source_page,
        vintage_id=db.latest_vintage_id(conn, WAGE_DATASET),
    ))


# --------------------------------------------------------------------------
# /explorer
# --------------------------------------------------------------------------

def _overview_findings(
    wage, median, cpi, base_year, latest, latest_median_year, deflatable,
) -> list[dict]:
    """The five findings the overview leads on, each computed here.

    Every one carries its own period, unit, vintage and a link into the
    explorer, so a reader who doubts a number can be looking at the rows behind
    it in one click rather than taking the headline on trust.
    """
    out: list[dict] = []

    if latest_median_year and latest_median_year in wage:
        mean = wage[latest_median_year]
        mid = median[latest_median_year]
        out.append({
            "title": "The average sits well above the middle earner",
            "value": f"{metrics.mean_median_gap(mean, mid).gap_pct:.1f}%",
            "period": latest_median_year,
            "unit": "gap between mean and median",
            "text": (
                f"In {latest_median_year} the mean was {mean:,.0f} GEL a month "
                f"and the median {mid:,.0f}. The mean is pulled up by high "
                f"earners, so it answers a different question from 'what does "
                f"a typical person earn'. They also come from different "
                f"sources: the mean from the enterprise survey, the median "
                f"from Revenue Service records."
            ),
            "href": "/explorer?dataset=median_earnings",
            "datasets": "earnings_annual, median_earnings",
        })

    if deflatable:
        first, last = deflatable[0], deflatable[-1]
        out.append({
            "title": "Nominal and real earnings tell different stories",
            "value": f"{last['real_index']:,.0f}",
            "period": f"{first['period']}–{last['period']}",
            "unit": f"real index, {base_year} = 100",
            "text": (
                f"Nominal earnings reached an index of "
                f"{last['nominal_index']:,.0f} by {last['period']} against "
                f"{last['real_index']:,.0f} once deflated by the CPI. The "
                f"difference between those two numbers is inflation, and it is "
                f"the single most common way a wage rise is overstated."
            ),
            "href": f"/explorer?base={base_year}",
            "datasets": "earnings_annual, cpi_2010_base",
        })

    unemployment = labour_map("unemployment_rate_percentage")
    employed = labour_map("employed")
    if unemployment:
        year = max(unemployment)
        broken = spans_a_break(LABOUR_DATASET, min(unemployment), year)
        out.append({
            "title": "Employment and unemployment",
            "value": f"{unemployment[year]:.1f}%",
            "period": year,
            "unit": "unemployment rate",
            "text": (
                f"{employed.get(year, 0):,.0f} thousand people were in work in "
                f"{year} and the unemployment rate was "
                f"{unemployment[year]:.1f}%. These come from the household "
                f"survey, not the payroll file, so they count people where "
                f"they live."
                + (
                    f" The series breaks between {broken['before']} and "
                    f"{broken['after']} on the {broken['what']}, so it is not "
                    f"one continuous line."
                    if broken else ""
                )
            ),
            "href": "/work",
            "datasets": "labour_force",
        })

    income = db.value_map(conn, INCOME_DATASET, "income_total", "country.georgia")
    spend = db.value_map(
        conn, EXPENDITURE_DATASET, "expenditure_total", "country.georgia")
    shared = sorted(set(income) & set(spend))
    if shared:
        year = shared[-1]
        gap = income[year] - spend[year]
        out.append({
            "title": "Households report more coming in than going out",
            "value": f"{gap:+,.0f}",
            "period": year,
            "unit": "GEL per household per month",
            "text": (
                f"Reported income was {income[year]:,.0f} GEL a month and "
                f"reported expenditure {spend[year]:,.0f}. Both are "
                f"self-reported in the same survey and the difference between "
                f"them is a reporting artefact, not a savings rate."
            ),
            "href": "/households",
            "datasets": "household_income, household_expenditure",
        })

    earnings_metric = REGION_METRICS_BY_KEY["earnings"]
    region_periods = regional_periods(earnings_metric)
    if region_periods:
        year = region_periods[-1]
        values = regional_values(earnings_metric, year)
        national = values.get("country.georgia")
        regional = {
            c: v for c, v in values.items()
            if c.startswith("region.")
            and c.split(".", 1)[1] in geography.RANKABLE_REGIONS
        }
        if regional and national:
            top = max(regional, key=regional.get)
            bottom = min(regional, key=regional.get)
            out.append({
                "title": "The capital is a category of its own",
                "value": f"{regional[top] / national * 100:.0f}",
                "period": year,
                "unit": "index of the national figure, Georgia = 100",
                "text": (
                    f"{geography.display_name(top)} pays "
                    f"{regional[top]:,.0f} GEL a month against "
                    f"{regional[bottom]:,.0f} in "
                    f"{geography.display_name(bottom)}. Enterprises are counted "
                    f"at their head office, so this measures where employers "
                    f"are registered as much as where the work happens."
                ),
                "href": f"/atlas?metric=earnings&year={year}",
                "datasets": "earnings_by_region",
            })

    return out


def _explorer_selection(
    dataset: str, indicator: str, breakdown: str, grain: str,
    period_from: str, period_to: str, vintage: str, include_pre_gel: int,
) -> dict:
    """Resolve the query parameters against what is actually published.

    Every parameter degrades to a valid choice rather than erroring, because a
    shared URL outlives the vintage it was copied from: a link to a breakdown
    Geostat has since stopped publishing should still open the explorer on
    something sensible, and say what it did.
    """
    dataset = dataset if dataset in ADAPTERS else WAGE_DATASET
    vintages = ingest.list_vintages(dataset)
    vintage = vintage if vintage in vintages else (vintages[-1] if vintages else "")

    indicator_rows = db.indicators(conn, dataset, vintage_id=vintage)
    indicator_codes = [r["indicator_code"] for r in indicator_rows]
    if indicator not in indicator_codes:
        indicator = indicator_codes[0] if indicator_codes else ""

    breakdown_rows = db.breakdowns(conn, dataset, indicator, vintage_id=vintage)
    breakdown_codes = [r["breakdown_code"] for r in breakdown_rows]
    if breakdown not in breakdown_codes:
        # The total or the country row where one exists. `nace2.total` before
        # `nace1.total` because rev.2 is the current classification, and any
        # `.total` before the first code alphabetically - otherwise the
        # quarterly earnings explorer opens on Agriculture, which is a
        # breakdown of the thing the reader asked for rather than the thing.
        preferred = ("total", "country.georgia", "georgia",
                     "nace2.total", "nace1.total")
        breakdown = next(
            (c for c in preferred if c in breakdown_codes),
            next(
                (c for c in breakdown_codes if c.endswith(".total")),
                breakdown_codes[0] if breakdown_codes else "",
            ),
        )

    rows = db.series(conn, dataset, indicator, breakdown, vintage_id=vintage)
    periods = [r["period"] for r in rows if r["value"] is not None]
    annual = [p for p in periods if len(p) == 4]
    quarterly = [p for p in periods if "-Q" in p]
    monthly = [p for p in periods if len(p) == 7 and "-Q" not in p]
    available_grains = [
        name for name, values in
        (("annual", annual), ("quarterly", quarterly), ("monthly", monthly))
        if values
    ]
    if grain not in available_grains:
        grain = available_grains[0] if available_grains else "annual"
    universe = {"annual": annual, "quarterly": quarterly,
                "monthly": monthly}.get(grain, annual)

    # The Lari-era default, preserved: the wage sheets put four currencies in
    # adjacent columns and the explorer must not open on the mixture.
    is_currency_era = ADAPTERS[dataset].unit_family == "currency_era"
    if is_currency_era and grain == "annual" and not include_pre_gel:
        gel_only = [p for p in universe if int(p[:4]) >= GEL_ERA_START]
        universe = gel_only or universe

    universe = sorted(universe)
    lo = period_from if period_from in universe else (universe[0] if universe else "")
    hi = period_to if period_to in universe else (universe[-1] if universe else "")
    if lo and hi and lo > hi:
        lo, hi = hi, lo
    picked = [p for p in universe if lo <= p <= hi]

    return {
        "dataset": dataset, "indicator": indicator, "breakdown": breakdown,
        "grain": grain, "vintage": vintage, "vintages": vintages,
        "period_from": lo, "period_to": hi, "universe": universe,
        "picked": picked, "rows": rows,
        "indicator_rows": indicator_rows, "breakdown_rows": breakdown_rows,
        "available_grains": available_grains,
        "is_currency_era": is_currency_era,
    }


@app.get("/explorer", response_class=HTMLResponse)
def explorer(
    request: Request,
    dataset: str = Query(WAGE_DATASET),
    indicator: str = Query(WAGE_INDICATOR),
    breakdown: str = Query("total"),
    grain: str = Query("annual"),
    year_from: str = Query(""),
    year_to: str = Query(""),
    vintage: str = Query(""),
    include_pre_gel: int = Query(0),
    base: str = Query("2010"),
    format: str = Query(""),
):
    sel = _explorer_selection(
        dataset, indicator, breakdown, grain, year_from, year_to, vintage,
        include_pre_gel,
    )
    if format == "csv":
        return _explorer_csv(sel)

    cpi = cpi_map()
    by_period = {
        r["period"]: r for r in sel["rows"] if r["period"] in set(sel["picked"])
    }
    values = {p: by_period[p]["value"] for p in sel["picked"]
              if by_period[p]["value"] is not None}
    unit_of = {p: by_period[p]["unit"] for p in sel["picked"]}
    units = sorted(set(unit_of.values()))
    mixed_era = len(units) > 1
    unit = units[0] if len(units) == 1 else ""

    # Deflation is only meaningful for a monetary series on annual periods.
    deflatable = (
        unit == "GEL" and sel["grain"] == "annual"
        and any(p in cpi for p in sel["picked"])
    )
    if base not in cpi:
        candidates = [p for p in sel["picked"] if p in cpi]
        base = candidates[0] if candidates else "2010"

    prelim = db.preliminary_periods(conn, sel["dataset"], vintage_id=sel["vintage"])
    series = []
    for period in sel["picked"]:
        row = by_period[period]
        real = None
        if deflatable and period in cpi and row["value"] is not None and cpi.get(base):
            real = metrics.deflate(row["value"], cpi[period], cpi[base])
        series.append({
            "period": period, "value": row["value"], "unit": row["unit"],
            "raw": row["raw"], "status": row["status"], "real": real,
            "preliminary": period in prelim,
        })

    plotted = {"Published": [r["value"] for r in series]}
    if deflatable:
        plotted[f"Real, {base} prices"] = [r["real"] for r in series]
    # The median only belongs on the chart when the selection is the headline
    # wage total it is comparable with.
    if (sel["dataset"] == WAGE_DATASET and sel["breakdown"] == "total"
            and sel["grain"] == "annual"):
        median = median_map()
        if any(p in median for p in sel["picked"]):
            plotted["Median GEL"] = [median.get(p) for p in sel["picked"]]

    chart = charts.line_chart(
        sel["picked"], plotted, height=290,
        value_fmt="{:,.1f}" if unit in {"percent", "share_of_1"} else "{:,.0f}",
    )
    bands = charts.era_bands(chart, sel["picked"], unit_of) if mixed_era or unit in {
        "GEL", "RUB", "KUP", "TKUP"} else []

    query = _explorer_query(sel, base=base, include_pre_gel=include_pre_gel)
    return render("explorer.html", shell(
        request, "/explorer",
        sel=sel, series=series, chart=chart, units=units, unit=unit,
        mixed_era=mixed_era, era_bands=bands, deflatable=deflatable,
        base=base, base_choices=sorted(cpi), include_pre_gel=include_pre_gel,
        datasets=[(d, ADAPTERS[d].title) for d in ADAPTERS],
        gel_era_start=GEL_ERA_START, currency_name=currency_name,
        adapter=ADAPTERS[sel["dataset"]],
        source_url=ADAPTERS[sel["dataset"]].url,
        vintage_id=sel["vintage"], cpi_years=sorted(cpi),
        csv_query=query + "&format=csv",
        share_query=query,
        breaks=series_breaks(sel["dataset"]),
    ))


def _explorer_query(sel: dict, *, base: str, include_pre_gel: int) -> str:
    parts = [
        f"dataset={sel['dataset']}", f"indicator={sel['indicator']}",
        f"breakdown={sel['breakdown']}", f"grain={sel['grain']}",
        f"year_from={sel['period_from']}", f"year_to={sel['period_to']}",
        f"vintage={sel['vintage']}", f"base={base}",
        f"include_pre_gel={int(include_pre_gel)}",
    ]
    return "?" + "&".join(parts)


def _explorer_csv(sel: dict):
    """The active selection as CSV.

    Built from the same `db.observations` call the table renders from, so the
    download cannot drift from what is on screen. Every row carries its dataset,
    vintage, unit and preliminary flag, because a CSV that loses its provenance
    is how a caveated figure becomes an uncaveated one in somebody's
    spreadsheet.
    """
    import csv
    import io

    rows = db.observations(
        conn, sel["dataset"], indicator_code=sel["indicator"],
        breakdown_code=sel["breakdown"], period_from=sel["period_from"],
        period_to=sel["period_to"], vintage_id=sel["vintage"],
    )
    picked = set(sel["picked"])
    adapter = ADAPTERS[sel["dataset"]]

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([
        "dataset_id", "indicator_code", "indicator_label", "breakdown_code",
        "breakdown_label", "period", "unit", "value", "raw", "status",
        "is_preliminary", "vintage_id", "source_url",
    ])
    for row in rows:
        if row["period"] not in picked:
            continue
        writer.writerow([
            row["dataset_id"], row["indicator_code"], row["indicator_label"],
            row["breakdown_code"], row["breakdown_label"], row["period"],
            row["unit"], "" if row["value"] is None else row["value"],
            row["raw"], row["status"], int(bool(row["is_preliminary"])),
            row["vintage_id"], adapter.url,
        ])
    filename = (
        f"geostats-{sel['dataset']}-{sel['indicator']}-{sel['breakdown']}"
        f"-{sel['vintage']}.csv"
    )
    from fastapi.responses import Response
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------
# /regions
# --------------------------------------------------------------------------

@app.get("/work", response_class=HTMLResponse)
def work(request: Request, activity: str = Query(""), base: str = Query("2010")):
    """Employment, unemployment and pay, each on its own scale."""
    unemployment = labour_map("unemployment_rate_percentage")
    employment_rate = labour_map("employment_rate_percentage")
    participation = labour_map("labour_force_participation_rate_percentage")
    employed = labour_map("employed")
    cpi = cpi_map()
    wage = wage_map("total")

    lf_years = sorted(unemployment)
    real_wage = deflate_series(wage, cpi, base if base in cpi else "2010")
    # The panels share an x axis, so they share a period universe: the years
    # where the labour force survey and the deflatable wage series overlap.
    shared = [y for y in lf_years if y in real_wage]

    panels = charts.aligned_panels(
        shared,
        [
            (f"Real earnings, {base} prices (GEL/month)",
             [real_wage.get(y) for y in shared], "GEL"),
            ("Unemployment rate (%)",
             [unemployment.get(y) for y in shared], "percent"),
            ("Employment rate (%)",
             [employment_rate.get(y) for y in shared], "percent"),
        ],
    )

    force_chart = charts.line_chart(
        lf_years,
        {
            "Unemployment rate": [unemployment.get(y) for y in lf_years],
            "Employment rate": [employment_rate.get(y) for y in lf_years],
            "Participation rate": [participation.get(y) for y in lf_years],
        },
        height=300, value_fmt="{:,.1f}", y_zero=True,
    )

    # -- quarterly small multiples ----------------------------------------
    quarterly_vintage = db.latest_vintage_id(conn, QUARTERLY_DATASET)
    activity_rows = [
        r for r in db.breakdowns(conn, QUARTERLY_DATASET, WAGE_INDICATOR)
        if r["breakdown_code"].startswith("nace2.")
    ]
    activity_choices = [
        (r["breakdown_code"], r["breakdown_label"]) for r in activity_rows
    ]
    chosen = [code for code, _ in activity_choices[:9]]
    if activity and activity in {c for c, _ in activity_choices}:
        chosen = [activity]
    multiples = []
    for code in chosen:
        values = db.value_map(conn, QUARTERLY_DATASET, WAGE_INDICATOR, code)
        quarters = sorted(values)
        if len(quarters) > 1:
            label = next(l for c, l in activity_choices if c == code)
            multiples.append((label, quarters, [values[q] for q in quarters]))
    small = charts.small_multiples(multiples)

    quarters_all = sorted(
        db.value_map(conn, QUARTERLY_DATASET, WAGE_INDICATOR, "nace2.total")
    )
    seasonality = _quarter_seasonality(
        db.value_map(conn, QUARTERLY_DATASET, WAGE_INDICATOR, "nace2.total")
    )

    # -- gender pay gap ----------------------------------------------------
    gpg_years = db.periods_for(conn, GPG_DATASET, "adjusted_gpg_hourly")
    gpg_year = gpg_years[-1] if gpg_years else ""
    hourly = db.cross_section(conn, GPG_DATASET, "adjusted_gpg_hourly", gpg_year)
    monthly = db.cross_section(conn, GPG_DATASET, "adjusted_gpg_monthly", gpg_year)
    gpg_labels = {
        r["breakdown_code"]: r["breakdown_label"]
        for r in db.breakdowns(conn, GPG_DATASET, "adjusted_gpg_hourly")
    }
    gpg = charts.dumbbell_rows(
        [
            (gpg_labels.get(code, code), hourly.get(code), monthly.get(code))
            for code in sorted(hourly, key=lambda c: -(monthly.get(c) or 0))
        ],
        left_label="Hourly", right_label="Monthly",
    )
    gpg_total_hourly = hourly.get("total")
    gpg_total_monthly = monthly.get("total")

    # -- sector ranking, both classifications kept apart --------------------
    sector_year = sorted(
        db.periods_for(conn, "earnings_by_activity", WAGE_INDICATOR)
    )
    latest_sector = sector_year[-1] if sector_year else ""
    sectors = db.cross_section(
        conn, "earnings_by_activity", WAGE_INDICATOR, latest_sector
    )
    sector_labels = {
        r["breakdown_code"]: r["breakdown_label"]
        for r in db.breakdowns(conn, "earnings_by_activity", WAGE_INDICATOR)
    }
    nace2 = sorted(
        ((sector_labels.get(c, c), v) for c, v in sectors.items()
         if c.startswith("nace2.") and not c.endswith(".total")),
        key=lambda pair: -pair[1],
    )
    sector_bars = charts.bar_rows(nace2, fmt="{:,.0f}")

    summary = _work_summary(
        shared, real_wage, unemployment, employed, base,
        gpg_total_hourly, gpg_total_monthly, gpg_year,
    )
    breaks = series_breaks(LABOUR_DATASET)

    return render("work.html", shell(
        request, "/work",
        panels=panels, force_chart=force_chart, lf_years=lf_years,
        shared=shared, base=base, base_choices=sorted(cpi),
        unemployment=unemployment, employment_rate=employment_rate,
        participation=participation, real_wage=real_wage,
        small=small, activity=activity, activity_choices=activity_choices,
        quarters=quarters_all, seasonality=seasonality,
        quarterly_vintage=quarterly_vintage,
        gpg=gpg, gpg_year=gpg_year,
        gpg_total_hourly=gpg_total_hourly, gpg_total_monthly=gpg_total_monthly,
        sectors=nace2, sector_bars=sector_bars, sector_year=latest_sector,
        summary=summary, breaks=breaks,
        labour_adapter=ADAPTERS[LABOUR_DATASET],
        quarterly_adapter=ADAPTERS[QUARTERLY_DATASET],
        gpg_adapter=ADAPTERS[GPG_DATASET],
        activity_adapter=ADAPTERS["earnings_by_activity"],
        labour_vintage=db.latest_vintage_id(conn, LABOUR_DATASET),
        qs=_lang_qs(request),
    ))


def _quarter_seasonality(values: dict[str, float]) -> list[dict]:
    """Average position of each quarter within its own year.

    Georgian pay is strongly fourth-quarter weighted. Reporting Q4 growth
    against Q3 as if it were a trend is the mistake this exists to name, so the
    figure shown is each quarter as a percentage of its own year's mean - a
    within-year comparison that cannot be mistaken for one across years.
    """
    by_year: dict[str, dict[int, float]] = {}
    for period, value in values.items():
        if "-Q" not in period:
            continue
        by_year.setdefault(period[:4], {})[int(period[-1])] = value

    totals: dict[int, list[float]] = {}
    for quarters in by_year.values():
        if len(quarters) != 4:
            continue                       # a partial year would skew its mean
        mean = sum(quarters.values()) / 4
        for q, value in quarters.items():
            totals.setdefault(q, []).append(value / mean * 100)
    return [
        {"quarter": f"Q{q}", "index": round(sum(v) / len(v), 1), "years": len(v)}
        for q, v in sorted(totals.items())
    ]


def _work_summary(
    years, real_wage, unemployment, employed, base,
    gpg_hourly, gpg_monthly, gpg_year,
) -> list[str]:
    """Plain-language findings, generated from the same numbers the charts use.

    Every sentence is a template filled from an approved metric. Nothing here
    is written by hand about a specific year, so a refreshed vintage updates
    the prose along with the charts rather than leaving stale claims behind.
    """
    out = []
    if len(years) >= 2:
        first, last = years[0], years[-1]
        wage_change = _pct_change(real_wage, first, last)
        if wage_change is not None:
            out.append(
                f"Real earnings rose {wage_change:.0f}% between {first} and "
                f"{last}, measured in {base} prices. That is the published "
                f"nominal series deflated by the CPI, not a separate estimate."
            )
        broken = spans_a_break(LABOUR_DATASET, first, last)
        caveat = (
            ""
            if not broken else
            f" This comparison crosses the {broken['before']}/{broken['after']} "
            f"{broken['what']} break, so part of the movement is a change in "
            f"who is counted rather than in the labour market."
        )
        if first in unemployment and last in unemployment:
            move = unemployment[last] - unemployment[first]
            out.append(
                f"Unemployment moved from {unemployment[first]:.1f}% to "
                f"{unemployment[last]:.1f}% over the same span, a change of "
                f"{move:+.1f} percentage points.{caveat}"
            )
        if first in employed and last in employed:
            out.append(
                f"Employment stood at {employed[last]:,.0f} thousand people in "
                f"{last} against {employed[first]:,.0f} thousand in {first}."
                f"{caveat}"
            )
        # The same comparison confined to one side of the break, which is the
        # only version of it that means what it appears to mean.
        if broken:
            after = [y for y in years if y >= broken["after"]]
            if len(after) >= 2 and after[0] in unemployment and after[-1] in unemployment:
                out.append(
                    f"On one consistent definition, {after[0]} to {after[-1]}, "
                    f"unemployment went from {unemployment[after[0]]:.1f}% to "
                    f"{unemployment[after[-1]]:.1f}% and employment from "
                    f"{employed.get(after[0], 0):,.0f} to "
                    f"{employed.get(after[-1], 0):,.0f} thousand. That is the "
                    f"comparison worth quoting."
                )
    if gpg_hourly is not None and gpg_monthly is not None:
        out.append(
            f"The adjusted gender pay gap in {gpg_year} was "
            f"{gpg_hourly:.1f}% hourly and {gpg_monthly:.1f}% monthly. The "
            f"monthly gap is the larger because women work fewer paid hours, "
            f"so the hourly figure is the one that isolates the rate of pay."
        )
    return out


SPEND_COMPONENTS = [
    ("on_food_beverages_tobacco", "Food, drink, tobacco"),
    ("housing_water_electricity_gas_and_other_fuels", "Housing and utilities"),
    ("on_healthcare", "Healthcare"),
    ("on_transport", "Transport"),
    ("on_clothes_and_footwear", "Clothes and footwear"),
    ("on_education", "Education"),
    ("on_household_goods", "Household goods"),
    ("other_consumption_expenditure", "Other consumption"),
]


@app.get("/households", response_class=HTMLResponse)
def households(request: Request, year: str = Query(""), base: str = Query("2010")):
    """What households report taking in and what they report spending."""
    income_years = db.periods_for(conn, INCOME_DATASET, "income_total")
    if year not in income_years:
        year = income_years[-1] if income_years else ""

    national_income = db.value_map(
        conn, INCOME_DATASET, "income_total", "country.georgia")
    national_spend = db.value_map(
        conn, EXPENDITURE_DATASET, "expenditure_total", "country.georgia")
    cpi = cpi_map()
    base = base if base in cpi else "2010"
    real_income = deflate_series(national_income, cpi, base)
    real_spend = deflate_series(national_spend, cpi, base)

    years = sorted(set(national_income) & set(national_spend))
    trend = charts.line_chart(
        years,
        {
            "Income, nominal": [national_income.get(y) for y in years],
            "Expenditure, nominal": [national_spend.get(y) for y in years],
            f"Income, {base} prices": [real_income.get(y) for y in years],
            f"Expenditure, {base} prices": [real_spend.get(y) for y in years],
        },
        height=300, y_zero=True,
    )

    # -- by region --------------------------------------------------------
    income_by_region = db.cross_section(
        conn, INCOME_DATASET, "income_total", year)
    spend_by_region = db.cross_section(
        conn, EXPENDITURE_DATASET, "expenditure_total", year)
    # Every rankable region, including the ones this year does not publish. A
    # region that simply vanishes from the list reads as "not a region"; a
    # region drawn as a gap reads as "not published", which is what it is.
    region_codes = [f"region.{code}" for code in geography.RANKABLE_REGIONS]
    paired = [
        {
            "code": code,
            "label": geography.display_name(code),
            "income": income_by_region.get(code),
            "expenditure": spend_by_region.get(code),
            "balance": (
                None
                if code not in income_by_region or code not in spend_by_region
                else income_by_region[code] - spend_by_region[code]
            ),
        }
        for code in region_codes
    ]
    paired.sort(key=lambda r: -(r["income"] or 0))
    missing = [r["label"] for r in paired
               if r["income"] is None or r["expenditure"] is None]

    dumbbell = charts.dumbbell_rows(
        [(r["label"], r["expenditure"], r["income"]) for r in paired],
        left_label="Reported expenditure", right_label="Reported income",
    )
    balance = charts.diverging_rows(
        [(r["label"], r["balance"]) for r in paired], fmt="{:+,.0f}"
    )

    # -- composition -------------------------------------------------------
    composition_items = []
    for row in paired:
        parts = []
        for code, label in SPEND_COMPONENTS:
            values = db.cross_section(conn, EXPENDITURE_DATASET, code, year)
            parts.append((label, values.get(row["code"])))
        if any(v is not None for _n, v in parts):
            composition_items.append((row["label"], parts))
    composition = charts.stacked_rows(composition_items)

    national_parts = []
    for code, label in SPEND_COMPONENTS:
        values = db.cross_section(conn, EXPENDITURE_DATASET, code, year)
        national_parts.append((label, values.get("country.georgia")))
    national_composition = charts.stacked_rows([("Georgia", national_parts)])

    summary = _household_summary(
        year, national_income, national_spend, real_income, real_spend,
        base, years, paired,
    )

    return render("households.html", shell(
        request, "/households",
        year=year, years=income_years, base=base, base_choices=sorted(cpi),
        trend=trend, trend_years=years,
        national_income=national_income, national_spend=national_spend,
        real_income=real_income, real_spend=real_spend,
        paired=paired, dumbbell=dumbbell, balance=balance, missing=missing,
        composition=composition, national_composition=national_composition,
        components=SPEND_COMPONENTS,
        summary=summary,
        income_adapter=ADAPTERS[INCOME_DATASET],
        expenditure_adapter=ADAPTERS[EXPENDITURE_DATASET],
        income_vintage=db.latest_vintage_id(conn, INCOME_DATASET),
        expenditure_vintage=db.latest_vintage_id(conn, EXPENDITURE_DATASET),
        qs=_lang_qs(request),
    ))


def _household_summary(
    year, income, spend, real_income, real_spend, base, years, paired,
) -> list[str]:
    out = []
    if year in income and year in spend:
        gap = spend[year] - income[year]
        overspending = [y for y in years if spend[y] > income[y]]
        direction = (
            "more than they reported receiving" if gap > 0
            else "less than they reported receiving"
        )
        out.append(
            f"In {year} the average household reported {income[year]:,.0f} GEL "
            f"a month coming in and {spend[year]:,.0f} GEL going out: they "
            f"reported spending {direction}, by {abs(gap):,.0f} GEL. Across the "
            f"{len(years)} published years, expenditure exceeds income in "
            f"{len(overspending)} of them. That gap is a known reporting "
            f"artefact of household surveys - income is under-reported more "
            f"than spending is - and it is not a savings rate, a deficit, or "
            f"evidence about anybody's finances."
        )
        flipped = [
            y for y in years
            if spend[y] <= income[y] and y > (overspending[-1] if overspending else "")
        ]
        if flipped and len(overspending) < len(years):
            out.append(
                f"The sign reverses in {flipped[0]}: from that year on, "
                f"reported income exceeds reported expenditure, having been the "
                f"other way round since {years[0]}. Geostat increased the "
                f"survey sample from 2019 and this page does not know whether "
                f"the reversal is a change in reporting behaviour, in the "
                f"sample, or in households. It is stated rather than explained."
            )
    if len(years) >= 2:
        first, last = years[0], years[-1]
        real_move = _pct_change(real_income, first, last)
        nominal_move = _pct_change(income, first, last)
        if real_move is not None and nominal_move is not None:
            out.append(
                f"Between {first} and {last} reported household income rose "
                f"{nominal_move:.0f}% in cash terms but {real_move:.0f}% once "
                f"deflated to {base} prices. The difference between those two "
                f"numbers is inflation, and quoting the first without the "
                f"second is the most common way to overstate a rise in living "
                f"standards."
            )
    ranked = [r for r in paired if r["income"] is not None]
    if len(ranked) >= 2:
        top, bottom = ranked[0], ranked[-1]
        out.append(
            f"The highest-reporting region in {year} is {top['label']} at "
            f"{top['income']:,.0f} GEL a month and the lowest is "
            f"{bottom['label']} at {bottom['income']:,.0f}, a ratio of "
            f"{top['income'] / bottom['income']:.2f} to 1. This survey places "
            f"a household where it lives, so unlike the earnings series it "
            f"carries no head-office effect."
        )
    return out


# One entry per comparable regional measure. `legacy_codes` marks the datasets
# whose breakdown codes predate the geography registry: `earnings_by_region`
# carries three genuine vintages, two of them recovered from the Internet
# Archive, so its codes are mapped at read time rather than re-ingested. A
# re-ingest would mint new timestamps and throw away the provenance that makes
# those two releases worth having.
REGION_METRICS: list[dict] = [
    {"key": "earnings", "label": "Average monthly earnings",
     "dataset": REGION_DATASET, "indicator": WAGE_INDICATOR,
     "unit": "GEL / month", "fmt": "{:,.0f}", "legacy_codes": True,
     "note": "Enterprises are counted at their head office, which inflates "
             "Tbilisi relative to where the work is done."},
    {"key": "unemployment", "label": "Unemployment rate",
     "dataset": LABOUR_REGION_DATASET, "indicator": "unemployment_rate_percentage",
     "unit": "%", "fmt": "{:,.1f}", "lower_is_better": True,
     "note": "Household survey: a person is counted where they live."},
    {"key": "employment", "label": "Employed people",
     "dataset": LABOUR_REGION_DATASET, "indicator": "employed",
     "unit": "thousand", "fmt": "{:,.0f}",
     "note": "Household survey. Breaks between 2009 and 2010 on the ICLS-19 "
             "definition change."},
    {"key": "household_income", "label": "Household income",
     "dataset": INCOME_DATASET, "indicator": "income_total",
     "unit": "GEL / household / month", "fmt": "{:,.0f}",
     "note": "Self-reported, and placed where the household lives."},
    {"key": "household_expenditure", "label": "Household expenditure",
     "dataset": EXPENDITURE_DATASET, "indicator": "expenditure_total",
     "unit": "GEL / household / month", "fmt": "{:,.0f}",
     "note": "Self-reported in the same survey as income."},
    {"key": "population", "label": "Population",
     "dataset": POPULATION_DATASET, "indicator": "population_1_january",
     "unit": "thousand", "fmt": "{:,.1f}",
     "note": "Rebased on the 2024 census, so the whole series was revised."},
    {"key": "enterprise_births", "label": "Enterprise births",
     "dataset": BUSINESS_DATASET, "indicator": "enterprise_births",
     "unit": "enterprises", "fmt": "{:,.0f}",
     "note": "Registrations, not activity: an individual entrepreneur "
             "registering counts the same as a factory opening."},
    {"key": "domestic_visits", "label": "Domestic tourism visits",
     "dataset": TOURISM_DATASET, "indicator": "domestic_visits",
     "unit": "thousand visits / month", "fmt": "{:,.0f}", "quarterly": True,
     "note": "Quarterly survey estimate of monthly average visits."},
]
REGION_METRICS_BY_KEY = {m["key"]: m for m in REGION_METRICS}


def regional_values(metric: dict, period: str) -> dict[str, float]:
    """`{region code: value}` for one measure in one period, registry-coded."""
    values = db.cross_section(
        conn, metric["dataset"], metric["indicator"], period)
    if not metric.get("legacy_codes"):
        return values
    labels = {
        r["breakdown_code"]: r["breakdown_label"]
        for r in db.breakdowns(conn, metric["dataset"], metric["indicator"])
    }
    out = {}
    for code, value in values.items():
        try:
            resolved, _name = geography.resolve(labels.get(code, code))
        except geography.UnknownPlace:
            continue
        out[resolved] = value
    return out


def regional_periods(metric: dict) -> list[str]:
    return db.periods_for(conn, metric["dataset"], metric["indicator"])


def _rows_to_csv(rows: list[dict], columns: list[str], filename: str):
    """A CSV response built from already-assembled rows.

    Shared by the explorer and the atlas so both downloads carry the same
    columns in the same order. A platform that cannot export is a screenshot,
    and an export that disagrees with the page it came from is worse than one.
    """
    import csv
    import io

    from fastapi.responses import Response

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if row.get(c) is None else row.get(c) for c in columns])
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/atlas", response_class=HTMLResponse)
def atlas_alias(request: Request):
    """The atlas used to live here. Kept so shared links do not rot."""
    query = request.url.query
    return RedirectResponse(
        "/regions" + (f"?{query}" if query else ""), status_code=308
    )


@app.get("/regions", response_class=HTMLResponse)
def regions(
    request: Request,
    metric: str = Query("earnings"),
    year: str = Query(""),
    region: str = Query(""),
    format: str = Query(""),
):
    """The regional atlas: one measure across the country, or one region across
    every measure."""
    chosen = REGION_METRICS_BY_KEY.get(metric) or REGION_METRICS[0]
    periods = regional_periods(chosen)
    if year not in periods:
        year = periods[-1] if periods else ""

    values = regional_values(chosen, year)
    national = values.get("country.georgia")
    regional = {
        code.split(".", 1)[1]: value
        for code, value in values.items()
        if code.startswith("region.")
        and code.split(".", 1)[1] in geography.RANKABLE_REGIONS
    }
    labels = {c: geography.display_name(f"region.{c}") for c in regional}
    tiles = charts.tile_atlas(
        regional,
        labels={c: geography.short_name(c) for c in charts.REGION_TILES},
        fmt=chosen["fmt"],
    )
    for cell in tiles["cells"]:
        cell["selected"] = cell["code"] == region

    ranked = [
        {
            "code": code, "label": labels[code], "value": value,
            "rank": i + 1,
            "index": (None if not national else round(value / national * 100, 1)),
        }
        for i, (code, value) in enumerate(
            sorted(regional.items(), key=lambda kv: -kv[1])
        )
    ]

    if format == "csv":
        vintage_id = db.latest_vintage_id(conn, chosen["dataset"]) or ""
        return _rows_to_csv(
            [
                {
                    "rank": row["rank"],
                    "region_code": f"region.{row['code']}",
                    "region": row["label"],
                    "period": year,
                    "unit": chosen["unit"],
                    "value": row["value"],
                    "national": national,
                    "index_georgia_100": row["index"],
                    "dataset_id": chosen["dataset"],
                    "indicator_code": chosen["indicator"],
                    "vintage_id": vintage_id,
                    "source_url": ADAPTERS[chosen["dataset"]].url,
                }
                for row in ranked
            ],
            ["rank", "region_code", "region", "period", "unit", "value",
             "national", "index_georgia_100", "dataset_id", "indicator_code",
             "vintage_id", "source_url"],
            f"geostats-atlas-{chosen['key']}-{year}-{vintage_id}.csv",
        )

    # -- wage against unemployment, sized by population ---------------------
    wage_metric = REGION_METRICS_BY_KEY["earnings"]
    unemployment_metric = REGION_METRICS_BY_KEY["unemployment"]
    scatter_year = _shared_year(
        [wage_metric, unemployment_metric, REGION_METRICS_BY_KEY["population"]]
    )
    scatter = {"empty": True}
    if scatter_year:
        wages = regional_values(wage_metric, scatter_year)
        unemp = regional_values(unemployment_metric, scatter_year)
        pop = regional_values(REGION_METRICS_BY_KEY["population"], scatter_year)
        scatter = charts.scatter(
            [
                {
                    "label": geography.display_name(code),
                    "x": wages.get(code), "y": unemp.get(code),
                    "size": pop.get(code),
                    "highlight": code == f"region.{region}",
                }
                for code in wages
                if code.startswith("region.")
                and code.split(".", 1)[1] in geography.RANKABLE_REGIONS
            ],
            x_label=f"Average monthly earnings, GEL ({scatter_year})",
            y_label=f"Unemployment rate, % ({scatter_year})",
        )

    # -- one region against the country, every measure ----------------------
    fingerprint = []
    profile = None
    region_label = ""
    if region in geography.RANKABLE_REGIONS:
        code = f"region.{region}"
        region_label = geography.display_name(code)
        for m in REGION_METRICS:
            m_periods = regional_periods(m)
            if not m_periods:
                continue
            m_year = m_periods[-1]
            m_values = regional_values(m, m_year)
            value, country = m_values.get(code), m_values.get("country.georgia")
            if value is None or not country:
                continue
            fingerprint.append({
                "label": m["label"], "key": m["key"], "period": m_year,
                "value": value, "national": country,
                "index": round(value / country * 100, 1),
                "unit": m["unit"], "note": m.get("note", ""),
            })
        chosen_periods = [p for p in periods]
        series_region = {
            p: regional_values(chosen, p).get(code) for p in chosen_periods
        }
        series_country = {
            p: regional_values(chosen, p).get("country.georgia")
            for p in chosen_periods
        }
        plotted = [p for p in chosen_periods
                   if series_region.get(p) is not None]
        if len(plotted) > 1:
            profile = charts.line_chart(
                plotted,
                {
                    region_label: [series_region[p] for p in plotted],
                    "Georgia": [series_country.get(p) for p in plotted],
                },
                height=260, value_fmt=chosen["fmt"],
            )

    spread = _earnings_spread() if chosen["key"] == "earnings" else None

    return render("regions.html", shell(
        request, "/regions",
        spread=spread,
        metric=chosen, metrics=REGION_METRICS, year=year, periods=periods,
        tiles=tiles, ranked=ranked, national=national,
        scatter=scatter, scatter_year=scatter_year,
        region=region, region_label=region_label,
        fingerprint=fingerprint, profile=profile,
        regions=[(c, geography.display_name(f"region.{c}"))
                 for c in geography.RANKABLE_REGIONS],
        adapter=ADAPTERS[chosen["dataset"]],
        vintage_id=db.latest_vintage_id(conn, chosen["dataset"]),
        qs=_lang_qs(request),
    ))


def _shared_year(metrics_list: list[dict]) -> str:
    """The most recent period every one of these measures publishes.

    A scatter built from three datasets must use one year for all three, or the
    points silently mix a 2025 wage with a 2019 population.
    """
    common = None
    for m in metrics_list:
        annual = {p for p in regional_periods(m) if len(p) == 4}
        common = annual if common is None else (common & annual)
    return max(common) if common else ""


def _earnings_spread() -> dict:
    """The leading and trailing region in every published year, each indexed
    against that year's national figure.

    Both endpoints move — the highest region is not the same place every year —
    so this is the spread between the extremes, not one region's history. It
    stays specific to the earnings series because that is the only regional
    measure published far enough back for a spread to say anything.
    """
    by_region = {}
    for row in db.breakdowns(conn, REGION_DATASET, WAGE_INDICATOR):
        code = row["breakdown_code"]
        if code != "total":
            by_region[code] = {"label": row["breakdown_label"]}

    years = sorted(
        r["period"] for r in db.series(conn, REGION_DATASET, WAGE_INDICATOR, "total")
        if r["value"] is not None
    )

    # The spread over time: the leading and trailing region in every published
    # year, each as an index of that year's national figure. Both endpoints move,
    # so this is a spread, not one region's history.
    national_by_year = db.value_map(conn, REGION_DATASET, WAGE_INDICATOR, "total")
    codes = [
        r["breakdown_code"]
        for r in db.breakdowns(conn, REGION_DATASET, WAGE_INDICATOR)
        if r["breakdown_code"] != "total"
    ]
    maps = {c: db.value_map(conn, REGION_DATASET, WAGE_INDICATOR, c) for c in codes}
    spread = []
    for y in years:
        vals = {c: m[y] for c, m in maps.items() if m.get(y) is not None}
        if not vals or not national_by_year.get(y):
            continue
        top_code = max(vals, key=vals.get)
        low_code = min(vals, key=vals.get)
        spread.append({
            "period": y,
            "top": metrics.region_index(vals[top_code], national_by_year[y]),
            "low": metrics.region_index(vals[low_code], national_by_year[y]),
            "top_label": by_region.get(top_code, {}).get("label", top_code),
            "low_label": by_region.get(low_code, {}).get("label", low_code),
        })

    spread_chart = charts.line_chart(
        [r["period"] for r in spread],
        {
            "Highest region": [r["top"] for r in spread],
            "National": [100.0 for _ in spread],
            "Lowest region": [r["low"] for r in spread],
        },
        height=240, value_fmt="{:,.0f}",
    )
    for line in spread_chart.lines:
        if line.label == "National":
            line.dashed = True

    return {"spread": spread, "chart": spread_chart}


# --------------------------------------------------------------------------
# /salary
# --------------------------------------------------------------------------

@app.get("/salary", response_class=HTMLResponse)
def salary(
    request: Request,
    amount: float = Query(1500.0),
    year_from: str = Query(""),
    year_to: str = Query(""),
):
    wage, cpi, median = wage_map(), cpi_map(), median_map()
    prelim = db.preliminary_periods(conn, WAGE_DATASET)
    years = sorted(cpi)
    lo = year_from if year_from in cpi else (years[-11] if len(years) > 11 else years[0])
    hi = year_to if year_to in cpi else years[-1]
    if lo > hi:
        lo, hi = hi, lo

    amount = max(0.0, min(float(amount), 1_000_000.0))
    equivalent = metrics.preserve_purchasing_power(amount, cpi[lo], cpi[hi])
    inflation = metrics.cumulative_inflation(cpi[lo], cpi[hi])
    span = int(hi) - int(lo)
    annualised = metrics.annualised_inflation(cpi[lo], cpi[hi], span) if span else 0.0
    real_today = metrics.deflate(amount, cpi[hi], cpi[lo])

    compare_year = hi if hi in wage else (max(y for y in wage if y <= hi) if wage else None)
    vs_mean = (amount / wage[compare_year] * 100) if compare_year in wage else None
    median_year = max((y for y in median if y <= hi), default=None)
    vs_median = (amount / median[median_year] * 100) if median_year else None

    ladder = [
        {
            "period": y,
            "equivalent": metrics.preserve_purchasing_power(amount, cpi[lo], cpi[y]),
            "cpi": cpi[y],
        }
        for y in years if lo <= y <= hi
    ]
    chart = charts.line_chart(
        [r["period"] for r in ladder],
        {f"{amount:,.0f} GEL from {lo}, kept whole": [r["equivalent"] for r in ladder]},
        height=230, value_fmt="{:,.0f}",
    )
    # One axis carrying the two published points and the entered amount. The
    # amount is placed by value, not by rank: it can sit outside both.
    scale = charts.position_scale([
        ("Published median", median.get(median_year)),
        ("Published mean", wage.get(compare_year)),
        ("Your amount", amount),
    ])
    return render("salary.html", shell(
        request, "/salary", scale=scale,
        amount=amount, year_from=lo, year_to=hi, years=years,
        equivalent=equivalent, inflation=inflation, annualised=annualised,
        span=span, real_today=real_today, ladder=ladder, chart=chart,
        vs_mean=vs_mean, vs_median=vs_median,
        compare_year=compare_year, median_year=median_year,
        mean_value=wage.get(compare_year), median_value=median.get(median_year),
        is_preliminary=compare_year in prelim if compare_year else False,
        cpi_lo=cpi[lo], cpi_hi=cpi[hi],
        source_url=ADAPTERS[CPI_DATASET].url,
        vintage_id=db.latest_vintage_id(conn, CPI_DATASET),
    ))


# --------------------------------------------------------------------------
# /reliability
# --------------------------------------------------------------------------

@app.get("/reliability", response_class=HTMLResponse)
def reliability(request: Request, refreshed: str = Query("")):
    cards = []
    for dataset_id, adapter in ADAPTERS.items():
        vintages = db.vintage_rows(conn, dataset_id)
        if not vintages:
            cards.append({"dataset_id": dataset_id, "adapter": adapter,
                          "meta": None, "checks": [], "empty": True})
            continue
        latest = next((v for v in vintages if v["is_latest"]), vintages[0])
        checks = db.contract_results(conn, dataset_id, latest["vintage_id"])
        passed = sum(1 for c in checks if c["passed"])
        period = conn.execute(
            """SELECT MAX(period) AS p FROM observations
                WHERE dataset_id = ? AND vintage_id = ? AND value IS NOT NULL""",
            (dataset_id, latest["vintage_id"]),
        ).fetchone()["p"]
        prelim = sorted(db.preliminary_periods(conn, dataset_id,
                                               vintage_id=latest["vintage_id"]))
        cards.append({
            "dataset_id": dataset_id, "adapter": adapter, "empty": False,
            "meta": dict(latest), "checks": checks,
            "passed": passed, "total": len(checks),
            "rate": passed / len(checks) * 100 if checks else 0,
            "latest_period": period, "preliminary": prelim,
            "vintage_count": len(vintages),
            "expectation": release_calendar.next_release(
                dataset_id,
                db.periods_for(conn, dataset_id, vintage_id=latest["vintage_id"]),
            ),
        })
    overdue = [c for c in cards if c.get("expectation") and c["expectation"].overdue]
    return render("reliability.html", shell(
        request, "/reliability", cards=cards, totals=contract_totals(),
        summary=db.summary(conn), refreshed=refreshed,
        contracts=CONTRACTS, qs=_lang_qs(request),
        overdue=overdue, no_feed_reason=release_calendar.NO_FEED_REASON,
    ))


@app.get("/reliability/{dataset_id}", response_class=HTMLResponse)
def reliability_detail(request: Request, dataset_id: str):
    adapter = ADAPTERS.get(dataset_id)
    if adapter is None:
        return RedirectResponse("/reliability", status_code=303)
    history = ingest.vintage_history(dataset_id)
    latest = db.latest_vintage_id(conn, dataset_id)
    px_table = PX_TABLES.get(dataset_id)
    px_snapshot = read_snapshot(dataset_id)
    px_meta = px_snapshot[1] if px_snapshot else None
    checks = db.contract_results(conn, dataset_id, latest)
    for check in checks:
        pass
    parsed = [
        {**dict(c), "offender_rows": json.loads(c["offenders"])} for c in checks
    ]
    return render("reliability_detail.html", shell(
        request, "/reliability", adapter=adapter, dataset_id=dataset_id,
        history=history, checks=parsed, latest=latest,
        px_table=px_table, px_meta=px_meta,
        qs=_lang_qs(request),
    ))


@app.get("/healthz")
def healthz():
    """Liveness plus the two facts worth alerting on: that the read index has
    data in it, and whether any contract is failing that nobody has explained."""
    try:
        counts = db.summary(conn)
    except Exception as exc:                         # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)
    undocumented = [
        f"{row['dataset_id']}/{row['code']}"
        for row in db.failing_checks(conn)
        if not known_failure(row["dataset_id"], row["code"])
    ]
    healthy = counts["observations"] > 0 and not undocumented
    return JSONResponse(
        {
            "ok": healthy,
            "datasets": counts["datasets"],
            "vintages": counts["vintages"],
            "observations": counts["observations"],
            "undocumented_contract_failures": undocumented,
            "refresh_enabled": ALLOW_REFRESH,
        },
        status_code=200 if healthy else 503,
    )


@app.post("/refresh-all")
def refresh_all_route():
    """Refresh every dataset in one batch. Local maintenance only."""
    if not ALLOW_REFRESH:
        return RedirectResponse(
            "/reliability?refreshed=" + (
                "Refresh is disabled on this deployment. It is a maintainer "
                "action: run it locally with GEOSTATS_ALLOW_REFRESH=1, review "
                "the new vintages, and commit them."
            ),
            status_code=303,
        )
    summary = refresh_many()
    parts = [
        f"{len(summary['new_vintages'])} new vintage(s)",
        f"{len(summary['unchanged'])} unchanged",
    ]
    if summary["failed"]:
        parts.append("failed: " + ", ".join(summary["failed"]))
    if summary["new_vintages"]:
        seed(verbose=False)
        red = {
            dataset_id: check["failed"]
            for dataset_id, check in (summary.get("contracts") or {}).items()
            if check["failed"]
        }
        if red:
            parts.append("contracts red on " + ", ".join(
                f"{d} {codes}" for d, codes in red.items()
            ))
    return RedirectResponse(
        "/reliability?refreshed=" + "; ".join(parts)[:400], status_code=303
    )


@app.post("/refresh")
def refresh(dataset_id: str = Form(...)):
    if not ALLOW_REFRESH:
        return RedirectResponse(
            "/reliability?refreshed=" + (
                "Refresh is disabled on this deployment. Committed vintages "
                "are served as published; set GEOSTATS_ALLOW_REFRESH=1 to "
                "fetch live from a local checkout."
            ),
            status_code=303,
        )
    result = ingest.refresh(dataset_id)
    if result.get("ok") and result.get("new_vintage"):
        seed(verbose=False)
        message = (
            f"New vintage {result['new_vintage']} written. "
            + _describe_diff(result.get("diff"))
        )
    elif result.get("ok"):
        message = result.get("message", "No change.")
    else:
        message = f"Refresh failed, vintages untouched. {result.get('error', '')}"
    return RedirectResponse(
        f"/reliability?refreshed={message[:400]}", status_code=303
    )


def _describe_diff(diff: dict | None) -> str:
    if not diff:
        return "No previous vintage to compare against."
    parts = []
    if diff["changed"]:
        first = diff["changed"][0]
        parts.append(
            f"{len(diff['changed'])} value(s) revised, e.g. {first['period']} "
            f"{first['breakdown_code']} changed from {first['old_value']} to "
            f"{first['new_value']}"
        )
    if diff["added"]:
        parts.append(f"{len(diff['added'])} series added")
    if diff["removed"]:
        parts.append(f"{len(diff['removed'])} series removed")
    if diff["preliminary_flag_changes"]:
        parts.append(
            f"{len(diff['preliminary_flag_changes'])} preliminary flag change(s)"
        )
    return "; ".join(parts) if parts else "Structure and values identical."


# --------------------------------------------------------------------------
# /ask
# --------------------------------------------------------------------------

@app.get("/ask", response_class=HTMLResponse)
def ask_page(request: Request, q: str = Query("")):
    answer = ask(conn, q) if q else None
    worked = [(question, ask(conn, question)) for question in EXAMPLES]
    return render("ask.html", shell(
        request, "/ask", q=q, answer=answer, examples=worked,
        approved=APPROVED_METRICS, qs=_lang_qs(request),
    ))


# --------------------------------------------------------------------------
# /lab
# --------------------------------------------------------------------------

@app.get("/lab", response_class=HTMLResponse)
def lab(
    request: Request,
    dataset_id: str = Query(WAGE_DATASET),
    fault_id: str = Query(""),
):
    if dataset_id not in ADAPTERS:
        dataset_id = WAGE_DATASET
    vintage_id = db.latest_vintage_id(conn, dataset_id)
    result = report = None
    if fault_id in FAULTS_BY_ID and vintage_id:
        cpi_rows = ingest.read_rows(CPI_DATASET,
                                    db.latest_vintage_id(conn, CPI_DATASET))
        result = inject(dataset_id, vintage_id, fault_id, cpi_rows=cpi_rows)
        report = defect_report(result)
    return render("lab.html", shell(
        request, "/lab", faults=FAULTS, fault_id=fault_id,
        dataset_id=dataset_id, datasets=list(ADAPTERS.items()),
        vintage_id=vintage_id, result=result, report=report,
        contracts=CONTRACTS, qs=_lang_qs(request),
    ))


# --------------------------------------------------------------------------
# /methodology
# --------------------------------------------------------------------------

@app.get("/case-study", response_class=HTMLResponse)
def case_study(request: Request):
    """The engineering narrative, with every number read live from the index.

    Nothing on this page is a typed-in statistic. If a dataset is added or a
    contract starts failing, the case study changes with it - which is the only
    way a page that claims a system works can be trusted to still be true.
    """
    stats = db.summary(conn)
    totals = contract_totals()

    red = []
    for row in db.failing_checks(conn):
        red.append({
            "dataset_id": row["dataset_id"],
            "code": row["code"],
            "message": row["message"],
            "explained": known_failure(row["dataset_id"], row["code"]),
        })

    # A real revision, found by diffing two genuine releases of one dataset.
    history = ingest.vintage_history(REGION_DATASET)
    revision = next(
        (h for h in history if h.get("diff") and (
            h["diff"]["added"] or h["diff"]["changed"])),
        None,
    )

    # A live fault injection, run now against a committed vintage, so the claim
    # that the contracts bite is demonstrated rather than asserted.
    demo_fault = FAULTS_BY_ID["mislabel_era"]
    demo = inject(
        WAGE_DATASET, db.latest_vintage_id(conn, WAGE_DATASET),
        demo_fault.fault_id,
    )

    answered = ask(conn, "What was the average salary in 2024?")
    refused = ask(conn, "What is the 90th percentile salary in Georgia?")

    grains = {}
    for dataset_id, adapter in ADAPTERS.items():
        grains.setdefault(adapter.period_grain, []).append(dataset_id)

    return render("case_study.html", shell(
        request, "/case-study",
        stats=stats, totals=totals, red=red,
        datasets=[(d, ADAPTERS[d]) for d in ADAPTERS],
        contracts=CONTRACTS, faults=FAULTS,
        revision=revision, demo=demo, demo_fault=demo_fault,
        answered=answered, refused=refused,
        grains=grains,
        px_tables=PX_TABLES,
        px_snapshots={d: read_snapshot(d)[1] for d in PX_TABLES if read_snapshot(d)},
        region_count=len(geography.RANKABLE_REGIONS),
        breaks={d: series_breaks(d) for d in ADAPTERS if series_breaks(d)},
        # One representative break for the prose. The same ICLS-19 boundary is
        # declared on both labour force datasets, and listing it twice reads as
        # two separate findings.
        primary_break=next(
            (b for d in ADAPTERS for b in series_breaks(d)), None
        ),
        source_pages=sorted({a.source_page for a in ADAPTERS.values()}),
        qs=_lang_qs(request),
    ))


@app.get("/methodology", response_class=HTMLResponse)
def methodology(request: Request):
    wage = wage_map()
    cpi = cpi_map()
    era_rows = []
    for period, unit, value in conn.execute(
        """SELECT period, unit, value FROM observations
            WHERE dataset_id = ? AND indicator_code = ? AND breakdown_code = 'total'
              AND vintage_id = (SELECT vintage_id FROM vintages
                                 WHERE dataset_id = ? AND is_latest = 1)
              AND value IS NOT NULL
         ORDER BY period""",
        (WAGE_DATASET, WAGE_INDICATOR, WAGE_DATASET),
    ).fetchall():
        era_rows.append({"period": period, "unit": unit, "value": value})
    return render("methodology.html", shell(
        request, "/methodology",
        adapters=list(ADAPTERS.values()), contracts=CONTRACTS,
        era_rows=era_rows, currency_name=currency_name,
        cpi_first=min(cpi) if cpi else None, cpi_last=max(cpi) if cpi else None,
        wage_first=min(wage) if wage else None,
        wage_last=max(wage) if wage else None,
        gel_era_start=GEL_ERA_START,
        approved=APPROVED_METRICS,
        summary=db.summary(conn),
        ka_coverage=i18n.KA_COVERAGE,
    ))
