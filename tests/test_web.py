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
