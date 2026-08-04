"""Dataset adapters for Geostat published spreadsheets.

Every adapter implements the same four-stage contract:

    discover()   -> SourceRef      where the file lives and what page documents it
    download()   -> bytes          raw HTTP fetch (browser User-Agent is mandatory)
    parse(bytes) -> list[dict]     workbook grid -> tidy records, markers preserved
    normalise()  -> list[Row]      long format with the composite key

`validate()` lives in contracts.py so the checks can run against any row set
(a fresh download, a committed vintage, or a deliberately corrupted copy).

The single most important thing in this file is `currency_for_year`. Geostat's
annual earnings workbook carries a footnote:

    "*Currency - before 1993 -Rouble; 1993 - Coupon; 1994 - Thousand Coupon;
     since 1995 - Lari."

The columns therefore are NOT one comparable series. 1993 reads 27950 and 1995
reads 13.5; that is a currency reform, not a 99.95% wage collapse. Every parsed
row carries the unit of its own year so the rest of the system cannot forget.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field, asdict
from typing import Callable

import openpyxl

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
)
WAGES_PAGE = "https://www.geostat.ge/en/modules/categories/39/wages"
INFLATION_PAGE = (
    "https://www.geostat.ge/en/modules/categories/26/inflation-consumer-price-index"
)

# Cells Geostat uses to mean "not published / not available".
MISSING_MARKERS = {"…", "...", "..", "-", "—", "–", "", "n/a", "N/A", ":"}

ROMAN_MONTHS = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
    "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
}


# --------------------------------------------------------------------------
# currency eras - the trap this whole project is built around
# --------------------------------------------------------------------------

CURRENCY_ERAS = [
    (None, 1992, "RUB", "Rouble"),
    (1993, 1993, "KUP", "Coupon"),
    (1994, 1994, "TKUP", "Thousand Coupon"),
    (1995, None, "GEL", "Lari"),
]

GEL_ERA_START = 1995


def currency_for_year(year: int) -> str:
    """Monetary unit in force in Georgia in `year`, per the Geostat footnote."""
    if year < 1993:
        return "RUB"
    if year == 1993:
        return "KUP"
    if year == 1994:
        return "TKUP"
    return "GEL"


def currency_name(code: str) -> str:
    for _lo, _hi, c, name in CURRENCY_ERAS:
        if c == code:
            return name
    return code


# --------------------------------------------------------------------------
# row model
# --------------------------------------------------------------------------

@dataclass
class Row:
    """One observation in long format.

    Composite key: (dataset_id, indicator_code, breakdown_code, period, unit,
    vintage_id). `vintage_id` is stamped when the row is written into a vintage.
    """

    dataset_id: str
    indicator_code: str
    breakdown_code: str
    breakdown_label: str
    period: str                 # "1995" or "1995-03"
    unit: str
    value: float | None
    raw: str                    # exactly what the cell held
    status: str                 # ok | missing | unparsed
    is_preliminary: bool = False
    vintage_id: str = ""

    def key(self) -> tuple:
        return (
            self.dataset_id, self.indicator_code, self.breakdown_code,
            self.period, self.unit, self.vintage_id,
        )

    def to_dict(self) -> dict:
        return asdict(self)


def parse_number(raw_value) -> tuple[float | None, str, str]:
    """Return (value, status, raw_text).

    status is 'ok', 'missing' (a published gap marker) or 'unparsed' (something
    we did not expect). Nothing is ever silently coerced to 0.
    """
    if raw_value is None:
        return None, "missing", ""
    if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
        return float(raw_value), "ok", repr(raw_value)
    text = str(raw_value).strip()
    if text in MISSING_MARKERS:
        return None, "missing", text
    cleaned = text.replace("\xa0", "").replace(" ", "")
    # Geostat publishes decimal points. A comma here means someone handed us a
    # European-formatted export; we refuse to guess whether it is a decimal
    # separator or a thousands separator.
    if "," in cleaned:
        return None, "unparsed", text
    try:
        return float(cleaned), "ok", text
    except ValueError:
        return None, "unparsed", text


def parse_period_header(cell) -> tuple[str | None, bool]:
    """Turn a year header cell into (period, is_preliminary).

    `2025**` -> ("2025", True) because ** is the preliminary-data footnote.
    `2006*`  -> ("2006", False) because a single * is a methodology footnote.
    """
    if cell is None:
        return None, False
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        return str(int(cell)), False
    text = str(cell).strip()
    prelim = text.endswith("**")
    digits = re.match(r"^(\d{4})", text)
    if not digits:
        return None, False
    return digits.group(1), prelim


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower())
    return s.strip("_") or "unknown"


# --------------------------------------------------------------------------
# parsers - five shapes cover all eight published workbooks
# --------------------------------------------------------------------------

def _sheet(data: bytes, name: str):
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=False)
    if name not in wb.sheetnames:
        raise KeyError(f"sheet {name!r} not in workbook (have {wb.sheetnames})")
    return wb[name]


def _last_col(ws, row: int) -> int:
    last = 0
    for c in range(1, ws.max_column + 1):
        if ws.cell(row, c).value is not None:
            last = c
    return last


def _year_headers(ws, header_row: int) -> list[tuple[int, str, bool]]:
    out = []
    for c in range(2, _last_col(ws, header_row) + 1):
        period, prelim = parse_period_header(ws.cell(header_row, c).value)
        if period:
            out.append((c, period, prelim))
    return out


def parse_year_grid(
    data: bytes,
    *,
    sheet: str,
    header_row: int,
    first_row: int,
    unit_mode: str,
    indicator: str,
    dataset_id: str,
    breakdown_prefix: str = "",
    detect_sections: bool = False,
) -> list[Row]:
    """Label column A, year headers across the top.

    `detect_sections=True` handles the annual earnings workbook, where rows like
    `Sex` / `Type of ownership` / `Sector` are group headings with no data and
    the rows beneath them belong to that group.
    """
    ws = _sheet(data, sheet)
    headers = _year_headers(ws, header_row)
    rows: list[Row] = []
    section = ""
    for r in range(first_row, ws.max_row + 1):
        label = ws.cell(r, 1).value
        if label is None:
            continue
        label = str(label).strip()
        if not label or label.startswith("*") or label.lower().startswith("source"):
            continue
        cells = [(p, prelim, ws.cell(r, c).value) for c, p, prelim in headers]
        has_data = any(v is not None and str(v).strip() != "" for _, _, v in cells)
        if detect_sections and not has_data:
            section = slug(label)
            continue
        if not has_data:
            continue
        code_parts = [x for x in (breakdown_prefix, section, slug(label)) if x]
        code = ".".join(code_parts)
        for period, prelim, cell in cells:
            value, status, raw = parse_number(cell)
            unit = currency_for_year(int(period)) if unit_mode == "currency_era" else unit_mode
            rows.append(Row(
                dataset_id=dataset_id, indicator_code=indicator,
                breakdown_code=code, breakdown_label=label,
                period=period, unit=unit, value=value, raw=raw,
                status=status, is_preliminary=prelim,
            ))
    return rows


def parse_banded_grid(
    data: bytes, *, sheet: str, header_row: int, first_row: int,
    unit_mode: str, indicator: str, dataset_id: str,
) -> list[Row]:
    """Same as a year grid, but split into bands (Women / Men) whose heading
    sits in column B with column A empty."""
    ws = _sheet(data, sheet)
    headers = _year_headers(ws, header_row)
    rows: list[Row] = []
    band = ""
    band_label = ""
    for r in range(first_row, ws.max_row + 1):
        a = ws.cell(r, 1).value
        b = ws.cell(r, 2).value
        if a is None and isinstance(b, str) and b.strip():
            band, band_label = slug(b), b.strip()
            continue
        if a is None:
            continue
        label = str(a).strip()
        if not label or label.startswith("*"):
            continue
        for c, period, prelim in headers:
            value, status, raw = parse_number(ws.cell(r, c).value)
            unit = currency_for_year(int(period)) if unit_mode == "currency_era" else unit_mode
            rows.append(Row(
                dataset_id=dataset_id, indicator_code=indicator,
                breakdown_code=f"{band}.{slug(label)}",
                breakdown_label=f"{band_label} - {label}",
                period=period, unit=unit, value=value, raw=raw,
                status=status, is_preliminary=prelim,
            ))
    return rows


def parse_cpi_monthly(data: bytes, *, dataset_id: str) -> list[Row]:
    """CPI 2010=100. One sheet per city, years down, roman-numeral months across.

    Also derives an annual average per city, but only for years where all twelve
    months are published - a partial year would quietly understate the average.
    """
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    rows: list[Row] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        city = sheet_name.strip()
        code = slug(city)
        months = []
        for c in range(2, _last_col(ws, 3) + 1):
            key = str(ws.cell(3, c).value or "").strip().upper()
            if key in ROMAN_MONTHS:
                months.append((c, ROMAN_MONTHS[key]))
        for r in range(4, ws.max_row + 1):
            year_cell = ws.cell(r, 1).value
            if not isinstance(year_cell, (int, float)):
                continue
            year = int(year_cell)
            monthly: list[float] = []
            for c, m in months:
                value, status, raw = parse_number(ws.cell(r, c).value)
                if status == "missing" and raw == "":
                    continue  # month not yet published
                if value is not None:
                    monthly.append(value)
                rows.append(Row(
                    dataset_id=dataset_id, indicator_code="cpi_2010_100",
                    breakdown_code=code, breakdown_label=city,
                    period=f"{year}-{m:02d}", unit="index_2010_100",
                    value=value, raw=raw, status=status,
                ))
            if len(monthly) == 12:
                rows.append(Row(
                    dataset_id=dataset_id, indicator_code="cpi_annual_avg_2010_100",
                    breakdown_code=code, breakdown_label=city,
                    period=str(year), unit="index_2010_100",
                    value=round(sum(monthly) / 12, 6),
                    raw="derived: mean of 12 published months",
                    status="ok",
                ))
    return rows


def parse_cpi_yoy(data: bytes, *, dataset_id: str) -> list[Row]:
    """CPI vs the same month of the previous year.

    The workbook carries the full COICOP tree for seven cities across ~270
    columns. We keep the headline 'Total' line per city: that is the number the
    press releases quote, and it is the only line the rest of GeoStats consumes.
    """
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    rows: list[Row] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        city = sheet_name.strip()
        code = slug(city)
        # row 3 holds a year every 12 columns, row 4 the roman months
        year_at: dict[int, int] = {}
        current = None
        for c in range(1, ws.max_column + 1):
            v = ws.cell(3, c).value
            if isinstance(v, (int, float)) and 1990 < float(v) < 2100:
                current = int(v)
            month_key = str(ws.cell(4, c).value or "").strip().upper()
            if current and month_key in ROMAN_MONTHS:
                year_at[c] = current
        total_row = None
        for r in range(4, min(ws.max_row, 12) + 1):
            if str(ws.cell(r, 3).value or "").strip().lower() == "total":
                total_row = r
                break
        if total_row is None:
            continue
        for c, year in year_at.items():
            month = ROMAN_MONTHS[str(ws.cell(4, c).value).strip().upper()]
            value, status, raw = parse_number(ws.cell(total_row, c).value)
            if status == "missing" and raw == "":
                continue
            rows.append(Row(
                dataset_id=dataset_id, indicator_code="cpi_same_month_prev_year",
                breakdown_code=code, breakdown_label=city,
                period=f"{year}-{month:02d}", unit="index_prev_year_100",
                value=value, raw=raw, status=status,
            ))
    return rows


def parse_basket_weights(data: bytes, *, dataset_id: str) -> list[Row]:
    """Consumer basket weights. Header spans two rows: labels on row 3, years on
    row 4 starting at column E. Values are shares (Total = 1.0), not percent,
    despite the title saying '%'."""
    ws = _sheet(data, "Weights")
    headers = []
    for c in range(5, _last_col(ws, 4) + 1):
        period, prelim = parse_period_header(ws.cell(4, c).value)
        if period:
            headers.append((c, period, prelim))
    rows: list[Row] = []
    for r in range(5, ws.max_row + 1):
        level = ws.cell(r, 2).value
        coicop = ws.cell(r, 3).value
        label = ws.cell(r, 4).value
        if coicop is None and label is None:
            continue
        name = str(label).strip() if label else str(coicop).strip()
        # The COICOP code alone is NOT unique in this workbook: "11" is Food at
        # level 3 and Restaurants and hotels at level 2. The key-uniqueness
        # contract caught that; the level has to be part of the key.
        code = slug(str(coicop) if coicop is not None else name)
        if level is not None:
            code = f"l{int(level)}.{code}"
        for c, period, prelim in headers:
            value, status, raw = parse_number(ws.cell(r, c).value)
            rows.append(Row(
                dataset_id=dataset_id, indicator_code="basket_weight",
                breakdown_code=code, breakdown_label=name,
                period=period, unit="share_of_1", value=value, raw=raw,
                status=status, is_preliminary=prelim,
            ))
    return rows


# --------------------------------------------------------------------------
# adapter registry
# --------------------------------------------------------------------------

@dataclass
class Adapter:
    dataset_id: str
    title: str
    url: str
    source_page: str
    parser: Callable[[bytes], list[Row]]
    unit_family: str
    note: str
    expected_sheets: list[str] = field(default_factory=list)
    period_grain: str = "annual"

    # -- the four ingestion stages ------------------------------------------
    def discover(self) -> dict:
        """Where this dataset comes from. Geostat has no machine-readable
        release feed on these pages, so the file URL is pinned and the vintage
        log is what proves whether the bytes behind it changed."""
        return {
            "dataset_id": self.dataset_id,
            "url": self.url,
            "source_page": self.source_page,
            "expected_sheets": self.expected_sheets,
        }

    def download(self, timeout: float = 45.0) -> tuple[bytes, int]:
        """Fetch the workbook. The browser User-Agent is not optional: without
        it Geostat answers 200 with a zero-byte body."""
        import httpx

        headers = {
            "User-Agent": USER_AGENT,
            "Referer": self.source_page,
            "Accept": "*/*",
        }
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(self.url, headers=headers)
        return resp.content, resp.status_code

    def parse(self, data: bytes) -> list[Row]:
        return self.parser(data)

    def normalise(self, data: bytes, vintage_id: str) -> list[Row]:
        rows = self.parse(data)
        for row in rows:
            row.vintage_id = vintage_id
        return rows


def _earnings_annual(data: bytes) -> list[Row]:
    return parse_year_grid(
        data, sheet="1", header_row=3, first_row=4,
        unit_mode="currency_era", indicator="avg_monthly_nominal_earnings",
        dataset_id="earnings_annual", detect_sections=True,
    )


def _median_earnings(data: bytes) -> list[Row]:
    return parse_year_grid(
        data, sheet="1", header_row=2, first_row=3,
        unit_mode="GEL", indicator="median_monthly_earnings",
        dataset_id="median_earnings",
    )


def _earnings_by_region(data: bytes) -> list[Row]:
    return parse_year_grid(
        data, sheet="1", header_row=3, first_row=4,
        unit_mode="currency_era", indicator="avg_monthly_nominal_earnings",
        dataset_id="earnings_by_region",
    )


def _earnings_by_activity(data: bytes) -> list[Row]:
    rows: list[Row] = []
    for sheet, prefix in (("NACE1", "nace1"), ("NACE2", "nace2")):
        rows += parse_year_grid(
            data, sheet=sheet, header_row=3, first_row=4,
            unit_mode="currency_era", indicator="avg_monthly_nominal_earnings",
            dataset_id="earnings_by_activity", breakdown_prefix=prefix,
        )
    return rows


def _earnings_by_sex(data: bytes) -> list[Row]:
    rows: list[Row] = []
    for sheet in ("NACE1", "NACE2"):
        part = parse_banded_grid(
            data, sheet=sheet, header_row=3, first_row=4,
            unit_mode="currency_era", indicator="avg_monthly_nominal_earnings",
            dataset_id="earnings_by_sex",
        )
        prefix = sheet.lower()
        for row in part:
            row.breakdown_code = f"{prefix}.{row.breakdown_code}"
        rows += part
    return rows


ADAPTERS: dict[str, Adapter] = {
    a.dataset_id: a for a in [
        Adapter(
            dataset_id="earnings_annual",
            title="Average monthly nominal earnings of employees, annual",
            url="https://geostat.ge/media/77569/01_Earnings_annual.xlsx",
            source_page=WAGES_PAGE,
            parser=_earnings_annual,
            unit_family="currency_era",
            expected_sheets=["1"],
            note=(
                "Headline series, 1970-2025. Columns span four currencies "
                "(Rouble, Coupon, Thousand Coupon, Lari) and are not a "
                "comparable series before 1995."
            ),
        ),
        Adapter(
            dataset_id="median_earnings",
            title="Median earnings of employees by economic activity",
            url="https://geostat.ge/media/73905/Median-Monthly-Earnings.xlsx",
            source_page=WAGES_PAGE,
            parser=_median_earnings,
            unit_family="GEL",
            expected_sheets=["1"],
            note=(
                "Administrative source (Revenue Service), 2018 onward. The gap "
                "between this and the mean is the skew of the wage distribution."
            ),
        ),
        Adapter(
            dataset_id="earnings_by_region",
            title="Average monthly nominal earnings by region",
            url="https://geostat.ge/media/73904/13_Earnings-by-regions_annual.xlsx",
            source_page=WAGES_PAGE,
            parser=_earnings_by_region,
            unit_family="currency_era",
            expected_sheets=["1"],
            note=(
                "Enterprises are counted at the location of the head office, "
                "which inflates Tbilisi relative to where work is done."
            ),
        ),
        Adapter(
            dataset_id="earnings_by_sex",
            title="Average monthly nominal earnings by economic activity and sex",
            url="https://geostat.ge/media/73901/03_Earnings-by-sex_annual.xlsx",
            source_page=WAGES_PAGE,
            parser=_earnings_by_sex,
            unit_family="currency_era",
            expected_sheets=["NACE1", "NACE2"],
            note=(
                "Two activity classifications. NACE rev.1 covers 1999-2019, "
                "NACE rev.2 covers 2014-2024; they are not splice-compatible."
            ),
        ),
        Adapter(
            dataset_id="earnings_by_activity",
            title="Average monthly nominal earnings by economic activity",
            url="https://geostat.ge/media/73900/02_Earnings-by-activity_annual.xlsx",
            source_page=WAGES_PAGE,
            parser=_earnings_by_activity,
            unit_family="currency_era",
            expected_sheets=["NACE1", "NACE2"],
            note=(
                "The 2006 column carries a methodology footnote: the drop in "
                "Financial intermediation is a coverage change, not a wage fall."
            ),
        ),
        Adapter(
            dataset_id="cpi_2010_base",
            title="Consumer price index, 2010 average = 100",
            url="https://geostat.ge/media/81846/consumer-price-index-2010%3D100-%2810%29.xlsx",
            source_page=INFLATION_PAGE,
            parser=lambda d: parse_cpi_monthly(d, dataset_id="cpi_2010_base"),
            unit_family="index_2010_100",
            expected_sheets=["Georgia "],
            period_grain="monthly",
            note=(
                "Monthly index for Georgia and five cities. GeoStats derives an "
                "annual average only from years with all twelve months present."
            ),
        ),
        Adapter(
            dataset_id="cpi_yoy",
            title="Consumer price index vs the same month of the previous year",
            url="https://geostat.ge/media/81847/consumer-price-index-to-the-same-month-of-previous-year.xlsx",
            source_page=INFLATION_PAGE,
            parser=lambda d: parse_cpi_yoy(d, dataset_id="cpi_yoy"),
            unit_family="index_prev_year_100",
            expected_sheets=["Georgia"],
            period_grain="monthly",
            note=(
                "Headline annual inflation rate as published monthly. Only the "
                "Total line is ingested; the COICOP tree is out of scope."
            ),
        ),
        Adapter(
            dataset_id="basket_weights",
            title="Consumer basket weights",
            url="https://geostat.ge/media/76662/Consumer-basket-weights.xlsx",
            source_page=INFLATION_PAGE,
            parser=lambda d: parse_basket_weights(d, dataset_id="basket_weights"),
            unit_family="share_of_1",
            expected_sheets=["Weights"],
            note=(
                "The weights behind the CPI. Published as shares summing to 1 "
                "even though the sheet title says percent."
            ),
        ),
    ]
}
