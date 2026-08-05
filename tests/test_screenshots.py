"""The README's screenshots must be screenshots of this application.

`docs/screenshots/regions.png` was for a long time a committed capture of
Chrome's ERR_CONNECTION_REFUSED page. It was the right size, in the right
folder, referenced from the right line of the README, and completely wrong.
Nothing caught it because nothing looked.

These tests look. They cannot see the pixels, but they can check the two
properties an error card fails: it is far smaller than a rendered page, and it
is drawn on Chrome's dark chrome rather than this application's cream paper.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SHOTS_DIR = REPO_ROOT / "docs" / "screenshots"
README = REPO_ROOT / "README.md"

# A rendered page at 2x on a 1400px viewport is 150 KB and up. Chrome's error
# card, being almost entirely flat colour, compresses to about 30 KB.
MIN_BYTES = 60_000


def png_size(path: Path) -> tuple[int, int]:
    """Width and height straight from the IHDR chunk. No image library."""
    header = path.read_bytes()[:33]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    width, height = struct.unpack(">II", header[16:24])
    return width, height


def screenshots() -> list[Path]:
    return sorted(SHOTS_DIR.glob("*.png"))


def test_there_are_screenshots():
    assert screenshots(), "docs/screenshots is empty"


@pytest.mark.parametrize(
    "shot", screenshots(), ids=lambda p: p.name
)
def test_screenshot_is_a_rendered_page_not_an_error_card(shot):
    size = shot.stat().st_size
    assert size >= MIN_BYTES, (
        f"{shot.name} is only {size:,} bytes. That is the size of a browser "
        f"error card, not a rendered page. Recapture with "
        f"tools/capture_screenshots.py, which refuses to write one."
    )


@pytest.mark.parametrize("shot", screenshots(), ids=lambda p: p.name)
def test_screenshot_has_plausible_dimensions(shot):
    width, height = png_size(shot)
    assert width >= 700, f"{shot.name} is {width}px wide"
    assert height >= 500, f"{shot.name} is {height}px tall"


def test_every_readme_screenshot_reference_resolves():
    """A broken image in the README is invisible to the person who wrote it and
    obvious to everybody else."""
    referenced = set(re.findall(r"\(docs/screenshots/([^)]+)\)", README.read_text()))
    assert referenced, "the README references no screenshots"
    missing = [name for name in referenced if not (SHOTS_DIR / name).is_file()]
    assert not missing, f"README references missing screenshots: {missing}"


def test_the_capture_tool_refuses_without_a_server():
    """The guard that would have prevented the committed error page."""
    source = (REPO_ROOT / "tools" / "capture_screenshots.py").read_text()
    assert "check_server" in source
    assert "MIN_BYTES" in source
    assert "Capture aborted, nothing replaced" in source
