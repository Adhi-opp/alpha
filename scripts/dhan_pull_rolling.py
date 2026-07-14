r"""Rolling-option pull (raw archive only) — incremental and date-aware.

ATM+/-10 x CALL/PUT x front-week (ec=1) over 30-day windows. Resumable:
archived windows are skipped, so extending a dataset is just a rerun with a
later --end. Credentials from .env (gitignored).

  # full/default range
  d:\alpha\.venv\Scripts\python scripts\dhan_pull_rolling.py --symbol nifty
  # incremental extension (only new windows are fetched)
  d:\alpha\.venv\Scripts\python scripts\dhan_pull_rolling.py --symbol sensex --end 2026-07-14
  # convert archived raw JSON to tidy parquet
  d:\alpha\.venv\Scripts\python scripts\dhan_pull_rolling.py --symbol nifty --tidy

IMPORTANT: --end must be a COMPLETED session (run after market close).
Archives are immutable — a partial day pulled mid-session would be frozen
wrong and skipped forever by the resume logic.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha.data import dhan_rolling
from scripts.dhan_probe import load_env

DEFAULT_START, DEFAULT_END = date(2023, 7, 1), date(2026, 7, 14)

SYMBOLS = {
    "nifty": {"symbol": "NIFTY", "security_id": dhan_rolling.NIFTY_UNDERLYING_ID,
              "segment": "NSE_FNO", "dataset": "dhan_rolling_1m"},
    "sensex": {"symbol": "SENSEX", "security_id": dhan_rolling.SENSEX_UNDERLYING_ID,
               "segment": "BSE_FNO", "dataset": "dhan_rolling_1m_sensex"},
}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", choices=sorted(SYMBOLS), default="nifty")
    ap.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START,
                    metavar="YYYY-MM-DD")
    ap.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END,
                    metavar="YYYY-MM-DD",
                    help="last date to include; must be a COMPLETED session")
    ap.add_argument("--tidy", action="store_true",
                    help="convert archived raw JSON to tidy parquet")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.end < args.start:
        print(f"--end {args.end} is before --start {args.start}")
        return 2
    if args.end > date.today():
        print(f"--end {args.end} is in the future — archives are immutable, "
              f"a partial day would be frozen wrong")
        return 2
    cfg = SYMBOLS[args.symbol]
    if args.tidy:
        n = dhan_rolling.tidy_archive_to_parquet(
            symbol=cfg["symbol"], out_dataset=cfg["dataset"])
        print(f"tidy parquet rows ({cfg['symbol']}): {n:,}")
        return 0
    env = load_env()
    token, cid = env.get("DHAN_ACCESS_TOKEN", ""), env.get("DHAN_CLIENT_ID", "")
    if not token or not cid:
        print("credentials missing from .env")
        return 2
    plan = dhan_rolling.plan_pull(args.start, args.end)
    print(f"plan: {len(plan)} requests over {args.start}..{args.end} "
          f"(~{len(plan) * dhan_rolling.REQUEST_SLEEP_S / 60:.0f} min at "
          f"{dhan_rolling.REQUEST_SLEEP_S}s/req; archived windows skipped)")
    stats = dhan_rolling.execute_pull(
        plan, token, cid, symbol=cfg["symbol"],
        security_id=cfg["security_id"], exchange_segment=cfg["segment"])
    print(f"done: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
