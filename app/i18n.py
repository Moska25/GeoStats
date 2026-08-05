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
    "nav.work": "Work",
    "nav.households": "Households",
    "nav.case_study": "Case study",
    "nav.explorer": "Explorer",
    "nav.regions": "Regions",
    "nav.salary": "Salary",
    "nav.reliability": "Data quality",
    "nav.ask": "Ask",
    "nav.lab": "Lab",
    "nav.methodology": "Methodology",
    "language": "Language",
    "footer.note": "Source: Geostat, National Statistics Office of Georgia",

    # page titles
    "page.overview": "Overview",
    "page.work": "Georgia at work",
    "page.households": "Georgian households",
    "page.case_study": "How this was built",
    "page.explorer": "Series explorer",
    "page.regions": "Regional atlas",
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
    "ind.unemployment_rate_percentage": "Unemployment rate",
    "ind.employment_rate_percentage": "Employment rate",
    "ind.labour_force_participation_rate_percentage": "Labour force participation rate",
    "ind.employed": "Employed",
    "ind.unemployed": "Unemployed",
    "ind.labour_force": "Labour force",
    "ind.population_1_january": "Population, 1 January",
    "ind.income_total": "Income, total",
    "ind.expenditure_total": "Expenditure, total",
    "ind.consumption_expenditure_total": "Consumption expenditure, total",
    "ind.active_enterprises": "Active enterprises",
    "ind.enterprise_births": "Enterprise births",
    "ind.enterprise_deaths": "Enterprise deaths",
    "ind.adjusted_gpg_hourly": "Adjusted gender pay gap, hourly",
    "ind.adjusted_gpg_monthly": "Adjusted gender pay gap, monthly",
    "ind.domestic_visits": "Domestic visits",
    "ind.inbound_visits": "Inbound visits",

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
    "m.income": "Income",
    "m.expenditure": "Expenditure",
    "m.population": "Population",
    "m.dataset": "Dataset",
    "m.indicator": "Indicator",
    "m.breakdown": "Breakdown",
    "m.quarter": "Quarter",
    "m.download": "Download CSV",

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
    "nav.work": "შრომა",
    "nav.households": "შინამეურნეობები",
    "nav.case_study": "პროექტის შესახებ",
    "nav.explorer": "მაჩვენებლები",
    "nav.regions": "რეგიონები",
    "nav.salary": "ხელფასი",
    "nav.reliability": "მონაცემთა ხარისხი",
    "nav.ask": "კითხვა",
    "nav.lab": "ლაბორატორია",
    "nav.methodology": "მეთოდოლოგია",
    "language": "ენა",
    "footer.note": "წყარო: საქართველოს სტატისტიკის ეროვნული სამსახური",

    "page.overview": "მიმოხილვა",
    "page.work": "საქართველო სამსახურში",
    "page.households": "ქართული შინამეურნეობები",
    "page.case_study": "როგორ არის აგებული",
    "page.explorer": "მაჩვენებლები",
    "page.regions": "რეგიონული ატლასი",
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
    "ind.unemployment_rate_percentage": "უმუშევრობის დონე",
    "ind.employment_rate_percentage": "დასაქმების დონე",
    "ind.labour_force_participation_rate_percentage": "სამუშაო ძალაში მონაწილეობის დონე",
    "ind.employed": "დასაქმებული",
    "ind.unemployed": "უმუშევარი",
    "ind.labour_force": "სამუშაო ძალა",
    "ind.population_1_january": "მოსახლეობა, 1 იანვარი",
    "ind.income_total": "შემოსავალი, სულ",
    "ind.expenditure_total": "ხარჯები, სულ",
    "ind.active_enterprises": "მოქმედი საწარმოები",
    "ind.enterprise_births": "საწარმოთა დაბადება",
    "ind.enterprise_deaths": "საწარმოთა გაუქმება",

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
    "m.income": "შემოსავალი",
    "m.expenditure": "ხარჯები",
    "m.population": "მოსახლეობა",
    "m.dataset": "მონაცემთა ბაზა",
    "m.indicator": "მაჩვენებელი",
    "m.breakdown": "ჭრილი",
    "m.quarter": "კვარტალი",
    "m.download": "CSV ჩამოტვირთვა",

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
