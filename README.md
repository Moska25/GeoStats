# GeoStats

A revision-aware data platform over real published statistics from Geostat, the
National Statistics Office of Georgia: wages and prices, with every retrieval
kept as an immutable vintage and every methodology caveat stated next to the
number it applies to.

![The series explorer with the currency-era band: the shaded span is not
Lari, and the strip under the axis names Rouble, Coupon, Thousand Coupon and
Lari](docs/screenshots/hero.png)

## What it does

- **Ingests eight real Geostat workbooks** (annual and median earnings, earnings
  by region, sex and activity, two CPI series, consumer basket weights) through
  an adapter per dataset, and normalises them into one long format keyed by
  `dataset_id, indicator_code, breakdown_code, period, unit, vintage_id`.
- **Keeps every retrieval as an immutable vintage.** `data/vintages/<dataset>/<UTC
  timestamp>/` holds the raw bytes, a `meta.json` with source URL, sha256, byte
  size and HTTP status, and the normalised rows. Nothing is ever overwritten;
  the files are chmod 0444 and the writer refuses an existing path.
- **Validates every vintage against nine data contracts** before the numbers
  reach a chart, including a currency-era check that catches the specific trap
  this dataset sets, and reports the offending rows when one fails.
- **Ranks the eleven regions against the national figure** for any published
  year, stating the head-office effect that inflates Tbilisi rather than
  quietly correcting for it.
- **Answers questions from a closed set of approved metric functions** and
  refuses the ones the published aggregates cannot support, with the reason.
- **Proves the contracts work** by injecting faults into copies of committed
  vintages and showing which check caught each one.

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

1. <http://127.0.0.1:8013/> — the overview. Scroll to *The trap: four currencies
   in one row of columns* and compare the two charts. The left one is what you
   get by plotting the sheet; the right one is the same data restricted to the
   Lari era.
2. <http://127.0.0.1:8013/methodology> — the currency-era section and the table
   listing every published period with the currency actually in force that year.
   Also read the Limitations list; it is real.
3. <http://127.0.0.1:8013/reliability/earnings_by_region> — three genuine
   releases of the same series (October 2020, January 2022, and the current
   file), each with its own sha256, and a diff between them. The diff reports
   that Geostat added years without revising any earlier figure, which is a
   finding, not an absence of one.
4. <http://127.0.0.1:8013/lab?fault_id=mislabel_era> — relabel the pre-1995
   Rouble and Coupon rows as Lari on a copy of a committed vintage, and watch
   `CURRENCY_ERA` catch it. The panel shows the committed vintage's checksum
   before and after the run to prove the original was untouched. Try the other
   eight faults from the same page.
5. <http://127.0.0.1:8013/ask> — the grounded analyst. Skip past the answers to
   the refusals: *What is the 90th percentile salary in Georgia?* and *What is
   the average take-home pay after tax in 2024?* Those are the interesting ones.
6. <http://127.0.0.1:8013/regions?year=2024> — the eleven regions indexed
   against the country. Tbilisi at 119 is the head-office effect, and the page
   says so above the chart rather than in a footnote nobody reads.

## Screenshots

The interface is deliberately a light one: a printed statistical yearbook rather
than a dashboard. Serif display type, thin rules, numbered exhibits with a source
line under each one, an editorial measure for prose, and footnotes set as
footnotes. The masthead carries a real dateline, computed from the vintages on
disk rather than typed in.

![The overview: a ruled key-figures band, then the same published column set
plotted naively and honestly side by side](docs/screenshots/overview.png)

*`/` — the key figures, then Figure 1: why the naive line is meaningless.*

![Regional earnings ranked for 2024, each region indexed against the national
figure, with the head-office caveat stated above the
chart](docs/screenshots/regions.png)

*`/regions` — ranked, indexed, and honest about what the ranking measures.*

![Dataset reliability: one card per dataset with retrieval time, checksum,
byte size and contract pass rate. The headline rate is an honest 96 percent,
not a tuned 100](docs/screenshots/reliability.png)

*`/reliability` — eight datasets, ten vintages, 7,197 observations, and a 69/72
contract pass rate that is left failing on purpose.*

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

![The analyst refusing to answer a percentile question, with the reason and what
data would be needed](docs/screenshots/ask-refusal.png)

*`/ask` — a percentile cannot be reconstructed from a mean and a median, so the
analyst refuses and says what it would need instead.*

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

![The methodology page as a numbered document with a contents
list](docs/screenshots/methodology.png)

*`/methodology` — six numbered sections, a contents list, and a Limitations
section that is real.*

![The regional ranking at a 375 pixel viewport: rank, region and index on one
line, bar and figure on the next, with no horizontal page
scroll](docs/screenshots/mobile-375.png)

*375px. Every page holds `scrollWidth === clientWidth` at this width in both
English and Georgian.*

## How it works

```
   Geostat .xlsx  ──(browser UA + Referer, else 0 bytes)──▶  adapters.py
                                                               │ parse
                                                               ▼
                                              raw bytes + meta.json + rows.json
                                              data/vintages/<id>/<UTC stamp>/
                                                    (chmod 0444, never rewritten)
                                                               │
                          ┌────────────────────────────────────┼──────────────┐
                          ▼                                    ▼              ▼
                    contracts.py                            seed.py        faults.py
              9 declarative checks                     sqlite read index   copy → mutate
              pass/fail + offenders                    (derived, gitignored)  → re-check
                          │                                    │              │
                          └──────────────┬─────────────────────┘──────────────┘
                                         ▼
                             metrics.py (pure) · analyst.py (router)
                                         ▼
                        main.py → Jinja2 → 8 pages + charts.py (inline SVG)
```

The vintages on disk are the source of truth. The sqlite database is a derived
read index that `python -m app.seed` rebuilds from scratch on every start; it is
gitignored, and if it ever disagrees with a vintage the vintage wins.

Business logic lives in importable modules — `adapters`, `ingest`, `contracts`,
`metrics`, `analyst`, `faults`, `charts` — and the route handlers only assemble template
context. That is what makes the test suite meaningful: it imports the same
functions the pages call.

## Engineering notes

**The currency-era trap is the whole design.** Rather than filtering pre-1995
data out at read time, the unit is part of the composite key: `currency_for_year`
stamps every parsed value with the currency in force that year, so a mixed-era
series is structurally detectable rather than something a developer has to
remember. The `CURRENCY_ERA` contract fails any series carrying more than one era
under a single unit label, and the explorer refuses to default into the mess.

**A contract you have never seen fail is not a check.** Every contract except the
cross-dataset join has a matching fault in `app/faults.py`, and the test suite
asserts, for all nine, that the contract passes on the clean vintage and fails
after injection. That is also why `SCHEMA` gates the rest: a renamed column used
to raise `KeyError` in eight downstream checks, which reports one defect nine
times and crashes the page. It now short-circuits and marks the rest
"not evaluated".

**The failing checks in the UI are deliberate.** `JOIN` fails on three earnings
datasets because the CPI series starts in 2000 while earnings go back to 1995 —
those five years genuinely cannot be deflated. Tuning the threshold until the
dashboard was green would have hidden a limitation the analytics must respect,
so instead the explorer shows `n/a` for those years and the reliability page
explains why the check is red.

**The contracts found a real defect during development.** `KEY_UNIQUE` failed on
the consumer basket file: COICOP code `11` is *Food* at level 3 and *Restaurants
and hotels* at level 2, so the code alone is not a unique key. The fix (folding
the level into the breakdown code) is in `parse_basket_weights`, and the case is
pinned by a test.

**The vintage history is real, not synthesised.** Two earlier releases of the
regional earnings file were recovered from the Internet Archive so the log starts
before this project did. Their `meta.json` records the retrieval route honestly.
Fabricating a second vintage to make the diff feature look good would have been
the easy option and would have made every number on the page worthless.

**No LLM in the analyst.** It is a regex intent router over nine approved metric
functions. That is a deliberate downgrade in flexibility for a large upgrade in
checkability: every answer names the function and formula that produced it, and
anything outside the closed set gets no answer instead of a plausible one.

**Trade-offs taken.** The year-on-year CPI workbook has 274 columns of COICOP
tree per city; only the headline `Total` line is ingested, because that is the
only line anything else consumes. Temporal sanity skips `share_of_1` units,
because basket weights for small subgroups legitimately move by an order of
magnitude and the check would produce only noise there.

## Tests

```bash
./.venv/bin/python -m pytest -q
```

**206 tests, all passing.** They cover:

- parser behaviour against the committed workbook: the eight confirmed published
  values, `…` preserved as a gap rather than zeroed, the numeric-string cell for
  2010, a decimal comma refused rather than guessed, `**` read as preliminary
  and `*` correctly not;
- the currency-era mapping, and that the 1994→1995 cliff is accompanied by a
  unit change;
- every contract passing on clean data and failing on the fault that targets it,
  with offending rows named;
- real-earnings, deflation, inflation and growth maths against hand-computed
  values, and the purchasing-power round trip returning the original amount;
- the analyst's answers and, specifically, its refusals — including that a
  refusal never attaches a source or a number;
- vintage immutability: fault injection cannot change a committed vintage's
  checksum, and committed files are read-only on disk;
- refresh failing gracefully on a network error, an empty body, and unchanged
  bytes, without touching existing vintages;
- every route returning 200 and carrying its caveats.

Deliberately not covered: the live network path (the adapters' `download` is
monkeypatched in tests so the suite runs offline and deterministically), browser
rendering, and the exact SVG geometry of the charts.

## Limitations

- Earnings before 1995 are denominated in Rouble, Coupon or Thousand Coupon. No
  conversion is applied, because none is published in these files. Those years
  are excluded from every default view.
- The CPI series begins in 2000, so wage years 1995–1999 cannot be deflated at
  all. The `JOIN` contract fails on exactly those years rather than hiding them.
- All earnings figures are **gross, before personal income tax**, and are an
  average over paid employees (earnings fund ÷ average paid employees ÷ months).
  They are not take-home pay and not a typical person's salary.
- The median series starts in 2018, comes from a different source (Revenue
  Service administrative records rather than the enterprise survey), and is
  published by economic activity only — never by region, sex or ownership.
- No distribution is published, so percentiles cannot be derived. The analyst
  refuses rather than modelling them.
- Earnings by activity exist under two incompatible classifications (NACE rev.1
  to 2019, NACE rev.2 from 2014). They are kept as separate breakdowns and are
  not spliced.
- Regional figures place enterprises at their head-office location, which
  overstates Tbilisi relative to where work is physically done.
- The latest annual earnings figure is preliminary and will be revised.
- Only one dataset (`earnings_by_region`) has a multi-release history, so the
  value-revision path of the diff engine is demonstrated through the fault lab
  rather than through a real Geostat revision. If Geostat revises a figure, the
  `Refresh` button will capture it.
- Employment, unemployment, quarterly earnings and the full COICOP tree are not
  ingested.
- Georgian covers the navigation, indicator labels, table headers and status
  words only. Explanatory prose stays in English deliberately; a half-correct
  Georgian rendering of a statistical caveat is worse than an English one, and
  the UI says so on every Georgian page.

## Source

All data is from Geostat, the National Statistics Office of Georgia:

- Wages: <https://www.geostat.ge/en/modules/categories/39/wages>
- Inflation: <https://www.geostat.ge/en/modules/categories/26/inflation-consumer-price-index>

Fetching these files requires a browser `User-Agent` header. Without one Geostat
answers HTTP 200 with a zero-byte body, which a naive ingester would record as a
successful empty release; the byte size is stored in every vintage so that an
empty response is visible rather than silent.
