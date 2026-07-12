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
import json
import ssl
import time
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


class SessionCapture:
    def __init__(self, token: str, symbols=("NIFTY", "SENSEX"),
                 half_width: int = 10, inner: int = 5,
                 minutes: float | None = None, keep_raw: bool = False,
                 label: str = "capture", out_root: Path | None = None):
        self.token = token
        self.symbols = list(symbols)
        self.half_width = half_width
        self.inner = inner
        self.minutes = minutes
        self.keep_raw = keep_raw
        root = out_root or LIVE_ROOT
        day = datetime.now(IST).strftime("%Y-%m-%d")
        self.dir = root / day / label
        self.queue: asyncio.Queue = asyncio.Queue()
        self.recorder = Recorder(self.dir, keep_raw=keep_raw)
        self.chains: dict[str, up.Chain] = {}
        self.bands: dict[str, list[float]] = {}
        self.spots: dict[str, float] = {}
        self._index_to_symbol: dict[str, str] = {}
        self._keys: list[str] | None = None
        self._t_start = time.time()
        self._stop = False

    # ---- setup -----------------------------------------------------------
    def resolve(self, master: list[dict] | None = None) -> list[str]:
        """Resolve chains + REST spots + initial bands; return the full
        subscription key list."""
        master = master or up.load_master(
            cache_path=LIVE_ROOT / "_master_cache.csv.gz")
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
        return self._keys

    # ---- event plumbing ---------------------------------------------------
    def _enqueue(self, event: dict, raw: bytes | None = None):
        event["t_local_ns"] = time.time_ns()
        raws = [(event["t_local_ns"], raw)] if raw is not None else None
        self.queue.put_nowait((event, raws))

    def _note(self, kind: str, **payload):
        self._enqueue({"kind": kind, **payload})

    # ---- retargeting -------------------------------------------------------
    def _retarget_frames(self) -> list[tuple[bytes, dict]]:
        """If any symbol's spot left its band core, build the unsub/sub
        frames and the bookkeeping events (sent by the caller)."""
        out = []
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
            self.bands[sym] = new_band
            if drop:
                out.append((up.build_frame("unsub", drop),
                            {"kind": "unsub", "symbol": sym, "keys": drop}))
            if add:
                out.append((up.build_frame("sub", add),
                            {"kind": "sub", "symbol": sym, "keys": add,
                             "reason": "retarget", "spot": spot}))
        return out

    # ---- main loop ---------------------------------------------------------
    def _should_stop(self) -> bool:
        if self._stop:
            return True
        if self.minutes is not None:
            return (time.time() - self._t_start) >= self.minutes * 60
        now = datetime.now(IST)
        return (now.hour, now.minute) >= SESSION_END_IST

    async def _ws_loop(self, keys: list[str]):
        ssl_ctx = ssl.create_default_context()
        while not self._should_stop():
            try:
                async with websockets.connect(
                    up.WS_URL, ssl=ssl_ctx,
                    additional_headers={
                        "Authorization": f"Bearer {self.token}"},
                ) as ws:
                    await asyncio.sleep(1)
                    for i in range(0, len(keys), SUB_CHUNK):
                        chunk = keys[i:i + SUB_CHUNK]
                        await ws.send(up.build_frame("sub", chunk))
                        self._note("sub", keys=chunk, reason="initial")
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
                        for ev in up.decode(raw):
                            if ev["kind"] == "index":
                                sym = self._index_to_symbol.get(ev["key"])
                                if sym:
                                    self.spots[sym] = ev["ltp"]
                            self._enqueue(
                                ev, raw if self.keep_raw else None)
                        if time.time() - last_retarget_check >= RETARGET_CHECK_S:
                            last_retarget_check = time.time()
                            for frame, ev in self._retarget_frames():
                                t0 = time.time_ns()
                                await ws.send(frame)
                                ev["send_ns"] = time.time_ns() - t0
                                self._enqueue(ev)
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
            await self._ws_loop(keys)
        finally:
            self._note("session_end")
            await self.queue.put(None)
            await pump_task
            manifest = await asyncio.to_thread(self.recorder.close)
            (self.dir / "session.json").write_text(json.dumps({
                "symbols": self.symbols,
                "chains": {s: {"expiry": c.expiry, "index_key": c.index_key,
                               "future_key": c.future_key}
                           for s, c in self.chains.items()},
                "n_keys": len(keys)}, indent=2))
        return manifest

    def stop(self):
        self._stop = True
