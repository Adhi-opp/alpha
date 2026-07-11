r"""Print the owner log: sessions vs the rating the console would have
emitted before each open, plus trade-level stats.

  d:\alpha\.venv\Scripts\python scripts\owner_log_report.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha.paper import owner_log

if __name__ == "__main__":
    s = owner_log.summary()
    print(f"sessions logged : {s['sessions_logged']}  "
          f"(validated-scope {s['sessions_validated_scope']} / "
          f"target {s['sessions_target']})")
    print(f"round trips     : {s['trades_logged']}   "
          f"median hold {s['median_hold_s']:.0f}s   "
          f"gross win rate {s['win_rate_gross']:.0%}")
    print(f"net P&L logged  : Rs {s['day_pnl_total']:+,.2f}")
    print(f"MAE computed    : {s['mae_computed']}/{s['trades_logged']} "
          f"(discipline flags: {s['discipline_flags']})")
    print("\nsession        exch  net P&L      wi pct  tier         scope")
    for r in s["by_session"]:
        pct = "—" if r["wi_pctile_252"] is None else f"{r['wi_pctile_252']:.1f}"
        tier = r["tier"] or "—"
        print(f"{r['session_date']}  {r['exchange']:4} "
              f"{r['day_net_pnl']:>+10,.2f}   {pct:>5}  {tier:<12} "
              f"{r['scope']}{'  · NIFTY expiry' if r['is_nifty_expiry'] else ''}")
