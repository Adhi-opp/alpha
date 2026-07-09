"""Immutable raw-file archive with JSON manifests.

Rules (docs/ARCHITECTURE.md §1):
- raw files are stored exactly as fetched and never modified;
- every file gets a sibling <name>.manifest.json (url, fetched_at, sha256);
- refetching identical bytes is a no-op; different bytes for the same
  logical file are stored alongside as .revN — never overwritten.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from alpha.config import RAW_ROOT


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def manifest_path(path: Path) -> Path:
    return path.with_name(path.name + ".manifest.json")


def store(
    source: str,
    relpath: str,
    content: bytes,
    url: str,
    meta: dict | None = None,
    root: Path | None = None,
) -> Path:
    """Archive content under <root>/<source>/<relpath>; return the final path.

    Identical bytes already archived -> existing path (no-op).
    Different bytes for the same relpath -> stored as <name>.revN alongside;
    the manifest records what it supersedes. The caller decides what a
    conflicting refetch means (usually: exchange revised the file).
    """
    root = root or RAW_ROOT
    target = root / source / relpath
    target.parent.mkdir(parents=True, exist_ok=True)

    digest = _sha256(content)
    candidate = target
    rev = 0
    while candidate.exists():
        mpath = manifest_path(candidate)
        if mpath.exists():
            if json.loads(mpath.read_text()).get("sha256") == digest:
                return candidate
        elif candidate.read_bytes() == content:
            return candidate
        rev += 1
        candidate = target.with_name(f"{target.name}.rev{rev}")

    candidate.write_bytes(content)
    manifest = {
        "url": url,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": digest,
        "size": len(content),
        "supersedes": target.name if rev else None,
        **(meta or {}),
    }
    manifest_path(candidate).write_text(json.dumps(manifest, indent=2))
    return candidate


def is_archived(source: str, relpath: str, root: Path | None = None) -> bool:
    root = root or RAW_ROOT
    return (root / source / relpath).exists()


def path_of(source: str, relpath: str, root: Path | None = None) -> Path:
    root = root or RAW_ROOT
    return root / source / relpath
