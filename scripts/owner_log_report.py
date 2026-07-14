r"""Print the owner log: retro seed vs H-004 forward log, kept honestly
apart. The retro sessions (before 2026-07-14) are context — the frozen
H-004 pre-registration excludes them; the forward count is the one that
walks toward 40. No association statistic appears here before n=40 (the
evaluator refuses anyway).

  d:\alpha\.venv\Scripts\python scripts\owner_log_report.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha.paper import owner_log

if __name__ == "__main__":
    s = owner_log.summary()
    print(f"sessions logged   : {s['sessions_logged']} "
          f"({s['retro_validated_sessions']} retro validated-scope — "
          f"context only, EXCLUDED from H-004)")
    print(f"H-004 forward log : {s['h004_ratings_emitted']} rating(s) "
          f"emitted, {s['h004_finalized']}/{s['h004_target']} finalized")
    print(f"round trips       : {s['trades_logged']}   "
          f"median hold {s['median_hold_s']:.0f}s   "
          f"gross win rate {s['win_rate_gross']:.0%}")
    print(f"net P&L logged    : Rs {s['day_pnl_total']:+,.2f}")
    print(f"MAE computed      : {s['mae_computed']}/{s['trades_logged']} "
          f"(discipline flags: {s['discipline_flags']})")
    if s["h004_forward"]:
        print("\nH-004 forward ratings")
        for r in s["h004_forward"]:
            print(f"  {r['session_date']}  {r['wi_pctile_252']:>5.1f} pct  "
                  f"{r['tier']:<12} outcome: {r['outcome']}")
    print("\nretro seed (context only)")
    print("session        exch  net P&L      wi pct  tier         scope")
    for r in s["by_session"]:
        pct = "—" if r["wi_pctile_252"] is None else f"{r['wi_pctile_252']:.1f}"
        tier = r["tier"] or "—"
        print(f"{r['session_date']}  {r['exchange']:4} "
              f"{r['day_net_pnl']:>+10,.2f}   {pct:>5}  {tier:<12} "
              f"{r['scope']}{'  · NIFTY expiry' if r['is_nifty_expiry'] else ''}")
