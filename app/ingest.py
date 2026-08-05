"""Vintage-aware ingestion.

A vintage is one immutable retrieval of one dataset:

    data/vintages/<dataset_id>/<UTC timestamp>/
        raw.xlsx     the exact bytes Geostat served
        meta.json    source URL, retrieved_at, sha256, HTTP status, byte size
        rows.json    the normalised long-format rows

Nothing here ever overwrites a vintage directory. `write_vintage` refuses to
touch a path that already exists, and every file it writes is chmod 0444. That
is the whole point of the project: official statistics get revised, corrected
and reclassified, and a platform that overwrites yesterday's file is lying to
its users about what it knew and when.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .adapters import ADAPTERS, Adapter, Row

REPO_ROOT = Path(__file__).resolve().parent.parent
VINTAGE_ROOT = REPO_ROOT / "data" / "vintages"


class VintageExists(Exception):
    """Raised when something tries to write over a committed vintage."""


def utc_stamp(when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    return when.strftime("%Y-%m-%dT%H-%M-%SZ")


def _freeze(path: Path) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def _thaw(path: Path) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------

def write_vintage(
    adapter: Adapter,
    data: bytes,
    http_status: int,
    *,
    root: Path | None = None,
    vintage_id: str | None = None,
    retrieved_at: str | None = None,
    extra_meta: dict | None = None,
) -> dict:
    """Persist one retrieval. Refuses to overwrite. Returns the meta dict."""
    root = root or VINTAGE_ROOT
    vintage_id = vintage_id or utc_stamp()
    target = root / adapter.dataset_id / vintage_id
    if target.exists():
        raise VintageExists(f"vintage already exists: {target}")

    rows = adapter.normalise(data, vintage_id)
    target.mkdir(parents=True)

    meta = {
        "dataset_id": adapter.dataset_id,
        "vintage_id": vintage_id,
        "title": adapter.title,
        "source_url": adapter.url,
        "source_page": adapter.source_page,
        "retrieved_at": retrieved_at or datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "http_status": http_status,
        "byte_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "row_count": len(rows),
        "period_grain": adapter.period_grain,
        "unit_family": adapter.unit_family,
        "note": adapter.note,
        "user_agent": (
            "browser User-Agent required; Geostat returns 0 bytes without one"
        ),
        "retrieval_via": "direct fetch from geostat.ge",
    }
    meta.update(extra_meta or {})

    raw_path = target / "raw.xlsx"
    raw_path.write_bytes(data)
    (target / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (target / "rows.json").write_text(
        json.dumps([r.to_dict() for r in rows], ensure_ascii=False) + "\n"
    )
    for name in ("raw.xlsx", "meta.json", "rows.json"):
        _freeze(target / name)
    return meta


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def list_vintages(dataset_id: str, root: Path | None = None) -> list[str]:
    root = root or VINTAGE_ROOT
    base = root / dataset_id
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "meta.json").is_file())


def latest_vintage(dataset_id: str, root: Path | None = None) -> str | None:
    ids = list_vintages(dataset_id, root)
    return ids[-1] if ids else None


def read_meta(dataset_id: str, vintage_id: str, root: Path | None = None) -> dict:
    root = root or VINTAGE_ROOT
    return json.loads((root / dataset_id / vintage_id / "meta.json").read_text())


def read_rows(dataset_id: str, vintage_id: str, root: Path | None = None) -> list[dict]:
    root = root or VINTAGE_ROOT
    return json.loads((root / dataset_id / vintage_id / "rows.json").read_text())


def read_raw(dataset_id: str, vintage_id: str, root: Path | None = None) -> bytes:
    root = root or VINTAGE_ROOT
    return (root / dataset_id / vintage_id / "raw.xlsx").read_bytes()


def all_datasets() -> list[str]:
    return list(ADAPTERS.keys())


def catalogue(root: Path | None = None) -> list[dict]:
    """One entry per dataset with its latest vintage meta, for the UI."""
    out = []
    for dataset_id, adapter in ADAPTERS.items():
        vintages = list_vintages(dataset_id, root)
        entry = {
            "dataset_id": dataset_id,
            "title": adapter.title,
            "url": adapter.url,
            "source_page": adapter.source_page,
            "note": adapter.note,
            "vintage_count": len(vintages),
            "vintages": vintages,
            "meta": read_meta(dataset_id, vintages[-1], root) if vintages else None,
        }
        out.append(entry)
    return out


# --------------------------------------------------------------------------
# diffing two vintages
# --------------------------------------------------------------------------

def _index(rows: list[dict]) -> dict[tuple, dict]:
    # .get on unit: the fault lab feeds this rows whose schema has been broken
    # on purpose, and the diff still has to render rather than raise.
    return {
        (r["indicator_code"], r["breakdown_code"], r["period"], r.get("unit", "?")): r
        for r in rows
    }


def diff_rows(old_rows: list[dict], new_rows: list[dict]) -> dict:
    """Compare two row sets on the composite key, ignoring vintage_id.

    Revisions to already-published numbers are the interesting case: they are
    invisible to any system that keeps only the newest file.
    """
    old = _index(old_rows)
    new = _index(new_rows)

    added = [new[k] for k in new.keys() - old.keys()]
    removed = [old[k] for k in old.keys() - new.keys()]
    changed, flag_changes = [], []
    for k in old.keys() & new.keys():
        o, n = old[k], new[k]
        if o.get("value") != n.get("value"):
            changed.append({
                "indicator_code": k[0], "breakdown_code": k[1],
                "period": k[2], "unit": k[3],
                "breakdown_label": n.get("breakdown_label", ""),
                "old_value": o.get("value"), "new_value": n.get("value"),
                "delta": (
                    None if o.get("value") is None or n.get("value") is None
                    else round(n["value"] - o["value"], 6)
                ),
            })
        if bool(o.get("is_preliminary")) != bool(n.get("is_preliminary")):
            flag_changes.append({
                "breakdown_code": k[1], "period": k[2],
                "old_is_preliminary": bool(o.get("is_preliminary")),
                "new_is_preliminary": bool(n.get("is_preliminary")),
            })

    changed.sort(key=lambda c: (c["period"], c["breakdown_code"]))
    return {
        "added": sorted(added, key=lambda r: (r["period"], r["breakdown_code"])),
        "removed": sorted(removed, key=lambda r: (r["period"], r["breakdown_code"])),
        "changed": changed,
        "preliminary_flag_changes": flag_changes,
    }


def diff_vintages(
    dataset_id: str, old_id: str, new_id: str, root: Path | None = None
) -> dict:
    """Diff two committed retrievals of the same dataset."""
    result = diff_rows(
        read_rows(dataset_id, old_id, root), read_rows(dataset_id, new_id, root)
    )
    old_meta = read_meta(dataset_id, old_id, root)
    new_meta = read_meta(dataset_id, new_id, root)
    result.update({
        "dataset_id": dataset_id,
        "old_vintage": old_id,
        "new_vintage": new_id,
        "bytes_identical": old_meta["sha256"] == new_meta["sha256"],
        "old_sha256": old_meta["sha256"],
        "new_sha256": new_meta["sha256"],
    })
    return result


def vintage_history(dataset_id: str, root: Path | None = None) -> list[dict]:
    """Chronological log with a diff against the preceding vintage."""
    ids = list_vintages(dataset_id, root)
    out = []
    for i, vid in enumerate(ids):
        meta = read_meta(dataset_id, vid, root)
        entry = dict(meta)
        entry["diff"] = (
            diff_vintages(dataset_id, ids[i - 1], vid, root) if i else None
        )
        out.append(entry)
    return list(reversed(out))


# --------------------------------------------------------------------------
# live refresh
# --------------------------------------------------------------------------

def refresh(dataset_id: str, root: Path | None = None) -> dict:
    """Fetch live, write a new vintage, diff it against the previous one.

    Network failure is a normal outcome here, not a crash: the committed
    vintages stay untouched and the caller gets a message it can show.
    """
    adapter = ADAPTERS.get(dataset_id)
    if adapter is None:
        return {"ok": False, "dataset_id": dataset_id, "error": "unknown dataset"}

    previous = latest_vintage(dataset_id, root)
    try:
        data, status = adapter.download()
    except Exception as exc:                      # noqa: BLE001 - reported to UI
        return {
            "ok": False, "dataset_id": dataset_id, "previous_vintage": previous,
            "error": f"network unavailable: {type(exc).__name__}: {exc}",
        }

    if status != 200 or not data:
        return {
            "ok": False, "dataset_id": dataset_id, "previous_vintage": previous,
            "error": (
                f"HTTP {status}, {len(data)} bytes. Geostat returns an empty "
                "body when the browser User-Agent header is missing."
            ),
        }

    digest = hashlib.sha256(data).hexdigest()
    if previous and read_meta(dataset_id, previous, root)["sha256"] == digest:
        return {
            "ok": True, "dataset_id": dataset_id, "previous_vintage": previous,
            "new_vintage": None, "unchanged": True,
            "message": (
                f"Bytes identical to vintage {previous} (sha256 {digest[:12]}). "
                "No new vintage written."
            ),
        }

    try:
        meta = write_vintage(adapter, data, status, root=root)
    except Exception as exc:                      # noqa: BLE001
        return {
            "ok": False, "dataset_id": dataset_id, "previous_vintage": previous,
            "error": f"could not write vintage: {exc}",
        }

    result = {
        "ok": True, "dataset_id": dataset_id, "previous_vintage": previous,
        "new_vintage": meta["vintage_id"], "unchanged": False, "meta": meta,
    }
    if previous:
        result["diff"] = diff_vintages(dataset_id, previous, meta["vintage_id"], root)
    return result


def copy_vintage_to(
    dataset_id: str, vintage_id: str, destination: Path, root: Path | None = None
) -> Path:
    """Copy a vintage into a scratch directory, writable.

    Used by the fault-injection lab so a corrupted copy can never be confused
    with, or written over, the committed original.
    """
    root = root or VINTAGE_ROOT
    src = root / dataset_id / vintage_id
    destination.mkdir(parents=True, exist_ok=True)
    dst = destination / dataset_id / vintage_id
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    # copytree preserves the source's mode, and the source is a committed
    # vintage: 0444 files, and on a read-only host a read-only directory too.
    # Thaw the directory before its contents - a 0555 copy cannot have anything
    # replaced inside it, so the next run's rmtree above dies on PermissionError.
    dst.chmod(0o755)
    for child in dst.iterdir():
        _thaw(child)
    return dst
