# GeoStats — roadmap

## Status

Phases 1–7 are built and working. The application ingests eight real Geostat
workbooks into immutable vintages under `data/vintages/`, validates each vintage
against nine data contracts, and serves seven pages on port 8013 entirely
offline from committed data. `earnings_by_region` carries three genuine
published releases (2020-10-13, 2022-01-29, and the current file) so the vintage
diff runs against real revisions history; the other seven datasets have one
vintage each. Nine fault injections each trip their target contract on a copy of
a vintage, and every run re-verifies that the committed original's sha256 is
unchanged. The grounded analyst routes fourteen worked examples to a definite
answer or a specific refusal with no language model involved. **The test suite is
174 tests and is green** (`./.venv/bin/python -m pytest -q`). Three contract
checks fail on purpose and are surfaced as failures in the UI: `JOIN` cannot
match wage years 1995–1999 to a CPI annual average because the CPI series starts
in 2000.

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

- [ ] **GEO-8.1** Add a labour-force adapter for the employment/unemployment release.
      Files: `app/adapters.py`, `tests/test_adapters.py`
      Done when: `ADAPTERS["labour_force"]` downloads and normalises the
      employment, unemployment and activity-rate series into long format with a
      vintage id, and `test_every_adapter_parses_its_committed_vintage` covers it.
- [ ] **GEO-8.2** Add a rate-bounds contract for percentage indicators.
      Files: `app/contracts.py`, `tests/test_contracts.py`
      Done when: a new unit `rate_pct` is added to `RANGE_BY_UNIT` with bounds
      0–100, and the `RANGE` contract fails on an unemployment rate of 150.
- [ ] **GEO-8.3** Add a labour-market section to `/` showing the unemployment rate beside real wages.
      Files: `app/main.py`, `app/templates/index.html`
      Done when: the overview renders both series on one chart with the
      unemployment definition (ILO, age 15+) stated in a `.note`.

## Phase 9 — Quarterly series

- [ ] **GEO-9.1** Extend the period model to quarters.
      Files: `app/adapters.py`, `app/contracts.py`, `tests/test_contracts.py`
      Done when: `parse_period_header` produces `2024-Q3`, the `COVERAGE`
      contract detects a missing quarter in a quarterly series, and annual and
      quarterly rows of the same indicator coexist without colliding on the
      composite key.
- [ ] **GEO-9.2** Add the quarterly earnings adapter.
      Files: `app/adapters.py`, `data/vintages/`
      Done when: a real vintage of the quarterly earnings release is committed
      and passes every contract except `JOIN`.
- [ ] **GEO-9.3** Add a grain selector to `/explorer`.
      Files: `app/main.py`, `app/templates/explorer.html`
      Done when: switching to quarterly redraws the chart from quarterly rows and
      the annual/quarterly choice is preserved in the query string.

## Phase 10 — Regional atlas

- [ ] **GEO-10.1** Add a `/regions` page ranking regions with a bar chart per year.
      Files: `app/main.py`, `app/templates/regions.html`, `app/charts.py`
      Done when: the page renders `charts.bar_rows` output for a selected year
      from `earnings_by_region` and states the head-office caveat in a `.note`.
- [ ] **GEO-10.2** Add a region-relative-to-national index.
      Files: `app/metrics.py`, `tests/test_metrics.py`
      Done when: `region_index(region_value, national_value)` returns 100 when
      they are equal and is unit-tested against a hand-computed value.

## Phase 11 — Release-calendar monitoring

- [ ] **GEO-11.1** Parse the Geostat release calendar into scheduled release dates.
      Files: `app/calendar.py`, `tests/test_calendar.py`
      Done when: `next_release(dataset_id)` returns a date, or `None` with a
      reason when the calendar does not cover that dataset.
- [ ] **GEO-11.2** Flag datasets whose expected release has passed without a new vintage.
      Files: `app/main.py`, `app/templates/reliability.html`
      Done when: a reliability card shows a `pill-warn` reading "release expected
      <date>, latest vintage <date>" when the newest vintage predates the
      scheduled release.

## Phase 12 — PX-Web API adapter

- [ ] **GEO-12.1** Add a PX-Web adapter alongside the spreadsheet adapters.
      Files: `app/adapters.py`, `tests/test_adapters.py`
      Done when: an adapter fetches the same indicator through the PX-Web JSON
      API, normalises it into the identical long format, and passes every
      contract.
- [ ] **GEO-12.2** Cross-check the API and spreadsheet values for the same indicator.
      Files: `app/contracts.py`, `tests/test_contracts.py`
      Done when: a `SOURCE_AGREEMENT` contract fails if any period differs
      between the two sources by more than 0.01, and its message names the
      periods that disagree.

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

## Demo script (5 minutes)

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
   percentile salary in Georgia?* and read the refusal. Close on: this is a
   regex router over nine functions, and refusing is the feature.

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
- **NOT YET EARNED** — "Monitors the official release calendar and flags overdue
  publications." Requires GEO-11.1 and GEO-11.2.
- **NOT YET EARNED** — "Cross-validates spreadsheet releases against the PX-Web
  statistical API." Requires GEO-12.1 and GEO-12.2.
