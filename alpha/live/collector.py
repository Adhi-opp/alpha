"""Session capture orchestration: connect, subscribe, watchdog, retarget.

Design contract (docs/LIVE_DESK.md):
- The recv loop ONLY decodes and enqueues — disk lives behind the queue.
- Static wide band (ATM +/- half_width at start), retarget ONLY when spot
  exits the inner core; every sub/unsub/retarget/reconnect is itself a
  recorded event so subscription churn has a measured cost, never a vibe.
- Dual timestamps everywhere: provider currentTs inside the event,
  t_local_ns stamped at enqueue.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import ssl
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import websockets

from alpha.config import IST, PROJECT_ROOT
from alpha.live import provider_upstox as up
from alpha.live.recorder import Recorder, pump

LIVE_ROOT = PROJECT_ROOT / "data" / "live"
WS_SILENT_TIMEOUT_S = 30          # feed silent longer than this -> reconnect
RETARGET_CHECK_S = 5.0
SESSION_END_IST = (15, 31)
SUB_CHUNK = 50                    # keys per subscribe frame
DEFAULT_QUEUE_MAX = 10_000


@dataclass
class SubscriptionChange:
    """A websocket subscription mutation, committed only after send()."""
    frame: bytes
    event: dict
    add: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    band_symbol: str | None = None
    new_band: list[float] | None = None


class SessionCapture:
    def __init__(self, token: str, symbols=("NIFTY", "SENSEX"),
                 half_width: int = 10, inner: int = 5,
                 minutes: float | None = None, keep_raw: bool = False,
                 label: str = "capture", out_root: Path | None = None,
                 queue_max: int = DEFAULT_QUEUE_MAX):
        self.token = token
        self.symbols = list(symbols)
        self.half_width = half_width
        self.inner = inner
        self.minutes = minutes
        self.keep_raw = keep_raw
        root = out_root or LIVE_ROOT
        day = datetime.now(IST).strftime("%Y-%m-%d")
        self.label = label
        self.run_id = (datetime.now(IST).strftime("%H%M%S_%f") + "_"
                       + uuid.uuid4().hex[:8])
        # Never reuse a label directory: a second probe must not overwrite
        # the first probe's manifest or hide its compressed segments.
        self.dir = root / day / f"{label}_{self.run_id}"
        if queue_max <= 0:
            raise ValueError("queue_max must be positive")
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=queue_max)
        self.queue_max = queue_max
        self.recorder = Recorder(self.dir, keep_raw=keep_raw)
        self.chains: dict[str, up.Chain] = {}
        self.bands: dict[str, list[float]] = {}
        self.spots: dict[str, float] = {}
        self._index_to_symbol: dict[str, str] = {}
        self._keys: list[str] | None = None
        self._active_keys: set[str] = set()
        self._master_sha256: str | None = None
        self._queue_high_water = 0
        self._queue_overflows = 0
        self._degraded_reason: str | None = None
        self._t_start = time.time()
        self._stop = False

    # ---- setup -----------------------------------------------------------
    def resolve(self, master: list[dict] | None = None) -> list[str]:
        """Resolve chains + REST spots + initial bands; return the full
        subscription key list."""
        master = master or up.load_master(
            cache_path=LIVE_ROOT / "_master_cache.csv.gz")
        self._master_sha256 = hashlib.sha256(
            json.dumps(master, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        keys: list[str] = []
        index_keys = [up.INDEX_KEYS[s] for s in self.symbols]
        spots = up.rest_ltp(index_keys, self.token)
        for sym in self.symbols:
            chain = up.front_week_chain(master, sym)
            spot = None
            for k, v in spots.items():
                if k == chain.index_key or sym.upper() in str(k).upper():
                    spot = v
            if spot is None:
                raise RuntimeError(
                    f"REST LTP gave no spot for {sym}: {spots}")
            band = up.select_band(chain.strikes, float(spot), self.half_width)
            self.chains[sym] = chain
            self.bands[sym] = band
            self.spots[sym] = float(spot)
            self._index_to_symbol[chain.index_key] = sym
            keys += [chain.index_key]
            if chain.future_key:
                keys.append(chain.future_key)
            keys += chain.band_keys(band)
        self._keys = list(dict.fromkeys(keys))
        self._active_keys = set(self._keys)
        return self._keys

    # ---- event plumbing ---------------------------------------------------
    def _enqueue_batch(self, events: list[dict], raw: bytes | None = None,
                       receipt_ns: int | None = None) -> bool:
        """Queue one received websocket frame as one recording unit.

        A provider packet can decode into many instrument events. Its raw
        payload must be retained once and every derived event must share the
        exact receipt timestamp; otherwise byte-rate and lag measurements are
        fiction. A full queue stops the capture explicitly rather than silently
        dropping an unknown portion of the session.
        """
        receipt_ns = receipt_ns if receipt_ns is not None else time.time_ns()
        for event in events:
            event["t_local_ns"] = receipt_ns
        raws = [(receipt_ns, raw)] if raw is not None else []
        try:
            self.queue.put_nowait((events, raws))
        except asyncio.QueueFull:
            self._queue_overflows += 1
            self._degraded_reason = "recorder queue full; capture halted"
            self._stop = True
            return False
        self._queue_high_water = max(self._queue_high_water, self.queue.qsize())
        return True

    def _enqueue(self, event: dict) -> bool:
        return self._enqueue_batch([event])

    def _note(self, kind: str, **payload) -> bool:
        return self._enqueue({"kind": kind, **payload})

    def _subscription_keys(self) -> list[str]:
        return sorted(self._active_keys)

    # ---- retargeting -------------------------------------------------------
    def _retarget_frames(self) -> list[SubscriptionChange]:
        """If any symbol's spot left its band core, build the unsub/sub
        frames and the bookkeeping events (sent by the caller)."""
        out: list[SubscriptionChange] = []
        for sym in self.symbols:
            band, spot = self.bands.get(sym), self.spots.get(sym)
            chain = self.chains.get(sym)
            if not band or spot is None or chain is None:
                continue
            if not up.needs_retarget(band, spot, self.inner):
                continue
            new_band = up.select_band(chain.strikes, spot, self.half_width)
            drop = chain.band_keys([k for k in band if k not in new_band])
            add = chain.band_keys([k for k in new_band if k not in band])
            if drop:
                out.append(SubscriptionChange(
                    up.build_frame("unsub", drop),
                    {"kind": "unsub", "symbol": sym, "keys": drop,
                     "reason": "retarget"},
                    remove=drop,
                    band_symbol=sym if not add else None,
                    new_band=new_band if not add else None))
            if add:
                out.append(SubscriptionChange(
                    up.build_frame("sub", add),
                    {"kind": "sub", "symbol": sym, "keys": add,
                     "reason": "retarget", "spot": spot},
                    add=add, band_symbol=sym, new_band=new_band))
            if not drop and not add:
                self.bands[sym] = new_band
                self._note("retarget_noop", symbol=sym, spot=spot,
                           band=new_band)
        return out

    def _apply_subscription_change(self, change: SubscriptionChange) -> None:
        self._active_keys.difference_update(change.remove)
        self._active_keys.update(change.add)
        if change.band_symbol is not None and change.new_band is not None:
            self.bands[change.band_symbol] = change.new_band

    def _instrument_map(self) -> dict[str, dict]:
        mapping: dict[str, dict] = {}
        for sym, chain in self.chains.items():
            mapping[chain.index_key] = {"symbol": sym, "kind": "index"}
            if chain.future_key:
                mapping[chain.future_key] = {
                    "symbol": sym, "kind": "future", "expiry": chain.expiry,
                }
            for (strike, side), key in chain.options.items():
                mapping[key] = {
                    "symbol": sym, "kind": "option", "expiry": chain.expiry,
                    "strike": strike, "side": side,
                }
        return mapping

    # ---- main loop ---------------------------------------------------------
    def _should_stop(self) -> bool:
        if self._stop:
            return True
        if self.minutes is not None:
            return (time.time() - self._t_start) >= self.minutes * 60
        now = datetime.now(IST)
        return (now.hour, now.minute) >= SESSION_END_IST

    async def _ws_loop(self):
        ssl_ctx = ssl.create_default_context()
        attempts = 0
        while not self._should_stop():
            try:
                async with websockets.connect(
                    up.WS_URL, ssl=ssl_ctx,
                    additional_headers={
                        "Authorization": f"Bearer {self.token}",
                        "Accept": "*/*"},
                ) as ws:
                    attempts += 1
                    await asyncio.sleep(1)
                    keys = self._subscription_keys()
                    self._note("ws_connected", attempt=attempts,
                               n_active_keys=len(keys))
                    for i in range(0, len(keys), SUB_CHUNK):
                        chunk = keys[i:i + SUB_CHUNK]
                        await ws.send(up.build_frame("sub", chunk))
                        self._note("sub", keys=chunk,
                                   reason="initial" if attempts == 1 else "reconnect")
                    last_retarget_check = time.time()
                    while not self._should_stop():
                        try:
                            raw = await asyncio.wait_for(
                                ws.recv(), timeout=WS_SILENT_TIMEOUT_S)
                        except asyncio.TimeoutError:
                            self._note("ws_silent",
                                       timeout_s=WS_SILENT_TIMEOUT_S)
                            break                       # reconnect
                        if isinstance(raw, str):
                            self._note("ws_text", text=raw[:2000])
                            continue
                        receipt_ns = time.time_ns()
                        events = up.decode(raw)
                        for ev in events:
                            if ev["kind"] == "index":
                                sym = self._index_to_symbol.get(ev["key"])
                                if sym:
                                    self.spots[sym] = ev["ltp"]
                        if not self._enqueue_batch(
                                events, raw if self.keep_raw else None, receipt_ns):
                            break
                        if time.time() - last_retarget_check >= RETARGET_CHECK_S:
                            last_retarget_check = time.time()
                            for change in self._retarget_frames():
                                t0 = time.time_ns()
                                await ws.send(change.frame)
                                change.event["send_elapsed_ns"] = time.time_ns() - t0
                                self._apply_subscription_change(change)
                                self._enqueue(change.event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._note("ws_error", error=f"{type(exc).__name__}: {exc}")
                await asyncio.sleep(5)

    async def run(self) -> dict:
        keys = self._keys or self.resolve()
        self._note("session_start", symbols=self.symbols,
                   chains={s: {"expiry": c.expiry,
                               "future_key": c.future_key,
                               "n_strikes": len(c.strikes)}
                           for s, c in self.chains.items()},
                   bands={s: b for s, b in self.bands.items()},
                   spots=self.spots, n_keys=len(keys),
                   half_width=self.half_width, keep_raw=self.keep_raw)
        pump_task = asyncio.create_task(pump(self.queue, self.recorder))
        try:
            await self._ws_loop()
        finally:
            await self.queue.put(None)
            await pump_task
            end = {"kind": "session_end", "t_local_ns": time.time_ns(),
                   "degraded_reason": self._degraded_reason}
            await asyncio.to_thread(self.recorder.write_batch, [end], [])
            metadata = {
                "label": self.label, "run_id": self.run_id,
                "queue_max": self.queue_max,
                "queue_high_water": self._queue_high_water,
                "queue_overflows": self._queue_overflows,
                "degraded_reason": self._degraded_reason,
                "master_sha256": self._master_sha256,
                "active_keys_at_close": len(self._active_keys),
            }
            manifest = await asyncio.to_thread(self.recorder.close, metadata)
            session = {
                "symbols": self.symbols,
                "chains": {s: {"expiry": c.expiry, "index_key": c.index_key,
                               "future_key": c.future_key}
                           for s, c in self.chains.items()},
                "n_keys_initial": len(keys),
                "instrument_map": self._instrument_map(),
                "master_sha256": self._master_sha256,
                "manifest": metadata,
            }
            tmp = self.dir / "session.json.tmp"
            tmp.write_text(json.dumps(session, indent=2), encoding="utf-8")
            tmp.replace(self.dir / "session.json")
        return manifest

    def stop(self):
        self._stop = True
