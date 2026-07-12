"""Replay a recorded session — the proof layer.

Any number the cockpit ever shows must be recomputable offline from the
session directory alone; this module is how. Events come back in recorded
order with both timestamps intact.
"""
from __future__ import annotations

import gzip
import json
import struct
from pathlib import Path
from typing import Iterator

_FRAME = struct.Struct("<qI")


def manifest(session_dir: Path) -> dict:
    return json.loads((Path(session_dir) / "manifest.json").read_text())


def events(session_dir: Path) -> Iterator[dict]:
    """Yield every recorded event in order (works on both open .jsonl and
    closed .jsonl.gz segments)."""
    d = Path(session_dir)
    names = (manifest(d)["segments"] if (d / "manifest.json").exists()
             else sorted(p.name for p in d.glob("events_*.jsonl*")))
    for name in names:
        p = d / name
        opener = gzip.open if p.suffix == ".gz" else open
        with opener(p, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)


def raw_frames(session_dir: Path) -> Iterator[tuple[int, bytes]]:
    """Yield (t_local_ns, payload) from the framed raw capture files."""
    d = Path(session_dir)
    for p in sorted(d.glob("raw_*.bin")):
        with open(p, "rb") as fh:
            while True:
                head = fh.read(_FRAME.size)
                if len(head) < _FRAME.size:
                    break
                t_ns, length = _FRAME.unpack(head)
                payload = fh.read(length)
                if len(payload) < length:
                    break
                yield t_ns, payload
