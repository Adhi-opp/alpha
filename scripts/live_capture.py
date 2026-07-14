r"""Capture one bounded Alpha Live Desk session; never place an order.

Use after ``scripts\upstox_login.py`` has created an access token:

  d:\alpha\.venv\Scripts\python scripts\live_capture.py
  d:\alpha\.venv\Scripts\python scripts\live_capture.py --minutes 30
  d:\alpha\.venv\Scripts\python scripts\live_capture.py --minutes 10 --keep-raw

Without ``--minutes`` capture stops at the configured session end. Each run
creates a unique directory under ``data/live/<date>/``. It records the
market; it never creates a ticket, sends an order, or changes account state.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha.live.collector import DEFAULT_QUEUE_MAX, SessionCapture
from scripts.dhan_probe import load_env


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--minutes", type=float,
                    help="stop after this many minutes (default: session end)")
    ap.add_argument("--label", default="capture",
                    help="human-readable run prefix; each run remains unique")
    ap.add_argument("--keep-raw", action="store_true",
                    help="also preserve one framed raw websocket payload per message")
    ap.add_argument("--queue-max", type=int, default=DEFAULT_QUEUE_MAX,
                    help="bounded in-memory frames before capture halts degraded")
    args = ap.parse_args()

    token = load_env().get("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        sys.exit("UPSTOX_ACCESS_TOKEN missing — run scripts\\upstox_login.py first")

    cap = SessionCapture(token, symbols=("NIFTY", "SENSEX"),
                         minutes=args.minutes, keep_raw=args.keep_raw,
                         label=args.label, queue_max=args.queue_max)
    keys = cap.resolve()
    print(f"NIFTY front-week {cap.chains['NIFTY'].expiry}; "
          f"SENSEX front-week {cap.chains['SENSEX'].expiry}")
    print(f"subscribing {len(keys)} instruments -> {cap.dir}")
    manifest = await cap.run()
    meta = manifest.get("metadata", {})
    print(f"capture complete: {manifest['n_events']:,} normalized events, "
          f"{manifest['n_raw']:,} raw frames")
    print(f"queue high-water: {meta.get('queue_high_water')} / "
          f"{meta.get('queue_max')}")
    if meta.get("degraded_reason"):
        print(f"CAPTURE DEGRADED: {meta['degraded_reason']}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
