#!/usr/bin/env python3
"""Recapture every README screenshot against a verified running server.

This exists because `docs/screenshots/regions.png` was for a long time a
committed screenshot of Chrome's ERR_CONNECTION_REFUSED page. Nothing caught
it: it was the right size, in the right directory, referenced from the right
line of the README, and it had been taken by a human who did not look at it
afterwards.

So the capture is verified rather than trusted. Before writing any file this
script:

  1. checks the server actually answers on the port,
  2. fetches each page over HTTP and asserts it returns 200 and contains a
     marker string that only the real page has,
  3. captures with headless Chrome,
  4. asserts the resulting PNG is large enough to be a page rather than an
     error card, and that Chrome did not report a navigation failure.

Any failure aborts before the existing screenshot is replaced. A stale correct
screenshot beats a fresh wrong one.

    ./run.sh &
    ./.venv/bin/python tools/capture_screenshots.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "docs" / "screenshots"
BASE = "http://127.0.0.1:8013"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# A screenshot smaller than this is an error card, a blank page or a crash.
# The real pages are 300 KB and up at 2x on a 1400px viewport.
MIN_BYTES = 40_000

# (filename, path, viewport, a string only the real page contains)
SHOTS: list[tuple[str, str, tuple[int, int], str]] = [
    ("overview.png", "/", (1400, 1150), "The trap: four currencies"),
    ("hero.png", "/explorer?include_pre_gel=1&year_from=1990&year_to=2000",
     (1400, 1000), "mixes currency eras"),
    ("work.png", "/work", (1400, 1250), "on separate axes"),
    ("households.png", "/households", (1400, 1250), "not a savings rate"),
    ("atlas.png", "/regions?metric=earnings", (1400, 1200),
     "cartogram, not a map"),
    ("atlas-region.png", "/regions?metric=earnings&region=kakheti",
     (1400, 1250), "against Georgia"),
    ("regions.png", "/regions?metric=unemployment&year=2024", (1400, 1150),
     "a person is counted where they live"),
    ("reliability.png", "/reliability", (1400, 1150), "failing checks are real"),
    ("contract-sheet.png", "/reliability/earnings_annual", (1400, 1200),
     "Contract results"),
    ("vintage-diff.png", "/reliability/earnings_by_region", (1400, 1200),
     "2020-10-13T14-57-22Z"),
    ("ask-refusal.png", "/ask?q=What+is+the+90th+percentile+salary+in+Georgia%3F",
     (1400, 1000), "cannot be reconstructed"),
    ("salary.png", "/salary?amount=1500", (1400, 1050), "not a percentile"),
    ("lab.png", "/lab?fault_id=mislabel_era", (1400, 1150), "CURRENCY_ERA"),
    ("methodology.png", "/methodology", (1400, 1150), "Limitations"),
    ("case-study.png", "/case-study", (1400, 1250), "Immutable vintages"),
    ("second-source.png", "/reliability/labour_force_by_region", (1400, 1150),
     "Checked against a second source"),
    ("release-staleness.png", "/reliability", (1400, 1150),
     "have not published the period"),
    ("explorer-csv.png",
     "/explorer?dataset=labour_force&indicator=unemployment_rate_percentage",
     (1400, 1100), "Download CSV"),
    ("mobile-375.png", "/regions?metric=earnings", (375, 900), "cartogram"),
]


def fetch(path: str) -> str:
    with urllib.request.urlopen(BASE + path, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        return response.read().decode("utf-8", "replace")


def check_server() -> None:
    try:
        fetch("/healthz")
    except (urllib.error.URLError, OSError) as exc:
        sys.exit(
            f"No server on {BASE} ({exc}).\n"
            "Start it first:  ./run.sh &\n"
            "Refusing to capture: a screenshot of a connection error is worse "
            "than no screenshot, and that is exactly how regions.png got "
            "committed."
        )


def capture(path: str, out: Path, size: tuple[int, int]) -> None:
    width, height = size
    with tempfile.TemporaryDirectory() as profile:
        # stderr goes to a real file, not a pipe. Chrome spawns an updater that
        # inherits the parent's handles and outlives the browser, so a pipe is
        # never closed and `subprocess.run` waits on EOF forever - the shot is
        # already written by then, which makes it look like a capture failure
        # when it is a plumbing one.
        log_path = Path(profile) / "chrome.log"
        with open(log_path, "w") as log:
            _run_chrome(log, [
                # `--headless` (the old mode) takes the shot and exits.
                # `--headless=new` keeps the browser alive afterwards and the
                # run just hangs until it is killed.
                CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
                "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", "--disable-background-networking",
                f"--user-data-dir={profile}",
                f"--window-size={width},{height}",
                "--force-device-scale-factor=2",
                "--virtual-time-budget=4000",
                f"--screenshot={out}",
                BASE + path,
            ], out)
        noise = log_path.read_text(errors="replace").lower()

    for bad in ("err_connection", "err_empty_response", "err_name_not_resolved"):
        if bad in noise:
            raise RuntimeError(f"chrome reported {bad} for {path}")
    if not out.exists():
        raise RuntimeError(f"chrome wrote no screenshot for {path}")


def _run_chrome(log, argv: list[str], out: Path, timeout: float = 90.0) -> None:
    """Launch Chrome, wait for the PNG to be finished, then stop the browser.

    Chrome on this machine writes the screenshot and then stays alive - the
    bundled updater keeps the process group up - so waiting for it to exit
    never returns. Waiting for the *artefact* instead is both faster and a
    better test: the file appearing and settling at a stable size is the thing
    actually being asked for.
    """
    process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + timeout
    stable_size = -1
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None and out.exists():
                return
            if out.exists():
                size = out.stat().st_size
                if size and size == stable_size:
                    return                     # written and no longer growing
                stable_size = size
            time.sleep(0.4)
        raise RuntimeError(f"timed out after {timeout:.0f}s waiting for {out.name}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


def main() -> int:
    if not Path(CHROME).exists():
        sys.exit(f"headless Chrome not found at {CHROME}")
    check_server()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    staging = Path(tempfile.mkdtemp(prefix="geostats-shots-"))
    captured: list[tuple[Path, Path]] = []
    try:
        for name, path, size, marker in SHOTS:
            html = fetch(path.split("#")[0])
            if marker.lower() not in html.lower():
                raise RuntimeError(
                    f"{path} rendered without {marker!r} - the page is not the "
                    "one this screenshot claims to show"
                )
            target = staging / name
            capture(path, target, size)
            if not target.exists():
                raise RuntimeError(f"{name} was not written")
            written = target.stat().st_size
            if written < MIN_BYTES:
                raise RuntimeError(
                    f"{name} is only {written:,} bytes; an error card or a "
                    f"blank page, not {path}"
                )
            captured.append((target, OUT_DIR / name))
            print(f"  ok  {name:22} {written // 1024:5} KB  {path}")
    except Exception as exc:                         # noqa: BLE001
        shutil.rmtree(staging, ignore_errors=True)
        sys.exit(f"\nCapture aborted, nothing replaced: {exc}")

    # Only now, with every shot verified, replace the committed files.
    for source, destination in captured:
        shutil.move(str(source), destination)
    shutil.rmtree(staging, ignore_errors=True)
    print(f"\n{len(captured)} screenshots written to {OUT_DIR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
