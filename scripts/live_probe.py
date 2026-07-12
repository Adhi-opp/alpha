r"""THE PROBE GATE (docs/LIVE_DESK.md): one market-hours run before any
cockpit or feature code gets built. Answers, from real responses:

  token/REST sanity - front-week resolution (both chains) - which fields
  actually arrive in `full` mode per instrument class - message/byte rates
  - subscription-limit behavior at ~90 keys - retarget drill latency -
  provider-vs-local clock skew.

Run any time 09:20-15:15 IST on a trading day (fresh token first:
scripts\upstox_login.py):

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
from alpha.live.collector import SessionCapture
from scripts.dhan_probe import load_env

DRILL_AFTER_S = 120       # unsub 2 wing strikes after this long
DRILL_RESUB_S = 15        # resubscribe them this much later


class ProbeCapture(SessionCapture):
    """SessionCapture plus the scheduled retarget drill."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._drill_state = "pending"
        self._drill_keys: list[str] = []
        self._drill_t = time.time()

    def _drill_frames(self):
        elapsed = time.time() - self._drill_t
        sym = self.symbols[0]
        chain, band = self.chains.get(sym), self.bands.get(sym)
        if not chain or not band or len(band) < 5:
            return []
        if self._drill_state == "pending" and elapsed >= DRILL_AFTER_S:
            self._drill_state = "unsubbed"
            self._drill_keys = chain.band_keys(band[-2:])
            return [(up.build_frame("unsub", self._drill_keys),
                     {"kind": "drill_unsub", "keys": self._drill_keys})]
        if self._drill_state == "unsubbed" and elapsed >= DRILL_AFTER_S + DRILL_RESUB_S:
            self._drill_state = "done"
            return [(up.build_frame("sub", self._drill_keys),
                     {"kind": "drill_resub", "keys": self._drill_keys})]
        return []

    def _retarget_frames(self):
        return self._drill_frames() + super()._retarget_frames()


def summarize(session_dir: Path) -> dict:
    counts: dict[str, int] = {}
    field_hits = {"iv": 0, "gamma": 0, "depth5": 0, "oi": 0, "tbq": 0,
                  "atp": 0}
    n_ticks = 0
    skew_ms: list[float] = []
    t0 = t1 = None
    per_key_ticks: dict[str, int] = {}
    drill = {"unsub_ns": None, "resub_ns": None, "first_tick_after_ns": None}
    errors: list[str] = []
    for ev in replay.events(session_dir):
        k = ev["kind"]
        counts[k] = counts.get(k, 0) + 1
        t = ev.get("t_local_ns")
        if t is not None:
            t0 = t if t0 is None else t0
            t1 = t
        if k == "tick":
            n_ticks += 1
            per_key_ticks[ev["key"]] = per_key_ticks.get(ev["key"], 0) + 1
            if ev.get("iv"):
                field_hits["iv"] += 1
            if ev.get("greeks", {}).get("gamma"):
                field_hits["gamma"] += 1
            if len(ev.get("depth", [])) >= 5:
                field_hits["depth5"] += 1
            if ev.get("oi"):
                field_hits["oi"] += 1
            if ev.get("tbq"):
                field_hits["tbq"] += 1
            if ev.get("atp"):
                field_hits["atp"] += 1
            if ev.get("provider_ts"):
                skew_ms.append(t / 1e6 - ev["provider_ts"])
        elif k == "drill_unsub":
            drill["unsub_ns"] = t
        elif k == "drill_resub":
            drill["resub_ns"] = t
            drill["keys"] = ev.get("keys", [])
        elif k in ("ws_error", "ws_text"):
            errors.append(json.dumps(ev)[:300])
    # first tick on a drilled key after resub
    if drill.get("resub_ns"):
        for ev in replay.events(session_dir):
            if (ev["kind"] == "tick" and ev["key"] in drill.get("keys", [])
                    and ev["t_local_ns"] > drill["resub_ns"]):
                drill["first_tick_after_ns"] = ev["t_local_ns"]
                break
    span_s = ((t1 - t0) / 1e9) if (t0 and t1 and t1 > t0) else float("nan")
    raw_bytes = sum(p.stat().st_size for p in Path(session_dir).glob("raw_*.bin"))
    return {
        "counts": counts,
        "span_s": round(span_s, 1),
        "ticks_per_s": round(n_ticks / span_s, 1) if span_s > 0 else None,
        "raw_bytes": raw_bytes,
        "raw_bytes_per_s": round(raw_bytes / span_s) if span_s > 0 else None,
        "field_presence_pct": {f: round(100 * v / n_ticks, 1) if n_ticks else 0
                               for f, v in field_hits.items()},
        "n_instruments_seen": len(per_key_ticks),
        "quietest_instruments": sorted(per_key_ticks.items(),
                                       key=lambda kv: kv[1])[:5],
        "clock_skew_ms": ({"median": round(statistics.median(skew_ms), 1),
                           "p95": round(sorted(skew_ms)[int(0.95 * len(skew_ms))], 1)}
                          if skew_ms else None),
        "drill_resub_to_first_tick_ms": (
            round((drill["first_tick_after_ns"] - drill["resub_ns"]) / 1e6, 1)
            if drill.get("first_tick_after_ns") and drill.get("resub_ns")
            else None),
        "errors": errors[:10],
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--half-width", type=int, default=10)
    args = ap.parse_args()

    env = load_env()
    token = env.get("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        sys.exit("UPSTOX_ACCESS_TOKEN missing — run scripts\\upstox_login.py")

    # 1. REST sanity (fails fast on a stale token, before any ws work)
    try:
        spots = up.rest_ltp(list(up.INDEX_KEYS.values()), token)
    except Exception as exc:
        sys.exit(f"REST LTP failed ({exc}) — token stale? run "
                 f"scripts\\upstox_login.py")
    print(f"REST spots: {spots}")

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

    manifest = await cap.run()   # uses the keys resolved above
    print(f"capture done: {manifest['n_events']:,} events, "
          f"{manifest['n_raw']:,} raw frames\n")

    summary = summarize(cap.dir)
    (cap.dir / "probe_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"\nsummary -> {cap.dir / 'probe_summary.json'}")
    print("Next: write docs/UPSTOX_FINDINGS.md from THIS output.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
