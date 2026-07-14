"""Append-only session recorder — the ingestion/disk firewall.

The websocket recv loop must never touch disk (review-flagged trap: blocking
I/O in the recv loop poisons local timestamps). So: the collector decodes
and enqueues; `pump()` drains the queue and hands batches to a Recorder,
whose flushes run in a worker thread via asyncio.to_thread.

Layout per session (data/live/<YYYY-MM-DD>/<label>/):
  events_NNNN.jsonl     rotated plain JSONL (crash-safe: appended lines
                        survive a kill; gzipped only at close)
  raw_NNNN.bin          optional framed raw ws payloads:
                        <int64 t_local_ns><uint32 len><payload>
  manifest.json         written at close: counts, spans, segment list

Every event gets t_local_ns stamped AT ENQUEUE TIME by the collector —
provider currentTs rides inside the event, so clock skew is measurable.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import os
import struct
from pathlib import Path

ROTATE_EVENTS = 100_000
_FRAME = struct.Struct("<qI")


class Recorder:
    def __init__(self, session_dir: Path, keep_raw: bool = False,
                 rotate_events: int = ROTATE_EVENTS,
                 compress_on_close: bool = True):
        self.dir = Path(session_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.keep_raw = keep_raw
        self.rotate_events = rotate_events
        self.compress_on_close = compress_on_close
        self._seg = 0
        self._seg_events = 0
        self._fh = None
        self._raw_fh = None
        self.n_events = 0
        self.n_raw = 0
        self.t_first_ns: int | None = None
        self.t_last_ns: int | None = None
        self._closed = False

    # ---- segment plumbing ----------------------------------------------
    def _open_next(self):
        if self._fh:
            self._fh.close()
        if self._raw_fh:
            self._raw_fh.close()
            self._raw_fh = None
        self._seg += 1
        self._seg_events = 0
        self._fh = open(self.dir / f"events_{self._seg:04d}.jsonl",
                        "a", encoding="utf-8")
        if self.keep_raw:
            self._raw_fh = open(self.dir / f"raw_{self._seg:04d}.bin", "ab")

    def write_batch(self, events: list[dict],
                    raws: list[tuple[int, bytes]] | None = None):
        """Synchronous batch write — call from a worker thread, not the
        event loop."""
        if self._closed:
            raise RuntimeError("recorder is closed")
        if self._fh is None or self._seg_events >= self.rotate_events:
            self._open_next()
        for ev in events:
            self._fh.write(json.dumps(ev, separators=(",", ":")) + "\n")
            t = ev.get("t_local_ns")
            if t is not None:
                if self.t_first_ns is None:
                    self.t_first_ns = t
                self.t_last_ns = t
        self._fh.flush()
        self.n_events += len(events)
        self._seg_events += len(events)
        if raws and self._raw_fh is not None:
            for t_ns, payload in raws:
                self._raw_fh.write(_FRAME.pack(t_ns, len(payload)))
                self._raw_fh.write(payload)
            self._raw_fh.flush()
            self.n_raw += len(raws)

    def close(self, metadata: dict | None = None) -> dict:
        if self._closed:
            return json.loads((self.dir / "manifest.json").read_text())
        self._closed = True
        if self._fh:
            self._fh.close()
        if self._raw_fh:
            self._raw_fh.close()
        segments = sorted(p.name for p in self.dir.glob("events_*.jsonl"))
        if self.compress_on_close:
            gz_segments = []
            for name in segments:
                p = self.dir / name
                with open(p, "rb") as src, gzip.open(f"{p}.gz", "wb") as dst:
                    dst.write(src.read())
                p.unlink()
                gz_segments.append(f"{name}.gz")
            segments = gz_segments
        manifest = {
            "n_events": self.n_events, "n_raw": self.n_raw,
            "t_first_ns": self.t_first_ns, "t_last_ns": self.t_last_ns,
            "segments": segments,
            "raw_segments": sorted(p.name for p in self.dir.glob("raw_*.bin")),
        }
        if metadata:
            manifest["metadata"] = metadata
        # A half-written manifest must never make a complete capture
        # unreplayable. Event segments remain append-only; publish their index
        # atomically only after all close-time work is complete.
        target = self.dir / "manifest.json"
        tmp = self.dir / "manifest.json.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(manifest, indent=2))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        return manifest


async def pump(queue: asyncio.Queue, recorder: Recorder,
               batch_max: int = 500) -> None:
    """Drain the queue into the recorder in batches. A `None` item is the
    shutdown sentinel. Disk writes run in a thread so this task never
    blocks the loop for the recv coroutine."""
    pending = None
    while True:
        item = pending if pending is not None else await queue.get()
        pending = None
        if item is None:
            return
        events, raws = list(item[0]), list(item[1])
        stopping = False
        while len(events) < batch_max:
            try:
                nxt = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if nxt is None:
                stopping = True
                break
            next_events, next_raws = nxt
            # Preserve one raw frame per websocket message. Do not split a
            # decoded message merely to hit an arbitrary write-batch size.
            if events and len(events) + len(next_events) > batch_max:
                pending = nxt
                break
            events.extend(next_events)
            raws.extend(next_raws)
        await asyncio.to_thread(recorder.write_batch, events, raws)
        if stopping:
            return
