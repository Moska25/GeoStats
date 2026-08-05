"""Canonical geography registry for Georgian places as Geostat spells them.

Geostat spells the same region differently in different workbooks: the regional
earnings file writes `Adjara A/R`, business demography writes `Adjara AR`,
population writes `Adjara A.R.`, and the labour force file writes `Adjara A/R`
with a footnote marker attached. Joining those files on the printed label would
silently produce four regions where there is one, and a regional ranking built
on that would be wrong in a way no value check could catch.

Every place therefore resolves through `resolve()` to a stable internal code
carrying its own level:

    country.georgia            the national figure
    region.adjara              one of the eleven regions plus Abkhazia
    municipality.batumi        a self-governed unit inside a region
    aggregate.other_regions    a published residual bucket, not a place

The level prefix is not decoration. `Tbilisi` appears in these workbooks as a
region *and* as a municipality, and a total that summed both would double-count
the capital. Prefixing by level makes that collision impossible to express.

An unrecognised label raises rather than inventing a code. If Geostat adds a
region or respells one, the ingest fails loudly on the next refresh instead of
quietly splitting a series in two.
"""

from __future__ import annotations

import re

COUNTRY = "country"
REGION = "region"
MUNICIPALITY = "municipality"
AGGREGATE = "aggregate"


def normalise_label(label: str) -> str:
    """Fold a printed place label to a comparison key.

    Strips footnote markers, punctuation and the autonomous-republic suffix,
    which is written `A/R`, `A.R.` and `AR` across the published files.
    """
    text = str(label).strip().lower()
    text = re.sub(r"[*†‡]+$", "", text).strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\b(a r|ar)\b", " ", text)
    return " ".join(text.split())


# (code, level, display name, extra aliases beyond the normalised display name)
_REGISTRY: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("georgia", COUNTRY, "Georgia", ("total", "georgia total")),
    ("tbilisi", REGION, "Tbilisi",
     ("the city of tbilisi", "c tbilisi municipality", "tbilisi city")),
    ("abkhazia", REGION, "Abkhazia A.R.", ("abkhazeti", "abkhazia")),
    ("adjara", REGION, "Adjara A.R.", ("adjara", "ajara")),
    ("guria", REGION, "Guria", ()),
    ("imereti", REGION, "Imereti", ()),
    ("kakheti", REGION, "Kakheti", ()),
    ("mtskheta_mtianeti", REGION, "Mtskheta-Mtianeti", ()),
    ("racha_lechkhumi", REGION, "Racha-Lechkhumi and Kvemo Svaneti",
     ("racha lechkhumi and kvemo svaneti",)),
    ("samegrelo_zemo_svaneti", REGION, "Samegrelo-Zemo Svaneti", ()),
    ("samtskhe_javakheti", REGION, "Samtskhe-Javakheti", ()),
    ("kvemo_kartli", REGION, "Kvemo Kartli", ()),
    ("shida_kartli", REGION, "Shida Kartli", ()),
    # Published residual buckets. They are not places and must never be ranked
    # against one, but dropping them would break the totals they belong to.
    ("other_regions", AGGREGATE, "Other regions", ("other regions",)),
    ("remaining_regions", AGGREGATE, "The remaining regions",
     ("the remaining regions",)),
    ("unknown", AGGREGATE, "Unknown", ("unknown",)),
]

_BY_ALIAS: dict[str, tuple[str, str, str]] = {}
for _code, _level, _name, _aliases in _REGISTRY:
    for _alias in (normalise_label(_name), *_aliases):
        _BY_ALIAS[_alias] = (_code, _level, _name)

# The eleven regions Geostat ranks, in its own published order, plus Abkhazia.
# Abkhazia is published but effectively unenumerated: its figures cover a
# handful of registered units, not the territory.
RANKABLE_REGIONS = [
    code for code, level, _n, _a in _REGISTRY
    if level == REGION and code != "abkhazia"
]


class UnknownPlace(KeyError):
    """A place label that is not in the registry.

    Deliberately fatal. A new spelling must be added here on purpose, because
    the alternative is a region that silently splits into two series.
    """


def resolve(label: str, *, level: str | None = None) -> tuple[str, str]:
    """Return (breakdown_code, display name) for a printed place label.

    `level` overrides the registry level, which is how the population workbook
    marks a municipality that shares its name with its region.
    """
    key = normalise_label(label)
    hit = _BY_ALIAS.get(key)
    if hit is None:
        if level == MUNICIPALITY:
            # Municipalities are not enumerated in the registry: there are 69
            # of them, they carry no cross-file spelling conflict, and their
            # printed name is already unique inside its level.
            return f"{MUNICIPALITY}.{_slug(key)}", str(label).strip()
        raise UnknownPlace(
            f"{label!r} (normalised {key!r}) is not a known Georgian place. "
            "Add it to app/geography.py rather than letting it become a new "
            "region by accident."
        )
    code, registry_level, name = hit
    return f"{level or registry_level}.{code}", name


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "unknown"


# Names short enough to sit inside a 76px cartogram tile. Georgian regional
# names are long and hyphenated; truncating them mid-word produced tiles
# reading "Samegrelo-Zem" and "Racha-Lechkhu", which is worse than an
# abbreviation chosen on purpose.
SHORT_NAMES = {
    "samegrelo_zemo_svaneti": "Samegrelo",
    "racha_lechkhumi": "Racha-Lech.",
    "mtskheta_mtianeti": "Mtskheta-Mt.",
    "samtskhe_javakheti": "Samtskhe-Jav.",
    "kvemo_kartli": "Kvemo Kartli",
    "shida_kartli": "Shida Kartli",
    "adjara": "Adjara",
    "abkhazia": "Abkhazia",
}


def short_name(breakdown_code: str) -> str:
    """Cartogram-sized label for a region code."""
    _level, _, code = breakdown_code.partition(".")
    code = code or breakdown_code
    return SHORT_NAMES.get(code, display_name(breakdown_code))


def is_region(breakdown_code: str) -> bool:
    return breakdown_code.startswith(f"{REGION}.")


def display_name(breakdown_code: str) -> str:
    """Human label for a resolved code, for chart axes and table headers."""
    _level, _, code = breakdown_code.partition(".")
    for reg_code, _lvl, name, _a in _REGISTRY:
        if reg_code == code:
            return name
    return code.replace("_", " ").title()


def demo() -> None:
    """Self-check: the spellings that actually occur in the committed files."""
    for spelling in ("Adjara A/R", "Adjara A.R.", "Adjara AR", "Ajara"):
        assert resolve(spelling)[0] == "region.adjara", spelling
    for spelling in ("Tbilisi", "The city of Tbilisi", "C. Tbilisi Municipality"):
        assert resolve(spelling)[0] == "region.tbilisi", spelling
    assert resolve("Imereti**")[0] == "region.imereti"
    assert resolve("Racha-Lechkhumi and Kvemo-Svaneti")[0] == "region.racha_lechkhumi"
    assert resolve("Racha-Lechkhumi and Kvemo Svaneti")[0] == "region.racha_lechkhumi"
    assert resolve("Georgia")[0] == "country.georgia"
    assert resolve("Total")[0] == "country.georgia"
    assert resolve("Other regions**")[0] == "aggregate.other_regions"
    # Tbilisi as a municipality must not collide with Tbilisi the region.
    assert resolve("Tbilisi", level=MUNICIPALITY)[0] == "municipality.tbilisi"
    assert resolve("Tbilisi")[0] != resolve("Tbilisi", level=MUNICIPALITY)[0]
    # An unheard-of place is an error, never a new region.
    try:
        resolve("Atlantis")
    except UnknownPlace:
        pass
    else:                                            # pragma: no cover
        raise AssertionError("unknown place silently accepted")
    assert len(RANKABLE_REGIONS) == 11, RANKABLE_REGIONS
    print("geography: ok")


if __name__ == "__main__":
    demo()
