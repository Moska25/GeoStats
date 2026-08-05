"""The region registry, which exists because Geostat spells places four ways."""

from __future__ import annotations

import pytest

from app import geography
from app.geography import RANKABLE_REGIONS, UnknownPlace, normalise_label, resolve
from app.ingest import all_datasets, latest_vintage, read_rows


@pytest.mark.parametrize("spelling", [
    "Adjara A/R", "Adjara A.R.", "Adjara AR", "Ajara", "Adjara", "Adjara A/R*",
])
def test_every_published_spelling_of_adjara_is_one_region(spelling):
    """These four spellings occur in four different committed workbooks. Joining
    on the printed label would produce four regions where there is one."""
    assert resolve(spelling)[0] == "region.adjara"


@pytest.mark.parametrize("spelling,expected", [
    ("Tbilisi", "region.tbilisi"),
    ("The city of Tbilisi", "region.tbilisi"),
    ("C. Tbilisi Municipality", "region.tbilisi"),
    ("Abkhazeti AR", "region.abkhazia"),
    ("Abkhazia A.R.", "region.abkhazia"),
    ("Imereti**", "region.imereti"),
    ("Racha-Lechkhumi and Kvemo Svaneti", "region.racha_lechkhumi"),
    ("Racha-Lechkhumi and Kvemo-Svaneti", "region.racha_lechkhumi"),
    ("Georgia", "country.georgia"),
    ("Total", "country.georgia"),
    ("Other regions**", "aggregate.other_regions"),
    ("Unknown", "aggregate.unknown"),
])
def test_published_spellings_resolve(spelling, expected):
    assert resolve(spelling)[0] == expected


def test_the_same_name_at_two_levels_does_not_collide():
    """Tbilisi is published as a region and as a municipality. A total that
    summed both would count the capital twice."""
    assert resolve("Tbilisi")[0] == "region.tbilisi"
    assert resolve("Tbilisi", level=geography.MUNICIPALITY)[0] == "municipality.tbilisi"
    assert resolve("Tbilisi")[0] != resolve("Tbilisi", level=geography.MUNICIPALITY)[0]


def test_an_unknown_place_raises_rather_than_inventing_a_region():
    """Silently accepting a new spelling is how one region becomes two series
    without anybody noticing."""
    with pytest.raises(UnknownPlace):
        resolve("Atlantis")


def test_aggregates_are_not_ranked_as_regions():
    """`Other regions` and `The remaining regions` are residual buckets. They
    belong in a total and must never appear in a regional ranking."""
    assert "other_regions" not in RANKABLE_REGIONS
    assert "remaining_regions" not in RANKABLE_REGIONS
    assert "unknown" not in RANKABLE_REGIONS
    assert len(RANKABLE_REGIONS) == 11


def test_abkhazia_is_a_region_but_not_rankable():
    """It is published, so it must resolve; its figures cover a handful of
    registered units rather than the territory, so ranking it is meaningless."""
    assert resolve("Abkhazeti AR")[0] == "region.abkhazia"
    assert "abkhazia" not in RANKABLE_REGIONS


def test_normalisation_strips_footnotes_and_the_autonomous_republic_suffix():
    assert normalise_label("Adjara A/R") == "adjara"
    assert normalise_label("Imereti**") == "imereti"
    assert normalise_label("  Kvemo  Kartli ") == "kvemo kartli"


def test_every_regional_dataset_resolves_to_registry_codes():
    """No committed vintage may contain a place code the registry did not mint.
    This is what proves the eight regional workbooks actually join."""
    for dataset_id in all_datasets():
        vintage = latest_vintage(dataset_id)
        if not vintage:
            continue
        for row in read_rows(dataset_id, vintage):
            code = row["breakdown_code"]
            if code.startswith(("region.", "country.", "aggregate.")):
                level, _, name = code.partition(".")
                assert name, f"{dataset_id} produced a bare level {code!r}"


def test_regions_join_across_datasets():
    """The point of the registry: a region code from the household survey must
    be the same string as the one from business demography."""
    def codes(dataset_id):
        return {
            r["breakdown_code"] for r in read_rows(dataset_id, latest_vintage(dataset_id))
            if r["breakdown_code"].startswith("region.")
        }

    household = codes("household_income")
    business = codes("business_demography")
    labour = codes("labour_force_by_region")
    shared = household & business & labour
    assert len(shared) >= 10, (
        f"regional datasets share only {len(shared)} region codes: {sorted(shared)}"
    )
