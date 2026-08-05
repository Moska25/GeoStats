"""Route smoke tests: every nav page renders and shows its caveats."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import NAV, SECONDARY_NAV, app

# Every page the site serves, not only the ones in the primary nav. Moving a
# page into the footer must not quietly drop it out of the route tests, which
# is exactly what happened when the navigation was reorganised: parametrising
# over NAV alone silently reduced coverage by two pages.
ALL_PAGES = (
    [href for href, _ in NAV]
    + [href for href, _ in SECONDARY_NAV]
    + ["/atlas"]
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def flat(html: str) -> str:
    """Collapse whitespace so assertions are not hostage to line wrapping."""
    return re.sub(r"\s+", " ", html)


@pytest.mark.parametrize("path", ALL_PAGES)
def test_every_page_returns_200(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "<h1>" in response.text


def test_overview_states_the_gross_caveat_next_to_the_numbers(client):
    body = flat(client.get("/").text)
    assert "gross, before personal income tax" in body
    assert "not take-home pay" in body


def test_overview_shows_the_currency_era_story(client):
    body = client.get("/").text
    assert "Rouble" in body and "Coupon" in body and "Lari" in body
    assert "1995" in body


def test_explorer_defaults_to_the_lari_era(client):
    body = client.get("/explorer").text
    assert 'value="1970"' not in body, "pre-1995 years must not be in the default range"
    assert 'value="1995"' in body


def test_explorer_warns_when_the_range_crosses_a_currency_boundary(client):
    body = client.get("/explorer?include_pre_gel=1&year_from=1990&year_to=2000").text
    assert "mixes currency eras" in body


def test_reliability_shows_checksums_and_retrieval_times(client):
    body = client.get("/reliability").text
    assert "sha256" in body
    assert "Retrieved" in body


def test_reliability_detail_shows_the_vintage_log(client):
    body = client.get("/reliability/earnings_by_region").text
    assert "Vintage log" in body
    assert "2020-10-13T14-57-22Z" in body


def test_ask_page_shows_refusals_among_the_examples(client):
    body = client.get("/ask").text
    assert "refused" in body
    assert "The refusal is the feature" in body


def test_ask_answers_a_query_string_question(client):
    body = client.get("/ask", params={"q": "What is 1000 GEL from 2015 worth in 2024?"}).text
    assert "purchasing_power" in body


def test_lab_runs_a_fault_and_reports_immutability(client):
    body = client.get("/lab", params={"fault_id": "mislabel_era"}).text
    assert "caught by CURRENCY_ERA" in body
    assert "intact" in body


def test_methodology_lists_every_source_url(client):
    from app.adapters import ADAPTERS

    body = client.get("/methodology").text
    for adapter in ADAPTERS.values():
        assert adapter.url in body


def test_georgian_toggle_changes_the_navigation(client):
    body = client.get("/", params={"lang": "ka"}).text
    assert "მიმოხილვა" in body
    assert "მეთოდოლოგია" in body


def test_georgian_page_admits_its_own_partial_coverage(client):
    body = client.get("/", params={"lang": "ka"}).text
    assert "Georgian covers" in body


def test_unknown_dataset_detail_redirects(client):
    response = client.get("/reliability/not_a_dataset", follow_redirects=False)
    assert response.status_code == 303


def test_regions_ranks_by_value_and_indexes_against_the_national_figure(client):
    """The atlas ranking table, read back through the CSV it exports so the
    assertion is on the same rows the page renders rather than on markup."""
    import csv as csvmod
    import io

    response = client.get(
        "/regions", params={"metric": "earnings", "year": "2024", "format": "csv"})
    rows = list(csvmod.DictReader(io.StringIO(response.text)))
    assert len(rows) == 11, "eleven regions, national excluded from the ranking"
    assert rows[0]["region"] == "Tbilisi"
    values = [float(r["value"]) for r in rows]
    assert values == sorted(values, reverse=True)
    # Tbilisi 2,348.7 against a national 1,970.77 is an index of 119.2.
    assert rows[0]["index_georgia_100"] == "119.2"
    assert "119.2" in client.get(
        "/regions", params={"metric": "earnings", "year": "2024"}).text


def test_regions_states_the_head_office_caveat_as_a_warning(client):
    body = flat(client.get("/regions", params={"metric": "earnings"}).text)
    assert "note note-warn" in body, "the caveat must be styled as a warning, not buried"
    assert "head office" in body
    assert "inflates Tbilisi" in body


def test_regions_swaps_the_caveat_with_the_measure(client):
    """The head-office effect is a property of the enterprise survey. The
    household survey counts people where they live, so repeating the same
    warning there would be wrong."""
    earnings = flat(client.get("/regions", params={"metric": "earnings"}).text)
    household = flat(client.get(
        "/regions", params={"metric": "household_income"}).text)
    assert "head office" in earnings
    assert "head office" not in household
    assert "where the household lives" in household


def test_the_old_atlas_url_still_resolves(client):
    """The atlas moved to /regions. Shared links must not rot."""
    response = client.get(
        "/atlas", params={"metric": "earnings"}, follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"].startswith("/regions")
    assert "metric=earnings" in response.headers["location"]


def test_the_spread_exhibit_appears_only_for_earnings(client):
    """It is the one regional measure published far enough back for a spread
    between the extremes to say anything."""
    assert "The spread over time" in client.get(
        "/regions", params={"metric": "earnings"}).text
    assert "The spread over time" not in client.get(
        "/regions", params={"metric": "population"}).text


def test_regions_falls_back_to_the_latest_year_for_an_unpublished_one(client):
    body = client.get("/regions", params={"year": "1812"}).text
    assert 'value="2024" selected' in body


def test_regions_spread_exhibit_plots_against_a_national_reference_line(client):
    body = flat(client.get("/regions").text)
    assert "Highest region" in body and "Lowest region" in body
    assert "stroke-dasharray" in body, "the national reference must be dashed"
    assert "No trend is fitted and none is claimed" in body


def test_salary_scale_places_three_points_on_one_axis_from_zero(client):
    body = client.get("/salary", params={"amount": "3000"}).text
    pcts = [float(x) for x in re.findall(r"left: ([\d.]+)%", body)]
    assert len(pcts) == 3, "median, mean and the entered amount"
    # 3000 is the largest of the three, so it sits at 1/1.08 of the axis
    assert max(pcts) == pytest.approx(92.59, abs=0.05)
    assert "not a percentile" in flat(body)


def test_salary_scale_handles_an_amount_below_both_published_figures(client):
    body = client.get("/salary", params={"amount": "10"}).text
    pcts = [float(x) for x in re.findall(r"left: ([\d.]+)%", body)]
    assert min(pcts) < 1.0, "a tiny amount still gets a mark, near zero"
    assert max(pcts) == pytest.approx(92.59, abs=0.05)


def test_unknown_url_returns_a_styled_404_that_lists_the_real_pages(client):
    # lang is pinned because the shared client carries whatever cookie the
    # previous test left, and the nav appends ?lang= to every href in Georgian.
    response = client.get("/not-a-page", params={"lang": "en"})
    assert response.status_code == 404
    assert "<h1>Page not found</h1>" in response.text
    for href, _ in NAV:
        assert f'href="{href}"' in response.text


def test_the_404_page_is_bilingual_like_every_other_page(client):
    response = client.get("/not-a-page", params={"lang": "ka"})
    assert response.status_code == 404
    assert "მეთოდოლოგია" in response.text


@pytest.mark.parametrize("path", ALL_PAGES)
def test_every_data_table_is_announced_to_screen_readers(client, path):
    body = client.get(path).text
    tables = body.count('<table class="data">')
    captions = body.count('<caption class="visually-hidden">')
    assert captions == tables, f"{path}: {tables} tables but {captions} captions"


def test_methodology_is_a_numbered_document_with_working_anchors(client):
    body = client.get("/methodology").text
    for anchor in ["measure", "currency", "formulas", "contracts", "sources", "limitations"]:
        assert f'id="{anchor}"' in body
        assert f'href="#{anchor}"' in body
    assert "pill-fail" not in body, "red is for failures, not for emphasis"


# -- the story pages -------------------------------------------------------

def test_work_page_names_the_definition_break_it_crosses(client):
    """The 2009/2010 ICLS-19 change is the labour-market cousin of the currency
    trap: no value check can see it, so the page has to say it."""
    body = flat(client.get("/work").text)
    assert "2009" in body and "2010" in body
    assert "ICLS-19" in body
    assert "definition" in body.lower()


def test_work_page_refuses_a_dual_axis(client):
    """Real earnings and unemployment are on separate panels on purpose."""
    body = flat(client.get("/work").text)
    assert "separate axes" in body
    assert "own scale" in body


def test_work_summary_flags_comparisons_that_cross_the_break(client):
    body = flat(client.get("/work").text)
    assert "crosses the 2009/2010" in body
    assert "one consistent definition" in body


def test_households_never_calls_the_gap_a_savings_rate(client):
    body = flat(client.get("/households").text)
    assert "not a savings rate" in body
    assert "reporting artefact" in body


def test_households_shows_missing_regions_rather_than_imputing(client):
    """A region the survey could not publish must be a gap, not an estimate.

    lang is pinned because the shared client carries whatever cookie the
    previous test left behind.
    """
    body = flat(client.get("/households", params={"year": "2011", "lang": "en"}).text)
    assert "Not published for every region" in body
    assert "no regional average is imputed" in body


def test_atlas_labels_itself_a_cartogram_not_a_map(client):
    body = flat(client.get("/atlas").text)
    assert "cartogram, not a map" in body
    assert "equal square" in body


def test_atlas_excludes_aggregate_buckets_from_the_ranking(client):
    """`Other regions` and `Unknown` are residual buckets, not places."""
    body = client.get("/atlas?metric=household_income").text
    assert "Other regions" not in body
    assert ">Unknown<" not in body


def test_atlas_offers_no_composite_score(client):
    body = flat(client.get("/atlas?region=kakheti").text)
    assert "no combined score" in body or "no composite score" in body


def test_case_study_reports_live_counts_not_typed_ones(client):
    from app.main import conn
    from app import db
    body = client.get("/case-study").text
    stats = db.summary(conn)
    assert f"{stats['observations']:,}" in body
    assert str(stats["vintages"]) in body


def test_case_study_runs_a_real_fault_injection(client):
    body = flat(client.get("/case-study").text)
    assert "Vintage untouched" in body
    assert "CURRENCY_ERA" in body


def test_case_study_lists_every_red_check_with_its_reason(client):
    body = client.get("/case-study").text
    assert "UNDOCUMENTED" not in body, (
        "a contract is failing with no entry in KNOWN_FAILURES"
    )


# -- the generalised explorer ---------------------------------------------

@pytest.mark.parametrize("dataset,indicator", [
    ("labour_force", "unemployment_rate_percentage"),
    ("household_income", "income_total"),
    ("population", "population_1_january"),
    ("tourism_by_region", "domestic_visits"),
    ("business_demography", "enterprise_births"),
    ("gender_pay_gap", "adjusted_gpg_hourly"),
])
def test_explorer_opens_on_any_dataset(client, dataset, indicator):
    response = client.get(
        "/explorer", params={"dataset": dataset, "indicator": indicator})
    assert response.status_code == 200
    assert dataset in response.text


def test_explorer_still_defaults_to_the_lari_era_for_wages(client):
    """Generalising the explorer must not lose the safe default."""
    body = client.get("/explorer").text
    assert 'value="1970"' not in body


def test_explorer_degrades_an_unknown_selection_instead_of_erroring(client):
    """A shared URL outlives the vintage it was copied from."""
    response = client.get("/explorer", params={
        "dataset": "not_a_dataset", "indicator": "nonsense",
        "breakdown": "nonsense", "grain": "hourly",
    })
    assert response.status_code == 200


def test_explorer_can_read_a_superseded_vintage_and_says_so(client):
    response = client.get("/explorer", params={
        "dataset": "earnings_by_region", "vintage": "2020-10-13T14-57-22Z",
    })
    assert response.status_code == 200
    assert "superseded vintage" in flat(response.text)


def test_csv_export_matches_the_html_selection_exactly(client):
    """The download and the table read from the same query, so they cannot
    drift. A CSV that disagrees with the page it came from is worse than none."""
    params = {"dataset": "labour_force",
              "indicator": "unemployment_rate_percentage",
              "breakdown": "country.georgia",
              "year_from": "2015", "year_to": "2020"}
    page = client.get("/explorer", params=params)
    csv_response = client.get("/explorer", params={**params, "format": "csv"})
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv_response.headers["content-disposition"]

    import csv as csvmod
    import io
    rows = list(csvmod.DictReader(io.StringIO(csv_response.text)))
    assert rows, "csv is empty"
    periods = [r["period"] for r in rows]
    assert periods == ["2015", "2016", "2017", "2018", "2019", "2020"]
    for row in rows:
        assert row["dataset_id"] == "labour_force"
        assert row["unit"] == "percent"
        assert row["vintage_id"]
        assert row["source_url"].startswith("https://geostat.ge/")
        assert row["is_preliminary"] in {"0", "1"}
    # every period on the page is in the download
    for period in periods:
        assert f">{period}<" in page.text


def test_csv_carries_provenance_on_every_row(client):
    """A figure that loses its caveats on the way into a spreadsheet is how a
    caveated number becomes an uncaveated one."""
    import csv as csvmod
    import io
    response = client.get("/explorer", params={
        "dataset": "earnings_annual", "format": "csv"})
    rows = list(csvmod.DictReader(io.StringIO(response.text)))
    assert rows
    for field in ("dataset_id", "vintage_id", "unit", "is_preliminary",
                  "source_url", "status", "raw"):
        assert all(field in r for r in rows)


# -- production is read-only ----------------------------------------------

def test_refresh_is_refused_when_the_deployment_is_read_only(client):
    """A deployed copy serves committed vintages and never calls Geostat."""
    from app import main
    assert main.ALLOW_REFRESH is False, "tests must run with refresh disabled"
    response = client.post("/refresh", data={"dataset_id": "labour_force"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert "disabled" in response.headers["location"]


def test_batch_refresh_is_refused_too(client):
    response = client.post("/refresh-all", follow_redirects=False)
    assert response.status_code == 303
    assert "disabled" in response.headers["location"]


def test_health_endpoint_reports_the_index_and_any_surprise_failure(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["observations"] > 0
    assert payload["datasets"] > 0
    assert payload["undocumented_contract_failures"] == []
    assert payload["refresh_enabled"] is False


# -- responsive and accessibility invariants -------------------------------

@pytest.mark.parametrize("path", ALL_PAGES)
@pytest.mark.parametrize("lang", ["en", "ka"])
def test_every_wide_table_sits_in_a_scroll_container(client, path, lang):
    """A data table wider than 375px is fine; a *page* wider than 375px is not.
    The rule that keeps both true is that every table lives inside
    `.table-wrap`, which scrolls on its own. This asserts the rule rather than
    the pixel measurement, because the measurement needs a browser and the rule
    is what actually holds the layout together.
    """
    body = client.get(path, params={"lang": lang}).text
    tables = body.count('<table class="data">')
    if not tables:
        return
    wraps = body.count('<div class="table-wrap">')
    assert wraps >= tables, (
        f"{path} ({lang}): {tables} data tables but only {wraps} scroll wrappers"
    )


@pytest.mark.parametrize("path", ALL_PAGES)
def test_no_static_inline_presentation_styles_remain(client, path):
    """Inline styles cannot be overridden by a media query, so every static one
    is a hole in the responsive layout. Data-driven values (a computed bar
    width, a dot's position) are exempt: a percentage that changes per row has
    no stylesheet to live in."""
    import re as _re
    body = client.get(path).text
    inline = _re.findall(r'style="([^"]*)"', body)
    static = [
        s for s in inline
        if not _re.search(r"\d+(\.\d+)?%", s) and "var(--series" not in s
    ]
    assert not static, f"{path} carries static inline styles: {static[:5]}"


# -- the overview labour-market section (GEO-8.3) --------------------------

def test_overview_shows_unemployment_beside_real_wages(client):
    body = flat(client.get("/", params={"lang": "en"}).text)
    assert "labour market beside real wages" in body
    assert "Unemployment rate (%)" in body
    assert "Real earnings" in body


def test_overview_states_the_ilo_age_15_definition_in_a_note(client):
    """A rate is meaningless without saying who is counted. Someone who stopped
    looking for work is outside the labour force, not unemployed."""
    body = flat(client.get("/", params={"lang": "en"}).text)
    assert "ILO definition, ages 15 and over" in body
    assert "stopped looking" in body
    assert "note" in body


def test_overview_labour_panels_are_not_a_dual_axis(client):
    """Two panels, two scales, one shared x. Not two lines on one pair of axes
    where the choice of scales decides how the relationship looks."""
    body = client.get("/").text
    assert body.count('class="panel"') >= 2


# -- atlas CSV export (GEO-17.2) ------------------------------------------

def test_atlas_exports_the_ranking_as_csv(client):
    import csv as csvmod
    import io

    params = {"metric": "earnings", "year": "2024"}
    page = client.get("/atlas", params={**params, "lang": "en"})
    response = client.get("/atlas", params={**params, "format": "csv"})
    assert response.headers["content-type"].startswith("text/csv")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert "earnings" in disposition and "2024" in disposition

    rows = list(csvmod.DictReader(io.StringIO(response.text)))
    assert len(rows) == 11, "eleven rankable regions"
    assert rows[0]["region"] == "Tbilisi"
    assert rows[0]["rank"] == "1"
    # the header names the unit, and every row carries its provenance
    for row in rows:
        assert row["unit"] == "GEL / month"
        assert row["dataset_id"] == "earnings_by_region"
        assert row["vintage_id"]
        assert row["source_url"].startswith("https://geostat.ge/")
    # and the CSV agrees with what the page rendered
    for row in rows:
        assert row["region"] in page.text


def test_atlas_csv_follows_the_selected_metric(client):
    import csv as csvmod
    import io

    response = client.get(
        "/atlas", params={"metric": "unemployment", "format": "csv"})
    rows = list(csvmod.DictReader(io.StringIO(response.text)))
    assert rows
    assert all(r["unit"] == "%" for r in rows)
    assert all(r["dataset_id"] == "labour_force_by_region" for r in rows)


# -- grain selection survives in the query string (GEO-9.3) ---------------

def test_explorer_grain_choice_is_preserved_in_the_query_string(client):
    body = client.get("/explorer", params={
        "dataset": "earnings_quarterly", "grain": "quarterly"}).text
    assert 'name="grain"' in body
    assert 'value="quarterly" selected' in body
    # and the periods drawn really are quarters
    assert "-Q1" in body or "-Q4" in body


def test_explorer_quarterly_chart_is_drawn_from_quarterly_rows(client):
    import csv as csvmod
    import io

    response = client.get("/explorer", params={
        "dataset": "earnings_quarterly", "grain": "quarterly", "format": "csv"})
    rows = list(csvmod.DictReader(io.StringIO(response.text)))
    assert rows
    assert all("-Q" in r["period"] for r in rows)
