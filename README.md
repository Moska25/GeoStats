# GeoStats

A revision-aware data platform over real published statistics from Geostat, the
National Statistics Office of Georgia: pay, prices, employment, households,
population, business and tourism, with every retrieval kept as an immutable
vintage and every methodology caveat stated next to the number it applies to.

![The series explorer with the currency-era band: the shaded span is not
Lari, and the strip under the axis names Rouble, Coupon, Thousand Coupon and
Lari](docs/screenshots/hero.png)

## What it does

- **Ingests twenty real Geostat workbooks** across seven publication
  categories — earnings (annual, quarterly, median, and by region, sex,
  activity, ownership and business sector), the labour force survey (national
  and regional), household income and expenditure, population by region and
  municipality, business demography, tourism, the adjusted gender pay gap, two
  CPI series and the consumer basket weights — through an adapter per dataset,
  normalised into one long format keyed by `dataset_id, indicator_code,
  breakdown_code, period, unit, vintage_id` at annual, quarterly and monthly
  grain.
- **Keeps every retrieval as an immutable vintage.** `data/vintages/<dataset>/<UTC
  timestamp>/` holds the raw bytes, a `meta.json` with source URL, sha256, byte
  size and HTTP status, and the normalised rows. Nothing is ever overwritten;
  the files are chmod 0444 and the writer refuses an existing path.
- **Validates every vintage against eleven data contracts** before the numbers
  reach a chart — including a currency-era check, an `IDENTITY` check that
  verifies the relationships the source states between its own rows, and a
  `SOURCE_AGREEMENT` check that compares the spreadsheet against Geostat's
  PX-Web API — and reports the offending rows when one fails.
- **Reads one series twice, by two paths that share no code.** Geostat
  publishes the regional labour force survey as a spreadsheet and as a PX-Web
  API table. The two agree on all 2,029 shared cells to within the API's own
  rounding. A parser that took the wrong column would pass every other check
  and fail this one immediately.
- **Says which datasets are behind.** Each dataset's cadence is inferred from
  its own published periods, and any whose next period has finished without
  appearing is flagged. Nine currently are, including every detailed earnings
  breakdown: Geostat publishes those a year behind the headline figure.
- **Joins six separately-published regional files** through a canonical
  geography registry. Geostat spells Adjara four ways across those files;
  joining on the printed label would produce four regions where there is one,
  so an unrecognised place name is a hard error rather than a new region.
- **Maps eight measures across the eleven regions** as an equal-area tile
  cartogram, ranked table and wage-against-unemployment scatter, stating the
  head-office effect that inflates Tbilisi rather than quietly correcting for
  it. No composite "opportunity score": the components are shown and the
  weighing is left to the reader.
- **Answers questions from a closed set of approved metric functions** and
  refuses the ones the published aggregates cannot support, with the reason.
- **Proves the contracts work** by injecting faults into copies of committed
  vintages and showing which check caught each one, with the original's
  checksum printed before and after every run.
- **Exports any selection as CSV** carrying dataset, vintage, unit, parse
  status and preliminary flag, so a figure cannot lose its caveats on the way
  into a spreadsheet.

## Why it exists / the question it answers

Official statistics are published, revised, corrected and reclassified. A
platform that overwrites yesterday's file is lying to its users: it can no
longer say what it knew, or when, or whether a number moved.

The Georgian earnings series makes the second half of the problem concrete. Its
annual workbook puts 1992, 1993, 1994 and 1995 in adjacent columns, and a
footnote at the bottom of the sheet explains that those columns are denominated
in Roubles, Coupons, Thousand Coupons and Lari respectively. Read the row as one
series and 1995 looks like a 99.8% collapse in wages. It was a redenomination.
GeoStats is built around the position that a data platform's job is to make that
impossible to get wrong, and to say out loud what its numbers do and do not
mean.

That shape of defect — every value plausible, the relationship between them
meaningless — turns out to be the general case, and the labour force survey
supplies a second instance the same machinery catches. Geostat adopted the
ICLS-19 employment standard in 2020, which puts subsistence agricultural
producers outside employment, and recalculated 2010 onward while leaving
1998–2009 on the old basis. Employment falls from 1,611 to 1,168 thousand and
unemployment rises from 18.3% to 27.2% between 2009 and 2010, because the
question changed rather than the labour market. No unit moved, no year is
missing and nothing is out of range, so no value check can see it. It is
declared in `SERIES_BREAKS`, and every comparison that crosses it says so.

## Run it

Requires **Python 3.12** (the script uses `/opt/homebrew/bin/python3.12`).

```bash
./run.sh
# then open http://127.0.0.1:8013
```

`run.sh` creates the venv if missing, rebuilds the sqlite read index from the
committed vintages, and serves on port 8013. **No network access is required**:
every dataset ships with at least one real vintage committed in the repository,
so the whole application works offline with genuine official data. The network
is used only by the optional `Refresh from Geostat` button.

## What to look at first

A five-minute tour:

1. <http://127.0.0.1:8013/> — the overview. Five computed findings, then *The
   trap: four currencies in one row of columns*. Compare the two charts: the
   left one is what you get by plotting the sheet, the right one is the same
   data restricted to the Lari era.
2. <http://127.0.0.1:8013/work> — pay against unemployment on *separate* axes,
   and the 2009/2010 definition break. Every generated sentence that crosses
   that boundary says it crosses it, and then gives the version that doesn't.
3. <http://127.0.0.1:8013/atlas?metric=earnings&region=kakheti> — six workbooks
   joined on one region registry, drawn as a cartogram rather than a map, with
   a per-region fingerprint against the country and deliberately no combined
   score.
4. <http://127.0.0.1:8013/households> — reported income against reported
   expenditure, with the gap between them labelled as the survey artefact it is
   rather than presented as a savings rate. Note the sign reversing in 2024.
5. <http://127.0.0.1:8013/reliability/earnings_by_region> — three genuine
   releases of the same series (October 2020, January 2022, and the current
   file), each with its own sha256, and a diff between them. The diff reports
   that Geostat added years without revising any earlier figure, which is a
   finding, not an absence of one.
6. <http://127.0.0.1:8013/lab?fault_id=mislabel_era> — relabel the pre-1995
   Rouble and Coupon rows as Lari on a copy of a committed vintage, and watch
   `CURRENCY_ERA` catch it. The panel shows the committed vintage's checksum
   before and after the run to prove the original was untouched. Try the other
   nine faults from the same page.
7. <http://127.0.0.1:8013/ask> — the grounded analyst. Skip past the answers to
   the refusals: *What is the 90th percentile salary in Georgia?* and *What is
   the average take-home pay after tax in 2024?* Those are the interesting ones.
8. <http://127.0.0.1:8013/case-study> — the engineering account, with every
   number on it read live from the index rather than typed in.

## Screenshots

The interface is deliberately a light one: a printed statistical yearbook rather
than a dashboard. Serif display type, thin rules, numbered exhibits with a source
line under each one, an editorial measure for prose, and footnotes set as
footnotes. The masthead carries a real dateline, computed from the vintages on
disk rather than typed in.

Every image below is regenerated by `tools/capture_screenshots.py`, which
refuses to write a file unless the server answered, the page contained a marker
string only that page has, and the resulting PNG is bigger than a browser error
card. That guard exists because `regions.png` was for a long time a committed
screenshot of Chrome's ERR_CONNECTION_REFUSED page, and nothing caught it.

![The overview: five computed findings, then the same published column set
plotted naively and honestly side by side](docs/screenshots/overview.png)

*`/` — the five figures, then Figure 1: why the naive line is meaningless.*

![Real earnings, unemployment and employment as three stacked panels sharing one
x axis, with the 2009/2010 definition break called out
above](docs/screenshots/work.png)

*`/work` — three panels, not one dual axis. Putting two scales on one pair of
axes lets whoever chose the scales decide whether the lines appear to move
together.*

![Household reported income against reported expenditure, with the gap labelled
as a survey artefact rather than a savings
rate](docs/screenshots/households.png)

*`/households` — the sign of the income-expenditure gap reverses in 2024, which
the page reports and explicitly declines to explain.*

![Georgia's regions as an equal-area tile cartogram shaded by average monthly
earnings, Tbilisi darkest](docs/screenshots/atlas.png)

*`/atlas` — a cartogram, not a map: one equal square per region, shaded by rank
because Tbilisi is far enough above the rest that a linear ramp would draw the
outlier instead of the country.*

![One region indexed against Georgia across every measure, each row carrying its
own published period](docs/screenshots/atlas-region.png)

*`/atlas?region=…` — the regional fingerprint. Six workbooks on different
publication schedules, so each row prints its own period rather than being
quietly aligned. No combined score.*

![Regional earnings ranked for 2024, each region indexed against the national
figure, with the head-office caveat stated above the
chart](docs/screenshots/regions.png)

*`/regions` — ranked, indexed, and honest about what the ranking measures.*

![Dataset reliability: one card per dataset with retrieval time, checksum,
byte size and contract pass rate](docs/screenshots/reliability.png)

*`/reliability` — twenty datasets, twenty-two vintages, 25,172 observations, a
212/220 contract pass rate that is left failing on purpose, and nine datasets
flagged as behind their own publication cadence.*

![The contract audit sheet: a pass/fail gutter down the left, the failing JOIN
check naming 1995 to 1999 as undeflatable, and each check's reason set as a
footnote](docs/screenshots/contract-sheet.png)

*`/reliability/earnings_annual` — contract results as a printed audit sheet. The
`JOIN` failure is real: the CPI series starts in 2000, so five Lari-era wage
years genuinely cannot be deflated.*

![The vintage log as an editorial corrections notice: current and superseded
releases, each with its retrieval route, checksum and revision
summary](docs/screenshots/vintage-diff.png)

*`/reliability/earnings_by_region` — three genuine releases of one series. Two
were recovered from the Internet Archive and are labelled as such; the third was
fetched directly. The diff reports years added with nothing revised.*

![The reliability detail page showing the PX-Web cross-check: table title,
capture time, checksum and row count for the second
source](docs/screenshots/second-source.png)

*`/reliability/labour_force_by_region` — the same survey read twice, by two
code paths that share nothing. `SOURCE_AGREEMENT` compares 2,029 shared cells.*

![The reliability index flagging nine datasets whose next period has finished
without appearing](docs/screenshots/release-staleness.png)

*`/reliability` — cadence is inferred from each dataset's own periods, so
"behind" is derived rather than asserted. There is no scheduled date attached
because Geostat publishes no machine-readable calendar, and the page says so.*

![The analyst refusing to answer a percentile question, with the reason and what
data would be needed](docs/screenshots/ask-refusal.png)

*`/ask` — a percentile cannot be reconstructed from a mean and a median, so the
analyst refuses and says what it would need instead.*

![The explorer on the labour force series with a CSV download
button](docs/screenshots/explorer-csv.png)

*`/explorer` — every series in every vintage, addressable by URL, exportable as
CSV with its unit, vintage and preliminary flag attached.*

![The salary position scale: one axis from zero carrying the published median,
the published mean and the entered amount](docs/screenshots/salary.png)

*`/salary` — the entered amount against two published points. The caption says
plainly that two points are not a distribution, so the position is not a
percentile.*

![The fault lab after injecting a currency-era mislabel: the contract results
table with the tripped check, and a defect report ready to
paste](docs/screenshots/lab.png)

*`/lab` — inject a defect into a copy, watch the contract catch it, and read the
checksum proving the committed vintage never moved.*

![The case study page with live dataset counts, the contract table and a fault
injection run at render time](docs/screenshots/case-study.png)

*`/case-study` — the engineering account. Every figure on it is read from the
index at render time, so it cannot go stale.*

![The methodology page as a numbered document with a contents
list](docs/screenshots/methodology.png)

*`/methodology` — six numbered sections, a contents list, and a Limitations
section that is real.*

![The regional atlas at a 375 pixel viewport, cartogram and controls stacked
with no horizontal page scroll](docs/screenshots/mobile-375.png)

*375px. Every page holds `scrollWidth === clientWidth` at this width in both
English and Georgian; wide tables scroll inside their own container, which is
asserted by a test rather than eyeballed.*

## How it works

```
   Geostat .xlsx  ──(browser UA + Referer, else 0 bytes)──▶  adapters.py
   PX-Web JSON    ──(second source, frozen to data/pxweb/)──▶  pxweb.py
                                                               │ parse
                                                  geography.py │ resolve places
                                                               ▼
                                              raw bytes + meta.json + rows.json
                                              data/vintages/<id>/<UTC stamp>/
                                                    (chmod 0444, never rewritten)
                                                               │
                          ┌────────────────────────────────────┼──────────────┐
                          ▼                                    ▼              ▼
                    contracts.py                            seed.py        faults.py
             11 declarative checks                     sqlite read index   copy → mutate
             pass/fail + offenders                     (derived, gitignored) → re-check
                          │                                    │              │
                          └──────────────┬─────────────────────┘──────────────┘
                                         ▼
                             metrics.py (pure) · analyst.py (router)
                                         ▼
                     main.py → Jinja2 → 12 pages + charts.py (inline SVG)
                                         ▼
                              refresh_all.py (batch, opt-in)
```

The vintages on disk are the source of truth. The sqlite database is a derived
read index that `python -m app.seed` rebuilds from scratch on every start; it is
gitignored, and if it ever disagrees with a vintage the vintage wins.

Business logic lives in importable modules — `adapters`, `geography`, `pxweb`,
`ingest`, `contracts`, `metrics`, `analyst`, `faults`, `charts`, `calendar`,
`refresh_all` — and the
route handlers only assemble template context. That is what makes the test suite
meaningful: it imports the same functions the pages call.

## Engineering notes

**The currency-era trap is the whole design.** Rather than filtering pre-1995
data out at read time, the unit is part of the composite key: `currency_for_year`
stamps every parsed value with the currency in force that year, so a mixed-era
series is structurally detectable rather than something a developer has to
remember. The `CURRENCY_ERA` contract fails any series carrying more than one era
under a single unit label, and the explorer refuses to default into the mess.

**Two sources beat one check.** `SOURCE_AGREEMENT` compares the spreadsheet
reading against Geostat's PX-Web API. Nothing is shared between the two paths —
one parses a workbook grid with openpyxl, the other reads JSON — so a
symmetrical bug cannot hide in both. The tolerance is 0.05 because PX-Web
rounds to one decimal place and the spreadsheets carry full precision; it is
half the last published digit, derived rather than tuned, and the worst
observed disagreement across 2,029 cells is exactly that. The API reading is
frozen to `data/pxweb/` with its own checksum, so the comparison runs offline
and "the two sources agreed" is a claim about specific bytes.

**There is no release calendar to parse, and the code says so.** Geostat's
calendar is rendered client-side and exposes no machine-readable feed; the
served HTML contains no dates and the obvious JSON endpoints 404.
`calendar.scheduled_date()` therefore returns `(None, reason)` for every
dataset rather than inventing one, and the staleness signal is derived instead:
a dataset's cadence comes from its own published periods, and it is late when
the period it should cover has itself finished.

**A definition change is the same defect with no unit to catch it.** The labour
force series breaks between 2009 and 2010 on the ICLS-19 standard. Nothing about
it is detectable by a value check, so it is declared in `SERIES_BREAKS` and
`spans_a_break()` is consulted wherever a first-to-last comparison is generated.
The `/work` page prints the caveat, and then prints the same comparison confined
to one side of the boundary — which is the version worth quoting.

**Six files, four spellings of Adjara.** `geography.py` resolves every published
place label to a level-prefixed code (`region.adjara`, `municipality.batumi`,
`country.georgia`). The level prefix is not decoration: Tbilisi is published as
both a region and a municipality, and a total that summed both would double-count
the capital. An unrecognised label raises rather than minting a new code, so a
respelling fails the next ingest loudly instead of silently splitting a series.

**A contract you have never seen fail is not a check.** Every contract has a
matching fault in `app/faults.py`, and the test suite asserts, for all ten, that
the contract passes on the clean vintage and fails after injection. `SCHEMA`
gates the rest: a renamed column used to raise `KeyError` in eight downstream
checks, which reports one defect nine times and crashes the page. It now
short-circuits and marks the rest "not evaluated".

**The `IDENTITY` contract catches what no single-value check can.** The sources
state relationships between their own rows — `1. Income, total (2+3)`, a
published unemployment rate next to the counts it comes from, a birth rate next
to births and active enterprises. Reading values into the wrong row leaves every
individual number inside its plausible range and only the arithmetic between
them wrong. `break_identity` is the fault that proves it bites.

**The failing checks in the UI are deliberate, and the test suite enforces
that.** `KNOWN_FAILURES` names all eight red checks with the reason each is left
red — five undeflatable wage years, a regional split Geostat stopped publishing
for a decade, a pandemic-suspended tourism survey, lumpy survey categories. One
test asserts nothing fails without an entry; another asserts every entry still
corresponds to a check that actually fails. The table cannot rot in either
direction.

**A 10x jump only means a unit error if the values are big enough for 10x to be
surprising.** Property income of 0.46 GEL a month, one registered enterprise in
Abkhazia, a 0.25% adjusted pay gap: all move by an order of magnitude for
ordinary reasons. `TEMPORAL` abstains below a per-unit materiality floor, and
never fires on a step to or from exactly zero, because no unit conversion
produces zero. Monetary units carry no floor: the currency trap is exactly a
large step in a large series and must always bite.

**The contracts found real defects during development.** `KEY_UNIQUE` failed on
the consumer basket file: COICOP code `11` is *Food* at level 3 and *Restaurants
and hotels* at level 2, so the code alone is not a unique key. `IDENTITY` found
that the national labour force file put its measures on the breakdown axis while
the regional one put them on the indicator axis, which made the identity
unverifiable in one of the two. Both fixes are pinned by tests.

**The vintage history is real, not synthesised.** Two earlier releases of the
regional earnings file were recovered from the Internet Archive so the log starts
before this project did. Their `meta.json` records the retrieval route honestly.
That is also why `earnings_by_region` keeps its pre-registry breakdown codes and
is mapped at read time: re-ingesting it would mint new timestamps and throw away
the provenance that makes those two releases worth having.

**No LLM in the analyst.** It is a regex intent router over twelve approved
metric functions plus two direct reads. That is a deliberate downgrade in
flexibility for a large upgrade in checkability: every answer names the function
and formula that produced it, and anything outside the closed set gets no answer
instead of a plausible one. A figure Geostat publishes directly is listed as a
*read* rather than a metric, because claiming a formula for it would invent a
derivation that never happens.

**Trade-offs taken.** The year-on-year CPI workbook has 274 columns of COICOP
tree per city; only the headline `Total` line is ingested. Only the `By regions`
sheet of the business demography workbook is parsed, not the legal-form or
per-year activity sheets. Municipality-level population is ingested but no page
plots it yet.

## Tests

```bash
./.venv/bin/python -m pytest -q
```

**432 tests, all passing.** They cover:

- parser behaviour against the committed workbooks: confirmed published values,
  `…` and `NULL` preserved as gaps rather than zeroed, the numeric-string cell
  for 2010, a decimal comma refused rather than guessed, `**` read as
  preliminary and `*` correctly not;
- the currency-era mapping, the 1994→1995 cliff and its unit change, and the
  canonicalisation of `2007_I` and `2008 IV` to `2007-Q1` and `2008-Q4`;
- every published spelling of every region resolving to one code, the
  region/municipality collision staying separate, aggregates staying out of
  rankings, and an unknown place raising rather than being invented;
- every contract passing on clean data and failing on the fault that targets it,
  with offending rows named, plus both directions of the `KNOWN_FAILURES` guard;
- real-earnings, deflation, inflation, growth, household-balance and
  enterprise-rate maths against hand-computed values, including the birth rate
  checked against the published 2024 national figure;
- the analyst's answers and, specifically, its refusals — including that a
  refusal never attaches a source or a number, that a count question gets a
  count rather than a rate, and that a new intent does not create a back door
  around the refusals;
- batch refresh with one failing source, an unexpected exception, an empty body
  and unchanged bytes, none of which may cancel the rest;
- vintage immutability: fault injection cannot change a committed vintage's
  checksum, and committed files are read-only on disk;
- CSV parity with the HTML selection, and provenance on every exported row;
- every route returning 200 in both languages, every data table announced to
  screen readers and wrapped in a scroll container, no static inline styles, and
  the deployed-copy refresh refusal;
- the second source: that the snapshot is committed, read-only and carries both
  halves of the API response, that both readings resolve places through the same
  registry, that they agree, that a 2% drift too small for any magnitude check
  is caught, and that comparing zero cells fails rather than passing trivially;
- cadence inference and overdue detection, including that a period still in
  progress is not reported late;
- that no committed screenshot is small enough to be a browser error card, and
  that every screenshot the README references exists.

Deliberately not covered: the live network path (the adapters' `download` is
monkeypatched in tests so the suite runs offline and deterministically), browser
rendering, and the exact SVG geometry of the charts.

## Deploying

```bash
docker build -t geostats .
docker run -p 8013:8013 geostats
```

A deployed copy is a **read-only publication**. It serves the vintages committed
in the repository and never calls Geostat: `POST /refresh` and `POST
/refresh-all` are refused unless `GEOSTATS_ALLOW_REFRESH=1` is set, which is
deliberately not set in the image. Refreshing is a maintainer's action taken
locally, whose output is a new immutable vintage to review and commit.

`GET /healthz` returns the dataset, vintage and observation counts, and fails
with 503 if any contract is failing that `KNOWN_FAILURES` does not explain.

```bash
python -m app.refresh_all --dry-run          # report without writing
python -m app.refresh_all                    # every dataset
python -m app.refresh_all --snapshots        # also recapture the PX-Web tables
python -m app.refresh_all labour_force cpi_yoy
```

One failed source never cancels the successful ones, and the sqlite index is
rebuilt only after the whole batch has been written and validated.

## Limitations

- Earnings before 1995 are denominated in Rouble, Coupon or Thousand Coupon. No
  conversion is applied, because none is published in these files. Those years
  are excluded from every default view.
- The CPI series begins in 2000, so wage years 1995–1999 cannot be deflated at
  all. The `JOIN` contract fails on exactly those years rather than hiding them.
- All earnings figures are **gross, before personal income tax**, and are an
  average over paid employees (earnings fund ÷ average paid employees ÷ months).
  They are not take-home pay and not a typical person's salary.
- The Labour Force Survey breaks between 2009 and 2010 on the ICLS-19 standard.
  No adjustment is applied because Geostat publishes none; the break is declared
  and every comparison crossing it says so.
- Household income and expenditure are **self-reported** and are not comparable
  with the earnings series: that one counts a job, this one counts a household
  and includes pensions, transfers and own produce. The difference between
  reported income and reported expenditure is a survey artefact and is never
  presented as a savings rate.
- The median series starts in 2018, comes from a different source (Revenue
  Service administrative records rather than the enterprise survey), and is
  published by economic activity only — never by region, sex or ownership.
- No distribution is published, so percentiles cannot be derived. The analyst
  refuses rather than modelling them.
- Earnings by activity exist under two incompatible classifications (NACE rev.1
  to 2019, NACE rev.2 from 2014). They are kept as separate breakdowns and are
  not spliced.
- Regional figures from the enterprise survey place enterprises at their
  head-office location, which overstates Tbilisi relative to where work is
  physically done. The household and labour force surveys do not have this
  problem, and the atlas says which is which.
- Business demography counts registrations, not economic activity: an individual
  entrepreneur registering counts the same as a factory opening.
- The tourism visitor survey was suspended from 2020-Q2 to 2021-Q4. The seven
  missing quarters fail `COVERAGE` rather than being interpolated.
- The regional labour force file stops publishing the hired / self-employed
  split for 2010–2019. The core indicators are complete; that split is not.
- The latest annual earnings figure is preliminary and will be revised.
- Only one dataset (`earnings_by_region`) has a multi-release history, so the
  value-revision path of the diff engine is demonstrated through the fault lab
  rather than through a real Geostat revision. If Geostat revises a figure, the
  `Refresh` button will capture it.
- Population is ingested down to municipality level but no page plots
  municipalities yet; they reach the UI only through the explorer and CSV.
- Georgian covers the navigation, indicator labels, table headers and status
  words only. Explanatory prose stays in English deliberately; a half-correct
  Georgian rendering of a statistical caveat is worse than an English one, and
  the UI says so on every Georgian page.

## Source

All data is from Geostat, the National Statistics Office of Georgia:

- Wages: <https://www.geostat.ge/en/modules/categories/39/wages>
- Inflation: <https://www.geostat.ge/en/modules/categories/26/inflation-consumer-price-index>
- Employment and unemployment:
  <https://www.geostat.ge/en/modules/categories/683/dasakmeba-umushevroba>
- Household income:
  <https://www.geostat.ge/en/modules/categories/50/households-income>
- Household expenditure:
  <https://www.geostat.ge/en/modules/categories/51/households-expenditures>
- Population: <https://www.geostat.ge/en/modules/categories/41/population>
- Business demography:
  <https://www.geostat.ge/en/modules/categories/69/business-demography>
- Regional statistics:
  <https://www.geostat.ge/en/modules/categories/93/regional-statistics>
- PX-Web database (the second source): <https://pc-axis.geostat.ge/PXWeb/>

Fetching these files requires a browser `User-Agent` header. Without one Geostat
answers HTTP 200 with a zero-byte body, which a naive ingester would record as a
successful empty release; the byte size is stored in every vintage so that an
empty response is visible rather than silent.
