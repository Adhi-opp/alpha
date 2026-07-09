"""Nightly fetch: participant OI + FO bhavcopy for one date.

raw archive -> parse (available_at stamped) -> derived parquet -> integrity
report. Exit code 1 if any ERROR-severity issue (red day: downstream must
not use it until resolved).

Usage:
  python scripts/fetch_daily.py                # last weekday (IST)
  python scripts/fetch_daily.py --date 2026-07-06
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha.config import IST
from alpha.data import integrity, nse, parse, pit

PARTICIPANT_KEYS = ["trade_date", "client_type"]
BHAV_KEYS = ["trade_date", "symbol", "instrument", "expiry", "strike", "option_type"]


def last_weekday_ist() -> date:
    d = datetime.now(IST)
    # both files publish in the evening; before 22:30 IST assume yesterday
    target = d.date() if (d.hour, d.minute) >= (22, 30) else d.date() - timedelta(days=1)
    while target.weekday() >= 5:
        target -= timedelta(days=1)
    return target


def run(d: date) -> int:
    issues: list[integrity.Issue] = []
    session = nse.make_session()

    try:
        poi_path = nse.fetch_participant_oi(d, session)
        poi = parse.parse_participant_oi(poi_path, d)
        pit.append("participant_oi", poi, PARTICIPANT_KEYS)
        issues += integrity.check_participant_oi_day(poi)
        print(f"participant_oi {d}: {len(poi)} rows -> derived")
    except nse.NotPublished:
        print(f"participant_oi {d}: not published (holiday or too early)")

    try:
        bhav_path = nse.fetch_fo_bhavcopy(d, session)
        bhav = parse.parse_fo_bhavcopy(bhav_path)
        pit.append("fo_bhavcopy", bhav, BHAV_KEYS)
        issues += integrity.check_bhavcopy_day(bhav)
        print(f"fo_bhavcopy    {d}: {len(bhav)} rows -> derived")
    except nse.NotPublished:
        print(f"fo_bhavcopy    {d}: not published (holiday or too early)")

    for issue in issues:
        print(str(issue))
    n_err = len(integrity.errors(issues))
    print(f"integrity: {n_err} error(s), {len(issues) - n_err} warning(s)")
    return 1 if n_err else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                    help="trade date (default: last weekday, IST)")
    args = ap.parse_args()
    target = date.fromisoformat(args.date) if args.date else last_weekday_ist()
    sys.exit(run(target))
