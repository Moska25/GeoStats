"""Vercel entrypoint.

Vercel's Python runtime serves an ASGI app exported as `app`. The application
directory is read-only there and only /tmp is writable, so the two derived
paths are redirected before app.main is imported and rebuilds the index.

Everything else is the same application: the vintages ship in the deployment
as committed files, and GEOSTATS_ALLOW_REFRESH stays unset, so the deployed
copy is read-only by design.
"""

import os

os.environ.setdefault("GEOSTATS_DB", "/tmp/geostats.db")
os.environ.setdefault("GEOSTATS_LAB_DIR", "/tmp/geostats-lab")

from app.main import app  # noqa: E402  (must follow the env defaults)

__all__ = ["app"]
