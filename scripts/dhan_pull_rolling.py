r"""Execute the 3-year NIFTY rolling-option pull (raw archive only).

~1,554 calls: ATM+/-10 x CALL/PUT x front-week (ec=1) over 30-day windows,
2023-07-01 .. 2026-07-06. Resumable — rerun after any interruption; archived
windows are skipped. Credentials from .env (gitignored).

  d:\alpha\.venv\Scripts\python scripts\dhan_pull_rolling.py
Then convert to tidy parquet:
  d:\alpha\.venv\Scripts\python scripts\dhan_pull_rolling.py --tidy
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha.data import dhan_rolling
from scripts.dhan_probe import load_env

START, END = date(2023, 7, 1), date(2026, 7, 6)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tidy", action="store_true",
                    help="convert archived raw JSON to tidy parquet")
    args = ap.parse_args()
    if args.tidy:
        n = dhan_rolling.tidy_archive_to_parquet()
        print(f"tidy parquet rows: {n:,}")
        sys.exit(0)
    env = load_env()
    token, cid = env.get("DHAN_ACCESS_TOKEN", ""), env.get("DHAN_CLIENT_ID", "")
    if not token or not cid:
        sys.exit("credentials missing from .env")
    plan = dhan_rolling.plan_pull(START, END)
    print(f"plan: {len(plan)} requests "
          f"(~{len(plan) * dhan_rolling.REQUEST_SLEEP_S / 60:.0f} min at "
          f"{dhan_rolling.REQUEST_SLEEP_S}s/req)")
    stats = dhan_rolling.execute_pull(plan, token, cid)
    print(f"done: {stats}")
