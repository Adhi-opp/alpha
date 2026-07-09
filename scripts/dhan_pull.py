"""Dhan bulk-pull driver. DRY-RUN BY DEFAULT — the paid step is explicit.

Sequence (docs/DATA.md): open free Dhan account -> build free layer ->
dry-run THIS script -> only then subscribe to Data APIs -> --execute ->
gap census -> cancel the subscription.

Usage:
  python scripts/dhan_pull.py --dry-run            # plan + cost/time estimate
  python scripts/dhan_pull.py --fetch-master       # archive instrument master (free)
  python scripts/dhan_pull.py --execute            # PAID: needs DHAN_* env vars
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha.data import archive, dhan_bulk, pit


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="NIFTY")
    ap.add_argument("--strike-window", type=float, default=0.06,
                    help="max |strike/underlying - 1| to include (default 6%%)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--fetch-master", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    if args.fetch_master:
        import requests
        resp = requests.get(dhan_bulk.INSTRUMENT_MASTER_URL, timeout=120)
        resp.raise_for_status()
        path = archive.store("dhan", "instrument_master/api-scrip-master-detailed.csv",
                             resp.content, dhan_bulk.INSTRUMENT_MASTER_URL)
        print(f"archived instrument master -> {path}")
        print("Inspect its columns, then implement _resolve_security_ids().")
        return 0

    bhav = pit.load_all_unsafe("fo_bhavcopy")  # ops context: PIT filter not needed
    universe = dhan_bulk.contract_universe(
        bhav, symbol=args.symbol, strike_window_pct=args.strike_window)
    plan = dhan_bulk.build_plan(universe)
    print(dhan_bulk.summarize_plan(universe, plan))

    # Resolve security IDs from the archived master (free, no API call) so a
    # dry-run also proves every contract is findable before any spend.
    master = archive.path_of("dhan", "instrument_master/api-scrip-master-detailed.csv")
    if master.exists():
        try:
            ids = dhan_bulk.resolve_security_ids(universe, master, symbol=args.symbol)
            print(f"\nsecurity-id resolution: {len(ids)}/{len(universe)} contracts matched")
        except KeyError as exc:
            print(f"\nsecurity-id resolution INCOMPLETE: {exc}")
            ids = None
    else:
        print("\ninstrument master not archived yet — run --fetch-master first")
        ids = None

    if args.execute:
        if ids is None:
            print("Refusing to spend: resolve security IDs cleanly first.")
            return 1
        dhan_bulk.execute_plan(plan, ids)
    return 0


if __name__ == "__main__":
    sys.exit(main())
