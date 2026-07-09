"""Backfill NSE daily files across a date range. Resumable and polite.

Already-archived dates are re-parsed from disk (no network, no sleep),
holidays are tolerated, and there is a courtesy sleep after each date that
hit the network. Parsed frames are flushed to derived parquet in batches
(rewriting a year partition per day would make a 3-year run quadratic).
Safe to Ctrl-C and re-run: raw archives survive, unflushed parses are
simply re-read from the archive on the next run.

Usage:
  python scripts/backfill.py --start 2023-07-01 --end 2026-07-06
  python scripts/backfill.py --start 2026-06-01 --end 2026-07-06 --only participant_oi
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from alpha.data import nse, parse, pit
from scripts.fetch_daily import BHAV_KEYS, PARTICIPANT_KEYS

SLEEP_S = 1.0
FLUSH_EVERY_DAYS = 21


class _Buffer:
    def __init__(self, dataset: str, keys: list[str]):
        self.dataset = dataset
        self.keys = keys
        self.frames: list[pd.DataFrame] = []

    def add(self, df: pd.DataFrame) -> None:
        self.frames.append(df)

    def flush(self) -> None:
        if self.frames:
            pit.append(self.dataset, pd.concat(self.frames, ignore_index=True),
                       self.keys)
            self.frames.clear()


def run(start: date, end: date, only: str | None) -> None:
    session = nse.make_session()
    poi_buf = _Buffer("participant_oi", PARTICIPANT_KEYS)
    bhav_buf = _Buffer("fo_bhavcopy", BHAV_KEYS)
    fetched = cached = not_published = failures = 0
    days_since_flush = 0
    d = start
    try:
        while d <= end:
            if d.weekday() >= 5:
                d += timedelta(days=1)
                continue
            hit_network = False

            if only in (None, "participant_oi"):
                was_cached = nse.participant_oi_archived(d)
                try:
                    path = nse.fetch_participant_oi(d, session)
                    poi_buf.add(parse.parse_participant_oi(path, d))
                    cached += was_cached
                    fetched += not was_cached
                    hit_network |= not was_cached
                except nse.NotPublished:
                    not_published += 1
                except Exception as exc:
                    failures += 1
                    print(f"FAIL participant_oi {d}: {exc}", flush=True)

            if only in (None, "fo_bhavcopy"):
                was_cached = nse.fo_bhavcopy_archived(d)
                try:
                    path = nse.fetch_fo_bhavcopy(d, session)
                    bhav_buf.add(parse.parse_fo_bhavcopy(path))
                    cached += was_cached
                    fetched += not was_cached
                    hit_network |= not was_cached
                except nse.NotPublished:
                    not_published += 1
                except Exception as exc:
                    failures += 1
                    print(f"FAIL fo_bhavcopy {d}: {exc}", flush=True)

            days_since_flush += 1
            if days_since_flush >= FLUSH_EVERY_DAYS:
                poi_buf.flush()
                bhav_buf.flush()
                days_since_flush = 0
                print(f"progress: through {d} | fetched {fetched}, "
                      f"cached {cached}, not-published {not_published}, "
                      f"failures {failures}", flush=True)
            if hit_network:
                time.sleep(SLEEP_S)
            d += timedelta(days=1)
    finally:
        poi_buf.flush()
        bhav_buf.flush()

    print(f"done: {fetched} fetched, {cached} from archive, "
          f"{not_published} not-published file-attempts, {failures} failures")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True, metavar="YYYY-MM-DD")
    ap.add_argument("--end", required=True, metavar="YYYY-MM-DD")
    ap.add_argument("--only", choices=["participant_oi", "fo_bhavcopy"])
    args = ap.parse_args()
    run(date.fromisoformat(args.start), date.fromisoformat(args.end), args.only)
