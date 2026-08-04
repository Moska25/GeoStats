"""FastAPI routes. Thin on purpose - all the logic lives in importable modules.

Port 8013.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import charts, db, i18n, ingest, metrics
from .adapters import ADAPTERS, GEL_ERA_START, currency_name
from .analyst import APPROVED_METRICS, EXAMPLES, ask
from .contracts import CONTRACTS
from .faults import FAULTS, FAULTS_BY_ID, defect_report, inject
from .seed import seed

BASE_DIR = Path(__file__).resolve().parent
PROJECT_NAME = "GeoStats"
PORT = 8013

WAGE_DATASET = "earnings_annual"
WAGE_INDICATOR = "avg_monthly_nominal_earnings"
MEDIAN_DATASET = "median_earnings"
MEDIAN_INDICATOR = "median_monthly_earnings"
CPI_DATASET = "cpi_2010_base"
CPI_INDICATOR = "cpi_annual_avg_2010_100"
REGION_DATASET = "earnings_by_region"

NAV = [
    ("/", "nav.overview"),
    ("/explorer", "nav.explorer"),
    ("/salary", "nav.salary"),
    ("/reliability", "nav.reliability"),
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
    ctx = {
        "request": request,
        "project_name": PROJECT_NAME,
        "project_tagline": t("tagline"),
        "nav": [(href, t(key)) for href, key in NAV],
        "active": active,
        "footer_note": t("footer.note"),
        "t": t,
        "lang": lang,
        "languages": i18n.LANGUAGES,
        "lang_note": i18n.untranslated_note(lang),
        "port": PORT,
    }
    ctx.update(extra)
    return ctx


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

    latest_real = deflatable[-1] if deflatable else None
    return render("index.html", shell(
        request, "/",
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

@app.get("/explorer", response_class=HTMLResponse)
def explorer(
    request: Request,
    breakdown: str = Query("total"),
    year_from: str = Query(""),
    year_to: str = Query(""),
    include_pre_gel: int = Query(0),
    base: str = Query("2010"),
):
    valid = {code for code, _ in BREAKDOWN_CHOICES}
    if breakdown not in valid:
        breakdown = "total"
    wage = wage_map(breakdown)
    cpi, median = cpi_map(), median_map()
    prelim = db.preliminary_periods(conn, WAGE_DATASET)

    universe = sorted(wage) if include_pre_gel else gel_era_years(wage)
    if not universe:
        universe = sorted(wage)
    lo = year_from if year_from in universe else universe[0]
    hi = year_to if year_to in universe else universe[-1]
    if lo > hi:
        lo, hi = hi, lo
    picked = [y for y in universe if lo <= y <= hi]

    if base not in cpi:
        deflatable = [y for y in picked if y in cpi]
        base = deflatable[0] if deflatable else "2010"

    series = metrics.build_series(
        {y: wage[y] for y in picked}, cpi,
        median if breakdown == "total" else {},
        base_year=base, preliminary=prelim,
    )
    units = sorted({
        r["unit"] for r in db.series(conn, WAGE_DATASET, WAGE_INDICATOR, breakdown)
        if r["period"] in set(picked)
    })
    mixed_era = len(units) > 1

    chart = charts.line_chart(
        [r["period"] for r in series],
        {
            "Nominal GEL": [r["nominal"] for r in series],
            f"Real, {base} prices": [r["real_gel"] for r in series],
            **({"Median GEL": [r["median"] for r in series]}
               if any(r["median"] for r in series) else {}),
        },
        height=290, value_fmt="{:,.0f}",
    )
    return render("explorer.html", shell(
        request, "/explorer",
        breakdown=breakdown, breakdown_choices=BREAKDOWN_CHOICES,
        universe=universe, year_from=lo, year_to=hi,
        include_pre_gel=include_pre_gel, base=base,
        base_choices=sorted(cpi),
        series=series, chart=chart, units=units, mixed_era=mixed_era,
        gel_era_start=GEL_ERA_START,
        currency_name=currency_name,
        source_url=ADAPTERS[WAGE_DATASET].url,
        vintage_id=db.latest_vintage_id(conn, WAGE_DATASET),
        cpi_years=sorted(cpi),
    ))


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
    return render("salary.html", shell(
        request, "/salary",
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
        })
    return render("reliability.html", shell(
        request, "/reliability", cards=cards, totals=contract_totals(),
        summary=db.summary(conn), refreshed=refreshed,
        contracts=CONTRACTS, qs=_lang_qs(request),
    ))


@app.get("/reliability/{dataset_id}", response_class=HTMLResponse)
def reliability_detail(request: Request, dataset_id: str):
    adapter = ADAPTERS.get(dataset_id)
    if adapter is None:
        return RedirectResponse("/reliability", status_code=303)
    history = ingest.vintage_history(dataset_id)
    latest = db.latest_vintage_id(conn, dataset_id)
    checks = db.contract_results(conn, dataset_id, latest)
    for check in checks:
        pass
    parsed = [
        {**dict(c), "offender_rows": json.loads(c["offenders"])} for c in checks
    ]
    return render("reliability_detail.html", shell(
        request, "/reliability", adapter=adapter, dataset_id=dataset_id,
        history=history, checks=parsed, latest=latest,
        qs=_lang_qs(request),
    ))


@app.post("/refresh")
def refresh(dataset_id: str = Form(...)):
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
