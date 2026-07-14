r"""THE PROBE GATE (docs/LIVE_DESK.md): one market-hours run before any
cockpit or feature code gets built. Grades itself honestly:

  GREEN    infra AND live market behavior verified (live_feed streaming,
           fresh trades, drill latency measured, clean recorder)
  PARTIAL  infra fine but the market was closed / no live stream — a valid
           after-hours test, NOT a green gate (probe #1 was this)
  RED      errors, degraded capture, or gate-relevant failures

Preflights BEFORE any capture:
  - clock: |local - provider currentTs| must be <= 5 s, else CLOCK_INVALID,
    exit 3, and NO market-rate statistics are published (a wrong local
    clock poisons every receipt timestamp — measured lesson, 2026-07-14).
  - market state: NSE_FO + BSE_FO segment status is recorded; a closed
    market cannot produce GREEN.

Token: the one-year read-only Analytics Token (UPSTOX_ANALYTICS_TOKEN) is
preferred automatically; the daily OAuth token is a fallback only. There is
no daily-login requirement.

  d:\alpha\.venv\Scripts\python scripts\live_probe.py --minutes 10

Everything is recorded raw (keep_raw=True); the summary is recomputed from
the recording via replay, so the probe proves the capture-replay loop too.
Findings go to docs/UPSTOX_FINDINGS.md AFTER this runs — from output, not
from guesses.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha.live import provider_upstox as up
from alpha.live import replay
from alpha.live.auth import load_upstox_token
from alpha.live.collector import SessionCapture, SubscriptionChange

MAX_CLOCK_SKEW_S = 5.0
DRILL_AFTER_S = 120.0     # unsub 2 wing strikes after this long
DRILL_RESUB_S = 15.0      # resubscribe them this much later
DRILL_RETRY_S = 2.0       # no live socket (reconnecting): retry cadence
FRESH_TRADE_MAX_AGE_S = 120.0


class ProbeCapture(SessionCapture):
    """SessionCapture plus a retarget drill on an INDEPENDENT timer.

    The drill must not depend on incoming ticks (a snapshot-only feed
    starves any tick-driven hook — measured failure, probe #1) and must
    survive reconnects: send_change() returns False when no socket is up
    and the loop simply retries until one is.
    """

    def __init__(self, *a, drill_after_s: float = DRILL_AFTER_S,
                 drill_resub_s: float = DRILL_RESUB_S,
                 drill_retry_s: float = DRILL_RETRY_S, **k):
        super().__init__(*a, **k)
        self.drill_after_s = drill_after_s
        self.drill_resub_s = drill_resub_s
        self.drill_retry_s = drill_retry_s

    def _drill_change(self, method: str, keys: list[str]) -> SubscriptionChange:
        kind = "drill_unsub" if method == "unsub" else "drill_resub"
        return SubscriptionChange(
            up.build_frame(method, keys), {"kind": kind, "keys": keys},
            add=keys if method == "sub" else [],
            remove=keys if method == "unsub" else [])

    async def _send_until_delivered(self, change: SubscriptionChange) -> None:
        while not self._stop:
            if await self.send_change(change):
                return
            await asyncio.sleep(self.drill_retry_s)

    async def _drill_loop(self) -> None:
        await asyncio.sleep(self.drill_after_s)
        sym = self.symbols[0]
        chain, band = self.chains.get(sym), self.bands.get(sym)
        if not chain or not band or len(band) < 5:
            self._note("drill_skipped", reason="band too small")
            return
        keys = chain.band_keys(band[-2:])
        await self._send_until_delivered(self._drill_change("unsub", keys))
        await asyncio.sleep(self.drill_resub_s)
        await self._send_until_delivered(self._drill_change("sub", keys))

    async def run(self) -> dict:
        drill = asyncio.create_task(self._drill_loop())
        try:
            return await super().run()
        finally:
            drill.cancel()
            try:
                await drill
            except (asyncio.CancelledError, Exception):
                pass


def summarize(session_dir: Path) -> dict:
    counts: dict[str, int] = {}
    field_hits = {"iv": 0, "gamma": 0, "depth5": 0, "oi": 0, "tbq": 0,
                  "atp": 0}
    n_ticks = 0
    initial_feed = live_feed = 0
    skew_ms: list[float] = []
    t0 = t1 = None
    freshest_trade_age_s = None
    per_key_ticks: dict[str, int] = {}
    segments: dict[str, str] = {}
    drill = {"unsub_ns": None, "resub_ns": None, "first_tick_after_ns": None}
    errors: list[str] = []
    for ev in replay.events(session_dir):
        k = ev["kind"]
        counts[k] = counts.get(k, 0) + 1
        t = ev.get("t_local_ns")
        if t is not None:
            t0 = t if t0 is None else t0
            t1 = t
        if k in ("tick", "index", "ltpc"):
            ft = ev.get("feed_type")
            if ft == "initial_feed":
                initial_feed += 1
            elif ft == "live_feed":
                live_feed += 1
            if ev.get("ltt") and t:
                age = t / 1e9 - ev["ltt"] / 1e3
                if freshest_trade_age_s is None or age < freshest_trade_age_s:
                    freshest_trade_age_s = age
        if k == "tick":
            n_ticks += 1
            per_key_ticks[ev["key"]] = per_key_ticks.get(ev["key"], 0) + 1
            for f, hit in (("iv", ev.get("iv")),
                           ("gamma", ev.get("greeks", {}).get("gamma")),
                           ("depth5", len(ev.get("depth", [])) >= 5),
                           ("oi", ev.get("oi")), ("tbq", ev.get("tbq")),
                           ("atp", ev.get("atp"))):
                if hit:
                    field_hits[f] += 1
            if ev.get("provider_ts") and t:
                skew_ms.append(t / 1e6 - ev["provider_ts"])
        elif k == "market_info":
            segments = dict(ev.get("segments", {}))
        elif k == "drill_unsub":
            drill["unsub_ns"] = t
        elif k == "drill_resub":
            drill["resub_ns"] = t
            drill["keys"] = ev.get("keys", [])
        elif k in ("ws_error", "ws_text"):
            errors.append(json.dumps(ev)[:300])
    if drill.get("resub_ns"):
        for ev in replay.events(session_dir):
            if (ev["kind"] == "tick" and ev["key"] in drill.get("keys", [])
                    and ev["t_local_ns"] > drill["resub_ns"]):
                drill["first_tick_after_ns"] = ev["t_local_ns"]
                break
    span_s = ((t1 - t0) / 1e9) if (t0 and t1 and t1 > t0) else float("nan")
    raw_bytes = sum(p.stat().st_size for p in Path(session_dir).glob("raw_*.bin"))
    manifest = replay.manifest(session_dir)
    meta = manifest.get("metadata", {})
    return {
        "counts": counts,
        "span_s": round(span_s, 1),
        "ticks_per_s": round(n_ticks / span_s, 1) if span_s > 0 else None,
        "raw_bytes": raw_bytes,
        "raw_bytes_per_s": round(raw_bytes / span_s) if span_s > 0 else None,
        "initial_feed_count": initial_feed,
        "live_feed_count": live_feed,
        "reconnect_count": max(0, counts.get("ws_connected", 0) - 1),
        "segment_statuses": segments,
        "freshest_trade_age_s": (round(freshest_trade_age_s, 1)
                                 if freshest_trade_age_s is not None else None),
        "field_presence_pct": {f: round(100 * v / n_ticks, 1) if n_ticks else 0
                               for f, v in field_hits.items()},
        "n_instruments_seen": len(per_key_ticks),
        "quietest_instruments": sorted(per_key_ticks.items(),
                                       key=lambda kv: kv[1])[:5],
        "tick_skew_ms": ({"median": round(statistics.median(skew_ms), 1),
                          "p95": round(sorted(skew_ms)[int(0.95 * len(skew_ms))], 1)}
                         if skew_ms else None),
        "drill_resub_to_first_tick_ms": (
            round((drill["first_tick_after_ns"] - drill["resub_ns"]) / 1e6, 1)
            if drill.get("first_tick_after_ns") and drill.get("resub_ns")
            else None),
        "degraded_reason": meta.get("degraded_reason"),
        "queue_high_water": meta.get("queue_high_water"),
        "queue_max": meta.get("queue_max"),
        "errors": errors[:10],
    }


def evaluate_gate(summary: dict, preflight_skew_s: float) -> tuple[str, list[str]]:
    """GREEN / PARTIAL / RED per the pre-declared rules. PARTIAL = every
    infra check passed but live market behavior was unobservable (closed
    market / no live_feed) — a valid infra test, never a green gate."""
    failures: list[str] = []
    if abs(preflight_skew_s) > MAX_CLOCK_SKEW_S:
        failures.append(f"CLOCK_INVALID: |skew| {abs(preflight_skew_s):.1f}s "
                        f"> {MAX_CLOCK_SKEW_S:.0f}s")
    if summary.get("degraded_reason"):
        failures.append(f"degraded: {summary['degraded_reason']}")
    if summary.get("errors"):
        failures.append(f"{len(summary['errors'])} ws errors/text frames")
    if failures:
        return "RED", failures

    partial: list[str] = []
    seg = summary.get("segment_statuses", {})
    closed = [s for s in up.GATE_SEGMENTS if seg.get(s) != up.OPEN_STATUS]
    if closed:
        partial.append(f"market closed: {closed}")
    if not summary.get("live_feed_count"):
        partial.append("zero live_feed messages (snapshots only)")
    fresh = summary.get("freshest_trade_age_s")
    if fresh is None or fresh > FRESH_TRADE_MAX_AGE_S:
        partial.append(f"no fresh trades (freshest ltt age {fresh}s)")
    if summary.get("drill_resub_to_first_tick_ms") is None:
        partial.append("drill latency unmeasured")
    return ("GREEN", []) if not partial else ("PARTIAL", partial)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--half-width", type=int, default=10)
    args = ap.parse_args()

    try:
        token, source = load_upstox_token()
    except RuntimeError as exc:
        print(str(exc))
        return 5
    print(f"token source: {source} "
          f"({'one-year analytics' if source == 'analytics' else 'daily OAuth fallback'})")

    # ---- preflight 1: clock (a wrong clock voids every measurement) ------
    pre = await up.preflight(token)
    print(f"preflight: provider-vs-local skew {pre['skew_s']:+.2f}s; "
          f"segments {pre['segments']}")
    if abs(pre["skew_s"]) > MAX_CLOCK_SKEW_S:
        print(f"\nCLOCK_INVALID: |{pre['skew_s']:.1f}s| > {MAX_CLOCK_SKEW_S:.0f}s "
              f"— local clock and provider disagree. Fix the system clock "
              f"(Settings -> set time automatically -> sync) and re-run. "
              f"No market statistics were computed.")
        return 3

    # ---- preflight 2: REST sanity ----------------------------------------
    try:
        spots = up.rest_ltp(list(up.INDEX_KEYS.values()), token)
    except Exception as exc:
        print(f"REST LTP failed ({type(exc).__name__}) — token invalid or "
              f"connectivity down.")
        return 4
    print(f"REST spots: {spots}")
    if not pre["gate_segments_open"]:
        print("NOTE: provider reports the gate segments CLOSED — this run "
              "can verify infrastructure only (gate will be PARTIAL).")

    cap = ProbeCapture(token, symbols=("NIFTY", "SENSEX"),
                       half_width=args.half_width, minutes=args.minutes,
                       keep_raw=True, label="probe")
    keys = cap.resolve()
    for sym, chain in cap.chains.items():
        print(f"{sym}: front-week {chain.expiry}, {len(chain.strikes)} strikes, "
              f"band {cap.bands[sym][0]:.0f}..{cap.bands[sym][-1]:.0f}, "
              f"future {chain.future_key}")
    print(f"subscribing {len(keys)} keys in full mode; capturing "
          f"{args.minutes:.0f} min -> {cap.dir}\n")

    manifest = await cap.run()
    print(f"capture done: {manifest['n_events']:,} events, "
          f"{manifest['n_raw']:,} raw frames\n")

    summary = summarize(cap.dir)
    gate_status, gate_failures = evaluate_gate(summary, pre["skew_s"])
    summary["gate_status"] = gate_status
    summary["gate_failures"] = gate_failures
    summary["preflight_skew_s"] = round(pre["skew_s"], 3)
    summary["token_source"] = source

    (cap.dir / "probe_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"\nGATE: {gate_status}"
          + (f" — {'; '.join(gate_failures)}" if gate_failures else ""))
    print(f"summary -> {cap.dir / 'probe_summary.json'}")
    return 0 if gate_status == "GREEN" else (1 if gate_status == "PARTIAL" else 2)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
