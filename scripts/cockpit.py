r"""Cockpit v1 — replay a recorded session or watch live (descriptive only).

  # Verification / offline: reduce a recorded session and print the board
  .venv\Scripts\python scripts\cockpit.py --replay data\live\2026-07-24\probe_141223_431602_fb5cf8d4

  # Live (Monday flow): capture normally AND render the board every 2 s.
  # Everything the board shows is simultaneously recorded, so tonight's
  # replay of the same directory must reproduce the same numbers.
  .venv\Scripts\python scripts\cockpit.py --live [--minutes 30] [--keep-raw]

Altimeter, not co-pilot: no tickets, no entry arrows, no predictions, no
order hooks — ever. Execution stays manual (constitution).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd                                             # noqa: E402

from alpha.config import IST                                    # noqa: E402
from alpha.live import replay                                   # noqa: E402
from alpha.live.auth import load_upstox_token                   # noqa: E402
from alpha.live.cockpit import Cockpit                          # noqa: E402
from alpha.live.collector import SessionCapture                 # noqa: E402


def _fmt(v, w=8, nd=2):
    if v is None:
        return "-".rjust(w)
    if isinstance(v, float):
        return f"{v:,.{nd}f}".rjust(w)
    return str(v).rjust(w)


def render(cp: Cockpit, now_ns: int | None = None) -> str:
    h = cp.feed_health(now_ns)
    lines = []
    lines.append("=" * 78)
    lines.append(f"ALPHA COCKPIT v1 — descriptive only · altimeter, not "
                 f"co-pilot")
    lines.append(f"feed: {h['banner']}   ticks/s(10s): {h['tick_rate_10s']}"
                 f"   instruments: {h['n_instruments']}   reconnects: "
                 f"{h['reconnects']}   errors: {h['errors']}")
    if cp.rating:
        r = cp.rating
        lines.append(
            f"pre-open rating (frozen, emitted {r.get('emitted_at_ist')}): "
            f"{r.get('tier')} {r.get('wi_pctile_252')} — outcome "
            f"{r.get('outcome')}")
    else:
        lines.append("pre-open rating: NONE EMITTED (session unrated for "
                     "H-004 unless scripts\\emit_rating.py ran pre-open)")
    for sym in cp.symbols:
        spot = cp.spots.get(sym)
        atm = cp.atm_strike(sym)
        mp = cp.max_pain(sym)
        churn = cp.churn_panel(sym)
        lines.append("-" * 78)
        lines.append(f"{sym}  spot {_fmt(spot, 10)}   ATM {_fmt(atm, 8, 0)}"
                     f"   expiry {cp.expiries.get(sym, '?')}")
        hist = mp["history"]
        migr = (" -> ".join(f"{int(k)}" for _, k in hist[-4:])
                if hist else "-")
        lines.append(f"captured-band max pain (proxy — ATM band only, not "
                     f"the full chain) {_fmt(mp['strike'], 8, 0)}   "
                     f"migration: {migr}")
        walls = cp.oi_walls(sym, top=4)
        if walls:
            lines.append("OI concentration (proxy — public chain data, not "
                         "'dealer' anything):")
            for w in walls:
                lines.append(
                    f"  {int(w['strike']):>7}  CE {w['ce_oi']:>12,.0f} "
                    f"(d {w['d_ce']:>+11,.0f})  PE {w['pe_oi']:>12,.0f} "
                    f"(d {w['d_pe']:>+11,.0f})")
        rows = cp.spread_table(sym, width=2)
        if rows:
            lines.append("live hurdle (INDICATIVE all-in breakeven % — "
                         "mid-based, not ask-entry/bid-exit):")
            lines.append("   strike side      bid      ask   spread  spr% "
                         "  be%")
            for r in rows:
                lines.append(
                    f"  {int(r['strike']):>7} {r['side']:>4} "
                    f"{_fmt(r['bid'])} {_fmt(r['ask'])} "
                    f"{_fmt(r['spread'])} {_fmt(r['spread_pct'], 5)} "
                    f"{_fmt(r['breakeven_pct'], 5)}")
        if churn.get("atm") is not None:
            lines.append(
                f"ATM pair tick path length (incl. bid/ask bounce — NOT "
                f"capturable energy, not scalp_energy): Rs "
                f"{_fmt(churn['tick_path_rs_per_lot'], 10, 0)}/lot")
    lines.append("=" * 78)
    return "\n".join(lines)


def _todays_rating(session_date: str) -> dict | None:
    from alpha.paper import owner_log
    try:
        fwd = owner_log.load_forward_ratings()
    except Exception:
        return None
    if not len(fwd):
        return None
    hit = fwd[fwd["session_date"].dt.normalize()
              == pd.Timestamp(session_date).normalize()]
    return hit.iloc[0].to_dict() if len(hit) else None


def run_replay(session_dir: Path, snap_json: bool) -> int:
    session_file = session_dir / "session.json"
    imap = {}
    if session_file.exists():
        imap = json.loads(session_file.read_text()).get("instrument_map", {})
    cp = Cockpit(imap)
    day = session_dir.parent.name
    cp.set_rating(_todays_rating(day))
    n = 0
    for ev in replay.events(session_dir):
        cp.apply(ev)
        n += 1
    print(render(cp))
    print(f"[replayed {n:,} events from {session_dir}]")
    if snap_json:
        out = session_dir / "cockpit_snapshot.json"
        out.write_text(json.dumps(cp.snapshot(), indent=2, default=str),
                       encoding="utf-8")
        print(f"[snapshot -> {out}]")
    return 0


class CockpitCapture(SessionCapture):
    """SessionCapture that tees every event into the reducer. The tee is
    pure dict work — the recv path still never touches disk."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.cockpit = Cockpit()

    def resolve(self, master=None):
        keys = super().resolve(master)
        self.cockpit.meta = self._instrument_map()
        return keys

    def _enqueue_batch(self, events, raw=None, receipt_ns=None):
        ok = super()._enqueue_batch(events, raw, receipt_ns)
        # the screen may only ever show what was recorded: on queue
        # overflow the batch was NOT enqueued, so it must not be reduced —
        # otherwise tonight's replay could not reproduce the live board
        if ok:
            for ev in events:
                self.cockpit.apply(ev)
        return ok


async def run_live(minutes: float | None, keep_raw: bool) -> int:
    token, source = load_upstox_token()
    print(f"token source: {source}")
    cap = CockpitCapture(token, minutes=minutes, keep_raw=keep_raw,
                         label="cockpit")
    cap.resolve()
    cap.cockpit.set_rating(
        _todays_rating(datetime.now(IST).strftime("%Y-%m-%d")))

    async def _render_loop():
        while True:
            await asyncio.sleep(2)
            import time
            print("\x1b[2J\x1b[H" + render(cap.cockpit, time.time_ns()))

    render_task = asyncio.create_task(_render_loop())
    try:
        manifest = await cap.run()
    finally:
        render_task.cancel()
    print(render(cap.cockpit))
    print(f"[capture -> {cap.dir}]")
    degraded = (manifest.get("metadata") or {}).get("degraded_reason")
    return 2 if degraded else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--replay", metavar="DIR", help="session directory")
    g.add_argument("--live", action="store_true")
    ap.add_argument("--snap", action="store_true",
                    help="with --replay: also write cockpit_snapshot.json")
    ap.add_argument("--minutes", type=float, default=None)
    ap.add_argument("--keep-raw", action="store_true")
    args = ap.parse_args(argv)
    if args.replay:
        return run_replay(Path(args.replay), args.snap)
    return asyncio.run(run_live(args.minutes, args.keep_raw))


if __name__ == "__main__":
    raise SystemExit(main())
