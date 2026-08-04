"""The grounded analyst: it answers what it can and refuses what it cannot."""

from __future__ import annotations

import pytest

from app import db
from app.analyst import APPROVED_METRICS, EXAMPLES, ask


@pytest.fixture(scope="module")
def conn():
    connection = db.connect()
    db.bootstrap(connection)
    yield connection
    connection.close()


# -- answers ---------------------------------------------------------------

def test_level_question_returns_the_published_value(conn):
    a = ask(conn, "What was the average monthly wage in 2024?")
    assert a.kind == "answer"
    assert a.intent == "earnings_level"
    assert "1,970.77" in a.headline


def test_answer_always_carries_full_provenance(conn):
    a = ask(conn, "What was the average monthly wage in 2024?")
    p = a.provenance[0]
    for field in ("dataset_id", "indicator_code", "breakdown_code", "period",
                  "unit", "vintage_id", "is_preliminary", "source_url"):
        assert field in p, f"provenance is missing {field}"
    assert p["source_url"].startswith("https://geostat.ge/")
    assert a.formula


def test_preliminary_status_is_surfaced_not_hidden(conn):
    a = ask(conn, "What was the average monthly wage in 2025?")
    assert a.provenance[0]["is_preliminary"] is True
    assert "preliminary" in a.headline.lower() or "preliminary" in a.explanation.lower()


def test_pre_1995_question_answers_in_the_right_currency_and_warns(conn):
    a = ask(conn, "What was the average wage in 1993?")
    assert a.kind == "answer"
    assert "KUP" in a.headline
    assert "Coupon" in a.explanation
    assert a.provenance[0]["unit"] == "KUP"


def test_purchasing_power_question(conn):
    a = ask(conn, "What is 1000 GEL from 2015 worth in 2024?")
    assert a.intent == "purchasing_power"
    assert a.kind == "answer"
    assert "1,000.00 GEL in 2015" in a.headline


def test_growth_question_reports_nominal_and_real(conn):
    a = ask(conn, "How much has the average wage grown from 2018 to 2024?")
    assert a.intent == "growth"
    labels = {row["label"] for row in a.table}
    assert "Nominal growth" in labels and "Real growth" in labels


def test_base_year_is_taken_as_the_earlier_year_whatever_the_word_order(conn):
    a = ask(conn, "What are real earnings in 2024 with 2010 as the base?")
    b = ask(conn, "What are real earnings from 2010 to 2024 in real terms?")
    assert a.intent == b.intent == "real_earnings_index"
    assert "2010 = 100" in a.headline


def test_mean_median_question_names_both_sources(conn):
    a = ask(conn, "What is the gap between the mean and the median in 2024?")
    assert a.intent == "mean_median_gap"
    assert "Revenue Service" in a.explanation
    assert "high earners" in a.caveat


def test_inflation_question(conn):
    a = ask(conn, "How much inflation was there between 2020 and 2024?")
    assert a.intent == "cumulative_inflation"
    assert "%" in a.headline


def test_region_question_ranks_and_states_the_head_office_caveat(conn):
    a = ask(conn, "Which region had the highest average pay in 2024?")
    assert a.intent == "region_ranking"
    assert "Tbilisi" in a.headline
    assert "head office" in a.caveat


def test_gender_gap_says_it_is_unadjusted(conn):
    a = ask(conn, "What is the gender pay gap in 2024?")
    assert a.intent == "gender_gap"
    assert "unadjusted" in a.explanation.lower()


# -- refusals: the headline feature ---------------------------------------

@pytest.mark.parametrize("question,intent", [
    ("What is the 90th percentile salary in Georgia?", "distribution_percentile"),
    ("Show me the salary distribution for 2024", "distribution_percentile"),
    ("What does a software engineer earn in Imereti?", "occupation_cross"),
    ("What is the average take-home pay after tax in 2024?", "net_pay"),
    ("What will the average wage be in 2030?", "forecast"),
    ("What is the median wage in Adjara?", "median_by_region"),
])
def test_refusals(conn, question, intent):
    a = ask(conn, question)
    assert a.is_refusal, f"{question!r} should have been refused"
    assert a.intent == intent
    assert a.explanation, "a refusal must explain itself"
    assert a.formula == "no metric executed"


def test_percentile_refusal_explains_why_it_cannot_be_derived(conn):
    a = ask(conn, "What is the 90th percentile salary in Georgia?")
    assert "mean and a median" in a.headline
    assert "cannot be reconstructed" in a.explanation
    assert a.missing


def test_refusal_never_carries_a_computed_number(conn):
    for question in ("What is the 90th percentile salary in Georgia?",
                     "What is the average take-home pay after tax in 2024?"):
        a = ask(conn, question)
        assert a.provenance == [], "a refusal must not attach a source to a non-answer"
        assert a.table == []


def test_out_of_range_year_is_refused_rather_than_extrapolated(conn):
    a = ask(conn, "What was the average wage in 1965?")
    assert a.kind in {"refusal", "unmatched"}
    assert "extrapolate" in a.explanation or "No approved metric" in a.headline


def test_unmatched_question_is_not_answered(conn):
    a = ask(conn, "who is the president of georgia")
    assert a.kind == "unmatched"
    assert "No approved metric" in a.headline


def test_empty_question_is_handled(conn):
    assert ask(conn, "").kind == "unmatched"


# -- the closed metric set -------------------------------------------------

def test_all_worked_examples_route_to_a_definite_outcome(conn):
    for question in EXAMPLES:
        a = ask(conn, question)
        assert a.kind in {"answer", "refusal"}, f"{question!r} fell through"
        assert a.headline


def test_the_examples_include_real_refusals(conn):
    outcomes = [ask(conn, q).kind for q in EXAMPLES]
    assert outcomes.count("refusal") >= 4
    assert outcomes.count("answer") >= 8


def test_approved_metric_list_is_not_empty_and_names_real_functions():
    from app import metrics

    assert len(APPROVED_METRICS) >= 8
    for name, formula in APPROVED_METRICS:
        assert formula
        assert hasattr(metrics, name.split(".", 1)[1])
