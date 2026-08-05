"""Route smoke tests: every nav page renders and shows its caveats."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import NAV, app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def flat(html: str) -> str:
    """Collapse whitespace so assertions are not hostage to line wrapping."""
    return re.sub(r"\s+", " ", html)


@pytest.mark.parametrize("path", [href for href, _ in NAV])
def test_every_nav_route_returns_200(client, path):
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
    body = client.get("/regions", params={"year": "2024"}).text
    labels = re.findall(r'rank-label">([^<]+)<', body)
    values = [
        float(v.replace(",", "")) for v in re.findall(r'rank-value">([\d,.]+)<', body)
    ]
    assert len(labels) == 11, "eleven regions, national excluded from the ranking"
    assert labels[0].strip() == "Tbilisi"
    assert values == sorted(values, reverse=True)
    # Tbilisi 2,348.7 against a national 1,970.77 is an index of 119.2.
    assert "119.2" in body


def test_regions_states_the_head_office_caveat_as_a_warning(client):
    body = flat(client.get("/regions").text)
    assert "note note-warn" in body, "the caveat must be styled as a warning, not buried"
    assert "head office" in body
    assert "Read Tbilisi with care" in body


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


@pytest.mark.parametrize("path", [href for href, _ in NAV])
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
