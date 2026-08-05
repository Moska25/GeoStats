"""Small bilingual layer, English and Georgian.

Deliberately small. Only strings that can be translated correctly are
translated: navigation, page titles, indicator labels, metric captions, table
headers and status words. Long explanatory prose stays in English, because a
half-right Georgian sentence about statistical methodology is worse than an
English one - and the UI says so rather than hiding it.

Any key missing from the Georgian dictionary falls back to English, so adding a
translation is a one-line change and never breaks a page.
"""

from __future__ import annotations

LANGUAGES = {"en": "English", "ka": "ქართული"}
DEFAULT_LANG = "en"

EN: dict[str, str] = {
    # shell
    "tagline": "Revision-aware Georgian labour statistics",
    "nav.overview": "Overview",
    "nav.explorer": "Explorer",
    "nav.regions": "Regions",
    "nav.salary": "Salary",
    "nav.reliability": "Reliability",
    "nav.ask": "Ask",
    "nav.lab": "Lab",
    "nav.methodology": "Methodology",
    "language": "Language",
    "footer.note": "Source: Geostat, National Statistics Office of Georgia",

    # page titles
    "page.overview": "Overview",
    "page.explorer": "Series explorer",
    "page.regions": "Regional earnings",
    "page.salary": "Salary and purchasing power",
    "page.reliability": "Dataset reliability",
    "page.ask": "Grounded analyst",
    "page.lab": "Fault-injection lab",
    "page.methodology": "Methodology and sources",

    # indicators
    "ind.avg_monthly_nominal_earnings": "Average monthly nominal earnings",
    "ind.median_monthly_earnings": "Median monthly earnings",
    "ind.cpi_2010_100": "Consumer price index (2010 = 100)",
    "ind.cpi_annual_avg_2010_100": "Consumer price index, annual average",
    "ind.cpi_same_month_prev_year": "Prices vs the same month a year earlier",
    "ind.basket_weight": "Consumer basket weight",

    # measures
    "m.nominal": "Nominal",
    "m.real": "Real",
    "m.median": "Median",
    "m.mean": "Mean",
    "m.year": "Year",
    "m.period": "Period",
    "m.value": "Value",
    "m.unit": "Unit",
    "m.inflation": "Inflation",
    "m.growth": "Growth",
    "m.gap": "Gap",
    "m.index": "Index",
    "m.region": "Region",
    "m.women": "Women",
    "m.men": "Men",
    "m.total": "Total",
    "m.purchasing_power": "Purchasing power",
    "m.gross": "Gross, before income tax",

    # data quality
    "q.preliminary": "Preliminary",
    "q.final": "Final",
    "q.source": "Source",
    "q.retrieved": "Retrieved",
    "q.vintage": "Vintage",
    "q.vintages": "Vintages",
    "q.dataset": "Dataset",
    "q.datasets": "Datasets",
    "q.rows": "Rows",
    "q.checks": "Checks",
    "q.passed": "Passed",
    "q.failed": "Failed",
    "q.skipped": "Not evaluated",
    "q.pass_rate": "Pass rate",
    "q.checksum": "Checksum",
    "q.observations": "Observations",
    "q.refresh": "Refresh from Geostat",

    # currencies
    "c.GEL": "Lari",
    "c.RUB": "Rouble",
    "c.KUP": "Coupon",
    "c.TKUP": "Thousand Coupon",
}

# Only entries that are confidently correct. Everything else falls back to EN.
KA: dict[str, str] = {
    "tagline": "ქართული შრომის სტატისტიკა ვერსიების აღრიცხვით",
    "nav.overview": "მიმოხილვა",
    "nav.explorer": "მაჩვენებლები",
    "nav.regions": "რეგიონები",
    "nav.salary": "ხელფასი",
    "nav.reliability": "სანდოობა",
    "nav.ask": "კითხვა",
    "nav.lab": "ლაბორატორია",
    "nav.methodology": "მეთოდოლოგია",
    "language": "ენა",
    "footer.note": "წყარო: საქართველოს სტატისტიკის ეროვნული სამსახური",

    "page.overview": "მიმოხილვა",
    "page.explorer": "მაჩვენებლები",
    "page.regions": "რეგიონები",
    "page.salary": "ხელფასი და მსყიდველობითი უნარი",
    "page.reliability": "მონაცემების სანდოობა",
    "page.ask": "ანალიტიკოსი",
    "page.lab": "ლაბორატორია",
    "page.methodology": "მეთოდოლოგია და წყაროები",

    "ind.avg_monthly_nominal_earnings": "საშუალო თვიური ნომინალური ხელფასი",
    "ind.median_monthly_earnings": "მედიანური თვიური ხელფასი",
    "ind.cpi_2010_100": "სამომხმარებლო ფასების ინდექსი (2010 = 100)",
    "ind.cpi_annual_avg_2010_100": "სამომხმარებლო ფასების ინდექსი, წლიური საშუალო",
    "ind.cpi_same_month_prev_year": "ფასები წინა წლის იმავე თვესთან შედარებით",
    "ind.basket_weight": "სამომხმარებლო კალათის წონა",

    "m.nominal": "ნომინალური",
    "m.real": "რეალური",
    "m.median": "მედიანა",
    "m.mean": "საშუალო",
    "m.year": "წელი",
    "m.period": "პერიოდი",
    "m.value": "მნიშვნელობა",
    "m.unit": "ერთეული",
    "m.inflation": "ინფლაცია",
    "m.growth": "ზრდა",
    "m.gap": "სხვაობა",
    "m.index": "ინდექსი",
    "m.region": "რეგიონი",
    "m.women": "ქალი",
    "m.men": "კაცი",
    "m.total": "სულ",
    "m.purchasing_power": "მსყიდველობითი უნარი",
    "m.gross": "ბრუტო, საშემოსავლო გადასახადამდე",

    "q.preliminary": "წინასწარი",
    "q.final": "საბოლოო",
    "q.source": "წყარო",
    "q.retrieved": "მიღების თარიღი",
    "q.vintage": "ვერსია",
    "q.vintages": "ვერსიები",
    "q.dataset": "მონაცემთა ნაკრები",
    "q.datasets": "მონაცემთა ნაკრებები",
    "q.rows": "ჩანაწერები",
    "q.checks": "შემოწმებები",
    "q.passed": "გავლილი",
    "q.failed": "ჩავარდნილი",
    "q.pass_rate": "წარმატების მაჩვენებელი",
    "q.observations": "დაკვირვებები",
    "q.refresh": "განახლება",

    "c.GEL": "ლარი",
    "c.RUB": "რუბლი",
    "c.KUP": "კუპონი",
    "c.TKUP": "ათასი კუპონი",
}

TABLES = {"en": EN, "ka": KA}

# Georgian coverage, computed rather than claimed.
KA_COVERAGE = len(KA) / len(EN)


def normalise(lang: str | None) -> str:
    return lang if lang in TABLES else DEFAULT_LANG


def translator(lang: str):
    """Return t(key, default=None) for the requested language."""
    lang = normalise(lang)
    table = TABLES[lang]

    def t(key: str, default: str | None = None) -> str:
        if key in table:
            return table[key]
        if key in EN:
            return EN[key]
        return default if default is not None else key

    return t


def untranslated_note(lang: str) -> str | None:
    if normalise(lang) != "ka":
        return None
    return (
        f"Georgian covers {KA_COVERAGE:.0%} of the interface: navigation, "
        "indicator names, table headers and status words. Explanatory prose "
        "about statistical methodology stays in English on purpose - a "
        "half-correct translation of a caveat is worse than no translation."
    )
