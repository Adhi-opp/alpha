"""Pre-registration freeze + hash guard.

A hypothesis's GO/NO-GO criteria must be fixed BEFORE results are seen. This
module extracts the pre-registration section of a ledger file, hashes it, and
records the hash in a sidecar. The study runner calls `assert_frozen` before
computing anything; if the pre-reg text has changed since the freeze, results
are refused. Editing criteria after seeing results is the cardinal sin this
prevents.

The hash lives in a sidecar (`ledger/.freezes/<stem>.json`), never inside the
hashed section, so freezing can't alter what it measures.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SECTION_HEADING = "## Pre-registration"
FREEZE_DIR_NAME = ".freezes"


class PreRegError(RuntimeError):
    pass


def extract_section(text: str) -> str:
    """Return the pre-registration section: from its heading to the next
    level-2 heading (exclusive)."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(SECTION_HEADING):
            start = i
            break
    if start is None:
        raise PreRegError(f"no '{SECTION_HEADING}' section found")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^##\s", lines[j]):
            end = j
            break
    return "\n".join(lines[start:end])


def _normalize(section: str) -> str:
    # ignore trailing whitespace and blank-line noise so cosmetic edits don't
    # trip the guard, but any change to the actual criteria does
    return "\n".join(l.rstrip() for l in section.strip().splitlines())


def section_hash(text: str) -> str:
    return hashlib.sha256(_normalize(extract_section(text)).encode()).hexdigest()


def _freeze_path(ledger_path: Path) -> Path:
    return ledger_path.parent / FREEZE_DIR_NAME / f"{ledger_path.stem}.json"


def freeze(ledger_path: Path | str) -> dict:
    """Record the pre-reg hash. Refuses to re-freeze a changed section."""
    ledger_path = Path(ledger_path)
    text = ledger_path.read_text(encoding="utf-8")
    digest = section_hash(text)
    fp = _freeze_path(ledger_path)
    if fp.exists():
        prior = json.loads(fp.read_text())
        if prior["hash"] != digest:
            raise PreRegError(
                f"{ledger_path.name} already frozen with a DIFFERENT pre-reg. "
                f"Freezing again after editing criteria is forbidden — register "
                f"a successor hypothesis instead."
            )
        return prior
    fp.parent.mkdir(parents=True, exist_ok=True)
    record = {"hash": digest, "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
              "ledger": ledger_path.name}
    fp.write_text(json.dumps(record, indent=2))
    return record


def is_frozen(ledger_path: Path | str) -> bool:
    return _freeze_path(Path(ledger_path)).exists()


def assert_frozen(ledger_path: Path | str) -> None:
    """Guard the study runner calls before computing results."""
    ledger_path = Path(ledger_path)
    fp = _freeze_path(ledger_path)
    if not fp.exists():
        raise PreRegError(
            f"{ledger_path.name} is not pre-registered — freeze the "
            f"pre-registration before any result may be computed."
        )
    stored = json.loads(fp.read_text())["hash"]
    current = section_hash(ledger_path.read_text(encoding="utf-8"))
    if stored != current:
        raise PreRegError(
            f"{ledger_path.name} pre-registration changed after freeze "
            f"(hash mismatch). Results are invalid; the criteria were edited "
            f"after the fact."
        )
