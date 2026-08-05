"""Release expectations, derived rather than scraped.

Geostat publishes a release calendar at <https://www.geostat.ge/en/calendar>,
but it is rendered client-side and exposes no machine-readable feed: the served
HTML contains no dates at all, and probing the obvious JSON endpoints returns
404. Scraping a JavaScript-rendered page would also break this project's
central property, that everything works offline from committed vintages.

So the expectation is computed from the data instead of asserted about it.

Every dataset's cadence is *inferred from its own published periods* - a file
whose periods are `2023, 2024, 2025` publishes annually, one whose periods are
`2025-Q1 … 2025-Q4` publishes quarterly - and the next expected period is the
one after the newest published. That is a statement about the file, derived
from the file, and it is the signal that actually matters: a dataset is stale
when the period it should be covering has not appeared.

What this module deliberately does NOT do is invent a calendar date. Saying
"the 2026 release is expected on 15 March" when no published schedule was read
would be exactly the fabrication the rest of the project refuses. `next_release`
therefore returns the expected *period* with the basis it was derived from, and
`scheduled_date` returns `None` with a reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .adapters import ADAPTERS

NO_FEED_REASON = (
    "Geostat's release calendar is rendered client-side and publishes no "
    "machine-readable feed, so no scheduled date is available for any dataset. "
    "The expectation below is derived from the dataset's own publication "
    "cadence, not from a calendar."
)


@dataclass(frozen=True)
class Expectation:
    """What the next release of a dataset should cover, and why we think so."""

    dataset_id: str
    cadence: str                 # annual | quarterly | monthly | irregular
    latest_period: str
    expected_period: str | None
    basis: str
    overdue: bool
    behind_by: int               # whole periods between expected and latest

    @property
    def summary(self) -> str:
        if self.expected_period is None:
            return f"cadence not inferable from {self.latest_period!r}"
        if not self.overdue:
            return (
                f"current: newest published period is {self.latest_period}, "
                f"and {self.expected_period} is not due yet"
            )
        return (
            f"{self.expected_period} expected, newest published is "
            f"{self.latest_period}"
        )


def infer_cadence(periods: list[str]) -> str:
    """Annual, quarterly or monthly, from the shape of the periods themselves."""
    if not periods:
        return "irregular"
    sample = periods[-1]
    if re.fullmatch(r"\d{4}-Q[1-4]", sample):
        return "quarterly"
    if re.fullmatch(r"\d{4}-\d{2}", sample):
        return "monthly"
    if re.fullmatch(r"\d{4}", sample):
        return "annual"
    return "irregular"


def next_period(period: str, cadence: str) -> str | None:
    """The period after `period` at this cadence."""
    if cadence == "annual" and re.fullmatch(r"\d{4}", period):
        return str(int(period) + 1)
    if cadence == "quarterly":
        match = re.fullmatch(r"(\d{4})-Q([1-4])", period)
        if match:
            year, quarter = int(match.group(1)), int(match.group(2))
            return f"{year + 1}-Q1" if quarter == 4 else f"{year}-Q{quarter + 1}"
    if cadence == "monthly":
        match = re.fullmatch(r"(\d{4})-(\d{2})", period)
        if match:
            year, month = int(match.group(1)), int(match.group(2))
            return f"{year + 1}-01" if month == 12 else f"{year}-{month + 1:02d}"
    return None


def _current_period(cadence: str, today: date) -> str | None:
    """The period `today` falls in."""
    if cadence == "annual":
        return str(today.year)
    if cadence == "quarterly":
        return f"{today.year}-Q{(today.month - 1) // 3 + 1}"
    if cadence == "monthly":
        return f"{today.year}-{today.month:02d}"
    return None


def _distance(a: str, b: str, cadence: str) -> int:
    """Whole periods from `a` to `b`, both at `cadence`."""
    steps = 0
    cursor = a
    while cursor and cursor < b and steps < 240:
        cursor = next_period(cursor, cadence)
        steps += 1
    return steps


def next_release(
    dataset_id: str, periods: list[str], *, today: date | None = None
) -> Expectation | None:
    """What the next release of this dataset should cover.

    Returns `None` when the dataset has no published periods at all, which is
    the only case where nothing can be said.
    """
    today = today or date.today()
    usable = sorted(p for p in periods if p)
    if not usable:
        return None

    cadence = infer_cadence(usable)
    latest = usable[-1]
    expected = next_period(latest, cadence)
    current = _current_period(cadence, today)

    # A release is overdue when the period it would cover has itself finished.
    # A 2026 annual figure is not late in the middle of 2026; a 2025 one is.
    overdue = bool(
        expected and current and expected < current
    )
    behind = _distance(latest, current, cadence) if (current and latest < current) else 0

    return Expectation(
        dataset_id=dataset_id,
        cadence=cadence,
        latest_period=latest,
        expected_period=expected,
        basis=(
            f"cadence inferred as {cadence} from {len(usable)} published "
            f"periods ending {latest}"
        ),
        overdue=overdue,
        behind_by=max(behind - 1, 0),
    )


def scheduled_date(dataset_id: str) -> tuple[None, str]:
    """The published release date for a dataset, which is never available.

    Kept as an explicit function returning `(None, reason)` rather than being
    omitted, because "we did not look" and "there is nothing to look at" are
    different claims and the UI should be able to make the second one.
    """
    if dataset_id not in ADAPTERS:
        return None, f"{dataset_id} is not a known dataset"
    return None, NO_FEED_REASON


def demo() -> None:
    """Self-check on the cadence arithmetic, which is the whole module."""
    assert infer_cadence(["2023", "2024"]) == "annual"
    assert infer_cadence(["2024-Q3", "2024-Q4"]) == "quarterly"
    assert infer_cadence(["2024-11", "2024-12"]) == "monthly"
    assert infer_cadence([]) == "irregular"

    assert next_period("2024", "annual") == "2025"
    assert next_period("2024-Q4", "quarterly") == "2025-Q1"
    assert next_period("2024-Q1", "quarterly") == "2024-Q2"
    assert next_period("2024-12", "monthly") == "2025-01"
    assert next_period("2024", "quarterly") is None

    # An annual file ending 2024, read in 2026: 2025 has finished and is late.
    late = next_release("x", ["2023", "2024"], today=date(2026, 8, 5))
    assert late.overdue and late.expected_period == "2025"
    assert "2025 expected" in late.summary

    # The same file ending 2025 is current: 2026 is not over yet.
    fine = next_release("x", ["2024", "2025"], today=date(2026, 8, 5))
    assert not fine.overdue and fine.expected_period == "2026"
    assert "current" in fine.summary

    assert next_release("x", []) is None
    assert scheduled_date("earnings_annual") == (None, NO_FEED_REASON)
    assert scheduled_date("nope")[0] is None
    print("calendar: ok")


if __name__ == "__main__":
    demo()
