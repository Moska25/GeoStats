# GeoStats — roadmap

## Status

**Phases 1–17 are built and working.** The application ingests **twenty** real
Geostat workbooks into immutable vintages under `data/vintages/`, validates each
vintage against **eleven** data contracts, and serves **twelve** pages on port
8013 entirely offline from committed data.

`earnings_by_region` carries three genuine published releases (2020-10-13,
2022-01-29, and the current file) so the vintage diff runs against real revision
history. Eleven fault injections each trip their target contract on a copy of a
vintage, and every run re-verifies that the committed original's sha256 is
unchanged. The grounded analyst routes twenty worked examples to a definite
answer or a specific refusal with no language model involved.

**The test suite is 432 tests and is green** (`./.venv/bin/python -m pytest -q`).

Eight contract checks fail on purpose and are surfaced as failures in the UI.
Every one is named in `contracts.KNOWN_FAILURES` with the reason it is left
red, and two tests guard that table in both directions: nothing may fail
without an entry, and no entry may survive its check starting to pass. They
are the CPI starting five years after the wage series, a regional split Geostat
stopped publishing for a decade, a pandemic-suspended tourism survey, and three
lumpy survey categories.

Two things beyond the original plan turned out to matter:

* **A second currency-era trap.** The Labour Force Survey breaks between 2009
  and 2010 on the ICLS-19 standard: employment falls 1,611 → 1,168 thousand
  because the definition moved, not the labour market. No unit changed, no year
  is missing and nothing is out of range, so no value check can see it. It is
  declared in `adapters.SERIES_BREAKS` and every comparison crossing it says so.
* **A second source.** Geostat publishes some series twice, as spreadsheets and
  as PX-Web API tables. `SOURCE_AGREEMENT` joins them and agrees on all 2,029
  shared cells of the regional labour force series to within the API's own
  rounding.

The interface is a light "statistical publication" theme, produced entirely by
overriding `base.css` variables in `app/static/app.css`; the shared `base.css`
is a verbatim copy and must stay one.

## How to pick up a task

1. Read this file and `MOSKA_MAIN/shared/CONVENTIONS.md` before writing anything.
2. Work only the task ids you were assigned. Do not "helpfully" pick up
   neighbouring tasks, and check `## Deliberately out of scope` before adding
   anything not listed here.
3. Run `./run.sh` and `./.venv/bin/python -m pytest -q` before reporting. Both
   must be clean. Report the test count.
4. **Never run a git command.** Not `add`, not `commit`, not `push`, not
   `checkout`. Leave the working tree dirty; the repository owner commits.
5. Any number that appears in the UI must be computed from data committed in
   `data/vintages/`. Do not invent statistics, and do not fabricate a vintage to
   make a feature look better.

## Phase 1 — Vintage-aware ingestion

- [x] **GEO-1.1** Write an adapter per dataset with `discover`/`download`/`parse`/`normalise`.
      Files: `app/adapters.py`
      Done when: `ADAPTERS` holds eight entries, each parsing its committed
      workbook into long-format `Row` objects with a non-empty period and unit.
- [x] **GEO-1.2** Send a browser User-Agent and Referer on every download.
      Files: `app/adapters.py`
      Done when: `Adapter.download` sets both headers and follows redirects;
      without them Geostat returns HTTP 200 with a zero-byte body.
- [x] **GEO-1.3** Write immutable vintages containing raw bytes, `meta.json` and `rows.json`.
      Files: `app/ingest.py`, `tests/test_ingest.py`
      Done when: `write_vintage` raises `VintageExists` on an existing path, the
      three files are chmod 0444 on disk, and `meta.json` records source URL,
      `retrieved_at`, sha256, HTTP status, byte size and row count.
- [x] **GEO-1.4** Commit at least one real vintage of every dataset so the app runs offline.
      Files: `data/vintages/`
      Done when: `./run.sh` seeds and serves with the network disconnected, and
      `test_offline_operation_needs_no_network` passes.
- [x] **GEO-1.5** Preserve the `**` preliminary marker as data.
      Files: `app/adapters.py`, `tests/test_adapters.py`
      Done when: `parse_period_header("2025**") == ("2025", True)` and
      `parse_period_header("2006*") == ("2006", False)`.
- [x] **GEO-1.6** Diff two vintages, reporting added, removed and changed values.
      Files: `app/ingest.py`, `tests/test_ingest.py`
      Done when: `diff_vintages` on the two archived regional releases reports
      added series and an empty `changed` list, and `diff_rows` detects a
      changed value, an added series and a preliminary-flag change.
- [x] **GEO-1.7** Add `POST /refresh` that fetches live, writes a new vintage and diffs it.
      Files: `app/main.py`, `app/ingest.py`, `tests/test_ingest.py`
      Done when: identical bytes write no new vintage, a network error and an
      empty body both return `ok: False` with a message, and in all three cases
      `list_vintages` is unchanged.

## Phase 2 — Data contracts

- [x] **GEO-2.1** Implement nine declarative contracts returning pass/fail, message and offenders.
      Files: `app/contracts.py`
      Done when: `run_contracts` returns nine `CheckResult`s and every failing
      one names at least one offending row.
- [x] **GEO-2.2** Implement the currency-era contract.
      Files: `app/contracts.py`, `tests/test_contracts.py`
      Done when: `CURRENCY_ERA` passes on the committed `earnings_annual`
      vintage and fails after the `mislabel_era` fault, naming the eras found.
- [x] **GEO-2.3** Make the schema contract gate the downstream checks.
      Files: `app/contracts.py`, `tests/test_contracts.py`
      Done when: the `rename_column` fault produces one `SCHEMA` failure and
      eight results with `skipped=True` and no raised exception.
- [x] **GEO-2.4** Fold the COICOP level into the basket-weights breakdown code.
      Files: `app/adapters.py`, `tests/test_adapters.py`
      Done when: codes `l2.11` and `l3.11` both exist and `KEY_UNIQUE` passes on
      the `basket_weights` vintage.

## Phase 3 — Analytics

- [x] **GEO-3.1** Write the pure metric functions.
      Files: `app/metrics.py`, `tests/test_metrics.py`
      Done when: `real_earnings_index`, `deflate`, `cumulative_inflation`,
      `annualised_inflation`, `preserve_purchasing_power`, `mean_median_gap`,
      `yoy_growth`, `real_growth` and `nominal_index` each match a hand-computed
      value in the test suite.
- [x] **GEO-3.2** Derive the CPI annual average only from complete years.
      Files: `app/adapters.py`, `tests/test_adapters.py`
      Done when: a year with fewer than twelve published months gets no annual
      average, and the derived 2010 average equals 100.0 to within 0.01.
- [x] **GEO-3.3** Keep undeflatable years visible instead of dropping them.
      Files: `app/metrics.py`, `app/templates/explorer.html`
      Done when: `build_series` returns a row with `real_index = None` for a year
      with no CPI, and the explorer renders `n/a` for it.

## Phase 4 — Grounded analyst

- [x] **GEO-4.1** Build a deterministic intent router over a closed metric set.
      Files: `app/analyst.py`, `tests/test_analyst.py`
      Done when: `ask` imports no HTTP client and no model client, and every
      answer carries dataset, indicator, breakdown, period, unit, vintage id,
      preliminary status, formula and source URL.
- [x] **GEO-4.2** Refuse questions the published aggregates cannot support.
      Files: `app/analyst.py`, `tests/test_analyst.py`
      Done when: percentile, occupation-cross, net-pay, forecast, employer-level
      and median-by-region questions all return `kind == "refusal"` with an
      explanation and an empty `provenance` list.
- [x] **GEO-4.3** Ship worked examples including refusals on `/ask`.
      Files: `app/analyst.py`, `app/templates/ask.html`
      Done when: `EXAMPLES` has at least twelve entries, at least four resolve to
      refusals, and each renders on the page with its outcome.

## Phase 5 — Fault-injection lab

- [x] **GEO-5.1** Implement nine faults, one per contract, operating on copies only.
      Files: `app/faults.py`, `tests/test_faults.py`
      Done when: each fault trips its declared target contract and
      `result["copy_path"]` starts with `data/cache/lab`.
- [x] **GEO-5.2** Verify vintage immutability on every injection.
      Files: `app/faults.py`, `tests/test_ingest.py`
      Done when: `inject` compares the committed `raw.xlsx` sha256 before and
      after, and `test_fault_injection_cannot_mutate_a_committed_vintage`
      passes for five faults in sequence.
- [x] **GEO-5.3** Render a defect report an engineer could paste into a ticket.
      Files: `app/faults.py`, `app/templates/lab.html`
      Done when: `defect_report` names the injected fault, the contracts tripped,
      the offending rows and the immutability check.

## Phase 6 — Bilingual EN/KA

- [x] **GEO-6.1** Add an EN/KA string table with English fallback and a top-bar toggle.
      Files: `app/i18n.py`, `app/templates/_layout.html`, `tests/test_web.py`
      Done when: `/?lang=ka` renders Georgian navigation, a missing Georgian key
      falls back to English rather than raising, and the choice survives via
      cookie and query parameter.
- [x] **GEO-6.2** State the translation coverage in the UI rather than implying completeness.
      Files: `app/i18n.py`
      Done when: every Georgian page shows a computed coverage percentage and
      says that methodology prose is deliberately untranslated.

## Phase 7 — Web app

- [x] **GEO-7.1** Build the seven pages on port 8013.
      Files: `app/main.py`, `app/templates/*.html`, `app/static/app.css`
      Done when: `/`, `/explorer`, `/salary`, `/reliability`, `/ask`, `/lab` and
      `/methodology` all return 200 and each opens with an `h1` and a `.lede`.
- [x] **GEO-7.2** Default the explorer to the Lari era and warn when the range crosses it.
      Files: `app/main.py`, `app/templates/explorer.html`, `tests/test_web.py`
      Done when: the default year range starts at 1995 and
      `/explorer?include_pre_gel=1&year_from=1990&year_to=2000` renders the
      "mixes currency eras" warning.
- [x] **GEO-7.3** Hold the layout at 375px with no horizontal page scroll.
      Files: `app/static/app.css`
      Done when: `document.documentElement.scrollWidth` equals
      `window.innerWidth` at a 375px viewport on every page.

## Phase 8 — Employment and unemployment

- [x] **GEO-8.1** Add a labour-force adapter for the employment/unemployment release.
      Files: `app/adapters.py`, `tests/test_adapters.py`
      Done when: `ADAPTERS["labour_force"]` downloads and normalises the
      employment, unemployment and activity-rate series into long format with a
      vintage id, and `test_every_adapter_parses_its_committed_vintage` covers it.
- [x] **GEO-8.2** Add a rate-bounds contract for percentage indicators.
      *Shipped as unit `percent`, not `rate_pct`: several committed vintages
      already carried `percent`, and renaming it would have meant re-ingesting
      them for a cosmetic change. Bounds and behaviour are as specified.*
      Files: `app/contracts.py`, `tests/test_contracts.py`
      Done when: a new unit `rate_pct` is added to `RANGE_BY_UNIT` with bounds
      0–100, and the `RANGE` contract fails on an unemployment rate of 150.
- [x] **GEO-8.3** Add a labour-market section to `/` showing the unemployment rate beside real wages.
      Files: `app/main.py`, `app/templates/index.html`
      Done when: the overview renders both series on one chart with the
      unemployment definition (ILO, age 15+) stated in a `.note`.

## Phase 9 — Quarterly series

- [x] **GEO-9.1** Extend the period model to quarters.
      Files: `app/adapters.py`, `app/contracts.py`, `tests/test_contracts.py`
      Done when: `parse_period_header` produces `2024-Q3`, the `COVERAGE`
      contract detects a missing quarter in a quarterly series, and annual and
      quarterly rows of the same indicator coexist without colliding on the
      composite key.
- [x] **GEO-9.2** Add the quarterly earnings adapter.
      Files: `app/adapters.py`, `data/vintages/`
      Done when: a real vintage of the quarterly earnings release is committed
      and passes every contract except `JOIN`.
- [x] **GEO-9.3** Add a grain selector to `/explorer`.
      Files: `app/main.py`, `app/templates/explorer.html`
      Done when: switching to quarterly redraws the chart from quarterly rows and
      the annual/quarterly choice is preserved in the query string.

## Phase 10 — Regional atlas (done)

- [x] **GEO-10.1** Add a `/regions` page ranking regions with a bar chart per year.
      Files: `app/main.py`, `app/templates/regions.html`, `app/charts.py`
      Done when: the page renders `charts.bar_rows` output for a selected year
      from `earnings_by_region` and states the head-office caveat in a `.note`.
      Eleven regions, 2010 to 2024, ranked descending with the national figure
      excluded from the ranking and used as the index base. The head-office
      caveat is a `.note-warn` above the exhibit, not a footnote.
- [x] **GEO-10.2** Add a region-relative-to-national index.
      Files: `app/metrics.py`, `tests/test_metrics.py`
      Done when: `region_index(region_value, national_value)` returns 100 when
      they are equal and is unit-tested against a hand-computed value.
      Both figures come from the same release, so the index never mixes a
      regional vintage with a national one from a different retrieval.

## Phase 15 — Publication apparatus (done)

A second design pass over Phase 13, taking the paper theme from "light" to
"typeset". Restyle plus one chart-rendering fix; no figure changed.

- [x] **GEO-15.1** Add a masthead dateline computed from the vintages on disk.
      Files: `app/db.py` (`summary` now returns `last_retrieved`), `app/main.py`,
      `app/templates/_layout.html`, `app/static/app.css`
- [x] **GEO-15.2** Number the statistical exhibits and give each one a source line.
      Files: `app/templates/_macros.html` (`exhibit`), `index.html`, `explorer.html`,
      `regions.html`
      Done when: every chart and every statistical table carries "Figure N" or
      "Table N", a title, and a source naming the dataset and vintage.
- [x] **GEO-15.3** Unwind the key-figures cards into a ruled band on `/`.
      Files: `app/templates/index.html`, `app/static/app.css`
- [x] **GEO-15.4** Add a skip link and a print stylesheet.
      Done when: keyboard focus reaches a visible "Skip to content" control, and
      printing drops the chrome, keeps table headers across pages and prints the
      source URLs.
- [x] **GEO-15.5** Stop the x axis printing two year labels on top of each other.
      Files: `app/charts.py`, `tests/test_web.py`
      Done when: on the 1970-2025 series the final period is still labelled and
      the smallest gap between axis labels is at least 40px.
- [x] **GEO-15.6** Stop using the failure red decoratively.
      Files: `app/templates/index.html`
      Done when: `pill-fail` appears only where a contract or a check actually
      failed, so red keeps meaning one thing.

## Phase 11 — Release-calendar monitoring

- [~] **GEO-11.1** Parse the Geostat release calendar into scheduled release dates.
      Files: `app/calendar.py`, `tests/test_calendar.py`
      **Not achievable as specified, and closed as such.** Geostat's calendar at
      <https://www.geostat.ge/en/calendar> is rendered client-side: the served
      HTML contains no dates at all, and the obvious JSON endpoints
      (`/api/calendar`, `/modules/calendar/*`) all return 404. Scraping a
      JavaScript-rendered page would also break the property that everything
      runs offline from committed data.
      What was built instead: `next_release(dataset_id, periods)` infers each
      dataset's cadence from its own published periods and reports the period
      the next release should cover, with the basis it was derived from.
      `scheduled_date(dataset_id)` returns `(None, reason)` for every dataset,
      which is the honest answer — inventing "expected 15 March" would be
      exactly the fabrication the rest of this project refuses.
- [x] **GEO-11.2** Flag datasets whose expected release has passed without a new vintage.
      *The pill reads "2025 expected, newest published is 2024" rather than
      carrying a date, because GEO-11.1 established there is no date to carry.
      Nine datasets are currently flagged, including every detailed earnings
      breakdown — Geostat publishes those a year behind the headline figure.*
      Files: `app/main.py`, `app/templates/reliability.html`
      Done when: a reliability card shows a `pill-warn` reading "release expected
      <date>, latest vintage <date>" when the newest vintage predates the
      scheduled release.

## Phase 12 — PX-Web API adapter

- [x] **GEO-12.1** Add a PX-Web adapter alongside the spreadsheet adapters.
      *Lives in `app/pxweb.py` rather than in `ADAPTERS`, because it is a
      cross-check rather than a dataset: it produces no vintage and no page
      reads from it. The API reading is frozen to `data/pxweb/` with its own
      checksum so the comparison runs offline. Two quirks of this installation
      are documented in the module: `json-stat2` 404s where `json` works, and a
      query carrying a `selection` 404s where an empty one returns the table.*
      Files: `app/adapters.py`, `tests/test_adapters.py`
      Done when: an adapter fetches the same indicator through the PX-Web JSON
      API, normalises it into the identical long format, and passes every
      contract.
- [x] **GEO-12.2** Cross-check the API and spreadsheet values for the same indicator.
      *Tolerance is 0.05, not 0.01: PX-Web rounds to one decimal place and the
      spreadsheets carry full precision, so half the last published digit is
      the largest gap rounding alone can produce. Derived, not tuned — the
      worst observed disagreement across 2,029 shared cells is exactly 0.05.*
      Files: `app/contracts.py`, `tests/test_contracts.py`
      Done when: a `SOURCE_AGREEMENT` contract fails if any period differs
      between the two sources by more than 0.01, and its message names the
      periods that disagree.

## Phase 13 — Visual identity: "statistical publication" (done)

Design spec: `MOSKA_MAIN/shared/UI_DIRECTION.md`, GeoStats section. Restyle only:
ingestion, contracts, metrics and the analyst are untouched and no figure changes.
This is the highest-risk restyle in the portfolio because it inverts the theme.

- [x] **GEO-13.1** Invert to the light paper theme by overriding the CSS variables in
      `app/static/app.css` only — never fork `base.css`.
      Done when: every page passes AA contrast, nothing still assumes a dark background,
      and both `?lang=en` and `?lang=ka` render correctly.
      Landed: paper `#faf7f2` / ink `#16181d`, with `--accent-text`, `--pass`, `--fail`,
      `--warn` and `--info` re-derived for a light ground and each measured against its
      own pill tint. A computed-style audit over 16 page/language combinations reports
      zero AA failures. `base.css` is untouched; `--r`, `--r-sm` and `--maxw` are left
      exactly as the shared skeleton sets them.
- [x] **GEO-13.2** Add the serif display scale with a verified Georgian fallback.
      Files: `app/static/app.css`
      Done when: a Georgian heading on `/explorer?lang=ka` renders in a font that actually
      supports the script; if the serif stack does not, `:lang(ka)` headings fall back to
      system sans.
      Measured, do not undo: "მსყიდველობითი" is 166.42578125px wide at 20px in Georgia,
      Times New Roman, ui-serif, serif AND in a deliberately missing family — identical to
      the pixel, so no serif here supplies Georgian and every one of them substitutes.
      `:lang(ka)` headings therefore take the system sans.
- [x] **GEO-13.3** Add the currency-era band beneath the explorer chart.
      Files: `app/charts.py`, `app/templates/explorer.html`, `app/static/app.css`
      Done when: including pre-1995 columns visibly shades the affected span and names
      Rouble, Coupon, Thousand Coupon and GEL.
      `charts.era_bands` groups the plotted periods into contiguous runs of one currency
      using the unit recorded on each observation, not a re-derivation.
- [x] **GEO-13.4** Restyle the vintage list as an editorial timeline showing retrieval route,
      checksum and diff.
      Files: `app/templates/reliability_detail.html`, `app/static/app.css`
      Done when: the Internet Archive route stays clearly distinguished from direct fetches.
- [x] **GEO-13.5** Restyle contract results as a printed audit sheet with a pass/fail gutter
      and the existing "Why:" note set as a footnote.
      Files: `app/templates/reliability_detail.html`, `app/static/app.css`
- [x] **GEO-13.6** Re-verify 375px on every page in both languages after the inversion.
      Done when: `scrollWidth === clientWidth` on all 16 route/language combinations.
      Verified on all 16, plus 16 heavier states (explorer with pre-1995 columns, both lab
      fault reports, a refusal on `/ask`, the salary ladder at its maximum amount, two more
      dataset detail pages, the refresh banner). One regression was found and fixed on the
      way: the tracked uppercase masthead subtitle made `.brand` — which is `nowrap` in
      `base.css` — 411px wide, so `.brand-sub` is hidden below 640px.

## Phase 14 — Showcase assets (done)

- [x] **GEO-14.1** Capture screenshots into `docs/screenshots/`: hero (explorer with era band),
      reliability card, vintage diff, the analyst refusing a question, plus one at 375px.
      Done when: five captioned PNGs exist, taken after Phase 13 lands.
      Six shipped: `hero.png`, `reliability.png`, `contract-sheet.png`, `vintage-diff.png`,
      `ask-refusal.png`, `mobile-375.png`. Note for whoever recaptures them: headless
      Chrome clamps its viewport to a 500px minimum, so `--window-size=375` silently
      renders at 500px and crops. The 375px shot was taken through a 375px-wide iframe in
      a 500px window and centre-cropped.
- [x] **GEO-14.2** Link the hero image at the top of README.md.

## Phase 16 — Showcase completion (done)

Phases 13 and 15 typeset the overview, explorer, regions and reliability pages.
Three pages never got the same attention (`/salary`, `/methodology`, `/lab`), the
tables are not announced to screen readers, and an unknown URL still returns raw
JSON. This phase closes those gaps. Restyle plus two new computed exhibits; no
existing figure changes.

- [x] **GEO-16.1** Replace the salary comparison list with a position scale.
      Files: `app/main.py` (`salary`), `app/templates/salary.html`, `app/static/app.css`
      Done when: `/salary?amount=1500` renders one horizontal scale carrying three
      marked points (published median, published mean, the entered amount), the
      entered amount is positioned by value rather than by rank, and a caption
      states that two published points are not a distribution and the space
      between them is not a percentile.
      `charts.position_scale` is the pure function behind it, unit-tested in
      `tests/test_charts.py` including the case where the entered amount is
      larger than both published figures.
- [x] **GEO-16.2** Add the Tbilisi-premium-over-time exhibit to `/regions`.
      Files: `app/main.py` (`regions`), `app/templates/regions.html`
      Done when: a second chart plots each published year's index for the highest
      and lowest region against the national 100 line, every point comes from
      `metrics.region_index` over committed data, and the caption names the first
      and last year of the span rather than asserting a trend.
- [x] **GEO-16.3** Set `/methodology` as a numbered document with a contents list.
      Files: `app/templates/methodology.html`, `app/static/app.css`
      Done when: each section carries a stable `id` and a section number, a
      contents list at the top links to all of them, and `pill-fail` no longer
      appears on that page for anything that is not a failure.
- [x] **GEO-16.4** Announce every statistical table to screen readers.
      Files: the templates carrying `table.data`, `app/static/app.css`
      Done when: every `table.data` has a `<caption>`, the caption is visually
      hidden where an exhibit head already prints the same words, and the hiding
      class keeps the text reachable (clip, not `display: none`).
- [x] **GEO-16.5** Serve a styled 404 instead of raw JSON.
      Files: `app/main.py`, `app/templates/404.html`
      Done when: `/not-a-page` returns HTTP 404 with the site shell, an `h1`, a
      `.lede`, and links to the pages that do exist, in both languages.
- [x] **GEO-16.6** Give `/lab` the exhibit apparatus.
      Files: `app/templates/lab.html`
      Done when: the contract-results table is a numbered exhibit with a source
      line naming the injected fault and the vintage it was copied from, and the
      defect report block says in the UI that it is generated text meant to be
      pasted into a ticket.
- [x] **GEO-16.7** Capture the remaining showcase screenshots.
      Files: `docs/screenshots/`, `README.md`
      Done when: `salary.png`, `lab.png` and `methodology.png` exist, taken after
      16.1 to 16.6 land, and each is captioned in the README.
- [x] **GEO-16.8** Re-verify the whole surface after Phase 16.
      Done when: `pytest` is green with the count recorded here, every route and
      the 404 return the expected status in both languages, `scrollWidth ===
      clientWidth` at 375px on all of them, and the computed-style contrast audit
      reports zero AA failures.
      How to reproduce the layout and contrast checks, because doing it against
      a live server is flaky here: render every page variant through
      `TestClient`, inline `base.css` and `app.css` into each response in place
      of the two `<link>` tags, embed them all in one local HTML file, and walk
      them in a single reused iframe with `document.write`. No server and no
      network means headless Chrome has nothing to wait for and `--dump-dom`
      returns a complete result. Measure `scrollWidth`/`clientWidth` at 375px
      and composite every text node's colour against its real background for AA.
      206 tests green. 28 route/language/state combinations hold
      `scrollWidth === clientWidth` at 375px, and the contrast audit reports
      zero AA failures across 56 renders (each combination at 375px and 1280px).

## Phase 17 — Next, in priority order (not started)

Everything above this line runs from data already committed. Everything below
needs a **new vintage fetched from Geostat**, so each task starts by finding the
workbook URL and ends by committing a real vintage. Geostat is reachable and
answers a browser User-Agent; without one it returns HTTP 200 with a zero-byte
body, which `Adapter.download` already guards against. Never fabricate a vintage
to unblock a task: if the file cannot be found, mark the task blocked and say so.

**Do these in order.** 17.1 is the cheapest real win, 17.5 is the largest.

- [x] **GEO-17.1** Answer a named region with that region's figure, not the whole ranking.
      Files: `app/analyst.py`, `tests/test_analyst.py`
      `_intent_region` already routes regional questions and returns the full
      ranking. The gap was narrower: *What did Imereti earn in 2024?* led with
      Tbilisi and Racha-Lechkhumi because the headline is always top-and-bottom.
      Done when: a question naming a region leads with that region's figure and
      its index against the national average, the ranking stays as the table, an
      unnamed regional question still leads with top and bottom, and the refusal
      for *median by region* still fires because the median series carries no
      regional breakdown. No new data needed; `earnings_by_region` is committed.
- [x] **GEO-17.2** Add a `?format=csv` download to the explorer and the regions page.
      Files: `app/main.py`, `tests/test_web.py`
      Done when: the response is `text/csv` with a `Content-Disposition` filename
      carrying the dataset and vintage id, the header row names the unit, and the
      rows equal the ones rendered in the HTML table for the same query string.
      A statistics platform that cannot export is a screenshot.
- [x] **GEO-17.3** Add the labour-force adapter (supersedes GEO-8.1).
      Files: `app/adapters.py`, `data/vintages/labour_force/`, `tests/test_adapters.py`
      Done when: the employment, unemployment and activity-rate series parse into
      long format from a committed vintage, `test_every_adapter_parses_its_committed_vintage`
      covers `labour_force`, and the ILO age-15+ definition is recorded in the
      adapter `note` so the UI can print it.
- [x] **GEO-17.4** Add the rate-bounds contract for percentage indicators (supersedes GEO-8.2).
      *Unit is `percent` rather than `rate_pct` — see GEO-8.2. The matching
      fault is `impossible_rate`, which pushes a rate to 150%.*
      Files: `app/contracts.py`, `tests/test_contracts.py`
      Done when: `RANGE_BY_UNIT` gains `rate_pct` bounded 0 to 100, the `RANGE`
      contract fails on an unemployment rate of 150 with the offending row named,
      and a matching fault exists in `app/faults.py` so the lab still has one
      injection per contract.
- [x] **GEO-17.5** Extend the period model to quarters (supersedes GEO-9.1).
      Files: `app/adapters.py`, `app/contracts.py`, `tests/test_contracts.py`
      Done when: `parse_period_header` produces `2024-Q3`, `COVERAGE` detects a
      missing quarter in a quarterly series, and annual and quarterly rows of the
      same indicator coexist without colliding on the composite key. Do this
      before GEO-9.2: the quarterly adapter is unwritable until the period model
      accepts quarters.

## Deliberately out of scope

- **Forecasting or nowcasting wages.** A forecast has no vintage, no checksum and
  no source URL, so it cannot sit next to figures that do.
- **Gross-to-net tax conversion.** Needs each year's income-tax and pension rules;
  modelling them and labelling the output "official" is exactly the failure this
  project is arguing against.
- **Reconstructing a wage distribution from the mean and median.** Mathematically
  not recoverable; the analyst refuses it on purpose.
- **Splicing NACE rev.1 and rev.2 into one long activity series.** The
  classifications are not compatible and Geostat does not publish a bridge.
- **Any LLM in the analyst.** The closed metric set is what makes an answer
  checkable; an LLM would trade that for fluency.
- **A JavaScript charting library.** The charts are hand-rolled inline SVG so the
  application stays fully offline with no build step.
- **User accounts, saved queries, alerting.** Nothing here is per-user.
- **Converting pre-1995 Roubles or Coupons to Lari.** No official conversion
  series exists in these files, and inventing one would be fabrication.

## Demo script (6 minutes)

1. `./run.sh`, then open <http://127.0.0.1:8013/>. Point at the four metric
   cards: the 2025 mean is flagged preliminary, and the mean sits 48% above the
   median. Read the "What these numbers are" note aloud — gross, before tax, an
   average over paid employees.
2. Scroll to *The trap: four currencies in one row of columns*. Compare the two
   charts. Say: this is one row of one sheet, and the footnote explaining it is
   at the bottom of the file. Show the handover table: 1994 is 6,151.6 Thousand
   Coupons and 1995 is 13.5 Lari.
3. Open <http://127.0.0.1:8013/reliability>. Note the pass-rate tile and that
   three checks are red on purpose. Click through to
   <http://127.0.0.1:8013/reliability/earnings_by_region>: three real releases,
   three distinct checksums, and a diff showing years added with nothing revised.
4. Open <http://127.0.0.1:8013/lab?fault_id=mislabel_era>. Show `CURRENCY_ERA`
   catching the relabel, then the "Committed vintage: intact" tile and the
   sha256 comparison in the defect report. Click *Coerce published gaps to zero*
   to show `PARSE` catching a `fillna(0)`.
5. Open <http://127.0.0.1:8013/ask>. Run *What is 1000 GEL from 2015 worth in
   2024?* and point at the provenance strip. Then scroll to *What is the 90th
   percentile salary in Georgia?* and read the refusal. Say: this is a regex
   router over nine functions, and refusing is the feature.
6. Close on <http://127.0.0.1:8013/regions?year=2024>. Tbilisi at 119 against a
   national 100, and the caveat above the chart saying the ranking places
   enterprises at the head office. Scroll to Figure 2: both ends of the spread
   move, so the page reports a spread and fits no trend.

## Resume bullets

- Built a revision-aware statistics platform over eight real Geostat releases
  that stores every retrieval as an immutable, checksummed vintage and diffs
  releases to surface added, removed and revised values — verified against three
  genuine published versions of the same series. *(GEO-1.1 … GEO-1.7)*
- Designed a nine-check data-contract suite including a currency-era check that
  catches a four-currency redenomination hidden in adjacent spreadsheet columns,
  and proved each check bites with a matching fault injection run against copies
  of committed data. *(GEO-2.1 … GEO-2.4, GEO-5.1 … GEO-5.3)*
- Shipped a grounded question-answering layer with no LLM: a deterministic router
  over nine unit-tested metric functions that attaches dataset, vintage, unit and
  formula to every answer and refuses questions the published aggregates cannot
  support. *(GEO-3.1 … GEO-3.3, GEO-4.1 … GEO-4.3)*
- Built a regional earnings atlas that ranks eleven regions against the national
  figure from the same release, indexes each one, and states the head-office
  effect that inflates the capital instead of silently correcting for it.
  *(GEO-10.1, GEO-10.2)*
- **NOT YET EARNED** — "Monitors the official release calendar and flags overdue
  publications." Requires GEO-11.1 and GEO-11.2.
- **NOT YET EARNED** — "Cross-validates spreadsheet releases against the PX-Web
  statistical API." Requires GEO-12.1 and GEO-12.2.
