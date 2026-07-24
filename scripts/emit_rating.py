r"""Emit (or finalize) the H-004 forward rating for one session.

journal/ratings_forward.csv is H-004's ONLY sample source: no emitted row,
no sample entry — the session is excluded AND disclosed as unrated. Rows
are written by this script, never by hand.

  # session morning BEFORE 09:15 IST (or the evening before, after the
  # participant file lands) — emit the next session's rating:
  .venv\Scripts\python scripts\emit_rating.py

  # after journaling the contract note (or confirming no trade):
  .venv\Scripts\python scripts\emit_rating.py --date 2026-07-28 --finalize traded
  .venv\Scripts\python scripts\emit_rating.py --date 2026-07-28 --finalize abstained

Exit codes: 0 written; 1 refused (guard tripped — the refusal message says
which frozen rule fired; a refused emission means the session goes unrated).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd                                             # noqa: E402

from alpha.config import IST                                    # noqa: E402
from alpha.paper import owner_log                               # noqa: E402


def default_session_date() -> str:
    """Today if before 09:15 IST, else the next weekday. Holiday shifts are
    the operator's problem — a wrong date trips the emission guards."""
    now = datetime.now(IST)
    d = pd.Timestamp(now.date())
    if (now.hour, now.minute) >= (9, 15):
        d += pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d += pd.Timedelta(days=1)
    return str(d.date())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=None,
                    help="session date YYYY-MM-DD (default: next session)")
    ap.add_argument("--finalize", choices=["traded", "abstained"],
                    default=None, help="settle an emitted rating instead")
    ap.add_argument("--note", default="", help="free-text note for the row")
    args = ap.parse_args(argv)
    session = args.date or default_session_date()
    try:
        if args.finalize:
            row = owner_log.finalize_forward_rating(session, args.finalize)
            print(f"finalized {session} -> {args.finalize}")
        else:
            row = owner_log.emit_forward_rating(session, note=args.note)
            print(f"emitted {session}: wi_pctile_252={row['wi_pctile_252']} "
                  f"({row['tier']}), computed from {row['computed_from']}, "
                  f"is_nifty_expiry={row['is_nifty_expiry']}, "
                  f"outcome=pending")
    except ValueError as exc:
        print(f"REFUSED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
