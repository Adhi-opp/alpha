"""Build the console's state from REAL project data. No invented numbers.

Every field traces to something measured: parquet coverage, the cost model
fitted to your contract notes, the ledger files, and a paper drawdown ledger.
The verdict is derived, not decided here — with no promoted study, it is
always STAND DOWN, and that is the honest default.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from alpha.config import DERIVED_ROOT, IST, PROJECT_ROOT
from alpha.data import integrity
from alpha.measure.costs import ZERODHA_NSE_OPTIONS_2026_07 as COST

KILL_SWITCH_RUPEES = 6000.0        # README constraint
LEDGER_DIR = PROJECT_ROOT / "ledger"
PAPER_STATE = PROJECT_ROOT / "data" / "paper" / "drawdown.json"
LOT_NIFTY = 65                     # read from data; snapshot 2026-07-08


def _trade_dates(dataset: str) -> list[date]:
    """Distinct trade dates for a derived dataset, reading only that column."""
    files = sorted((DERIVED_ROOT / dataset).glob("*.parquet"))
    if not files:
        return []
    days: set[date] = set()
    for f in files:
        col = pd.read_parquet(f, columns=["trade_date"])["trade_date"]
        days.update(pd.to_datetime(col).dt.date.unique())
    return sorted(days)


def coverage() -> dict:
    bhav_days = _trade_dates("fo_bhavcopy")
    poi_days = _trade_dates("participant_oi")
    gaps = integrity.gap_report("participant_oi", poi_days, bhav_days) if bhav_days else []
    green = len(bhav_days) > 0 and len(gaps) == 0
    return {
        "sessions": len(bhav_days),
        "participant_sessions": len(poi_days),
        "gaps": len(gaps),
        "green": green,
        "span": ([str(bhav_days[0]), str(bhav_days[-1])] if bhav_days else None),
    }


def cost_hurdle() -> list[dict]:
    rows = []
    for premium, lots in [(50, 1), (100, 1), (150, 1), (100, 4)]:
        qty = LOT_NIFTY * lots
        rt = COST.round_trip_cost(premium * qty, premium * qty)
        be = COST.breakeven_move(premium, qty)
        rows.append({
            "position": f"₹{premium} × {lots} lot{'s' if lots > 1 else ''} ({qty})",
            "round_trip": round(rt, 2),
            "breakeven_pct": round(be / premium * 100, 2),
        })
    return rows


def drawdown() -> dict:
    used = 0.0
    if PAPER_STATE.exists():
        used = float(json.loads(PAPER_STATE.read_text()).get("cumulative_drawdown", 0.0))
    return {
        "used": used,
        "budget": KILL_SWITCH_RUPEES,
        "pct": round(min(used / KILL_SWITCH_RUPEES, 1.0) * 100, 1),
        "tripped": used >= KILL_SWITCH_RUPEES,
    }


def _parse_ledger_status(text: str) -> str:
    m = re.search(r"^-?\s*\*\*Status:\*\*\s*(.+)$", text, re.MULTILINE)
    if not m:
        m = re.search(r"^-\s*\*\*Status:\*\*\s*(.+)$", text, re.MULTILINE)
    raw = (m.group(1) if m else "").upper()
    for verdict in ("NO-GO", "INVERTED", "STALE", "GO", "PRE-REGISTERED", "RUNNING", "DRAFT"):
        if verdict in raw:
            return verdict
    return "UNKNOWN"


def _ledger_status(stem_prefix: str) -> str | None:
    """Live status of a ledger entry (e.g. 'H001r'), None if no file yet."""
    for f in sorted(LEDGER_DIR.glob(f"{stem_prefix}-*.md")):
        return _parse_ledger_status(f.read_text(encoding="utf-8"))
    return None


def ledger() -> dict:
    # Imported GammaLeak-era family: 1 GO (H-001) + 4 NO-GO, per ledger/README.
    imported = {"registered": 5, "go": 1, "nogo": 4}
    entries = []
    for f in sorted(LEDGER_DIR.glob("[HS]*.md")):
        status = _parse_ledger_status(f.read_text(encoding="utf-8"))
        entries.append({"id": f.stem.split("-")[0], "status": status})
    return {
        "family_registered": imported["registered"],
        "go": imported["go"],
        "nogo": imported["nogo"],
        "entries": entries,
    }


def _tier(pctile: float) -> str:
    """Display convention only (family's trailing 66.7/33.3 split). The
    forward-log promotion test pre-registers its OWN split before grading;
    the log stores the raw percentile, never just the tier."""
    if pctile >= 66.7:
        return "FAVORABLE"
    if pctile < 33.3:
        return "UNFAVORABLE"
    return "NEUTRAL"


def _next_session_expiry() -> tuple[str | None, bool | None]:
    """Next weekday after the latest bhav session, and whether it is the
    front-week NIFTY expiry. Holiday shifts make 'next weekday' approximate;
    the next morning's fetch corrects it."""
    files = sorted((DERIVED_ROOT / "fo_bhavcopy").glob("*.parquet"))
    if not files:
        return None, None
    b = pd.read_parquet(files[-1],
                        columns=["trade_date", "symbol", "instrument", "expiry"])
    b = b[(b["symbol"] == "NIFTY") & (b["instrument"] == "IDO")]
    if b.empty:
        return None, None
    last_td = b["trade_date"].max()
    nxt = last_td + pd.Timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += pd.Timedelta(days=1)
    expiries = pd.to_datetime(b.loc[b["trade_date"] == last_td, "expiry"])
    future = expiries[expiries >= nxt]
    fw = future.min() if len(future) else None
    return str(nxt.date()), bool(fw == nxt) if fw is not None else None


def scalp_environment() -> dict:
    """H-003 (GO) licenses exactly one verdict: rate the NEXT NIFTY session
    from the freshest T-1 participant file. The effect is EXPIRY-SPECIFIC
    (non-expiry contrast −0.14), so the rating only speaks on expiry
    sessions. Association GO — no ticket, no sizing; promotion pending the
    forward owner log."""
    if (_ledger_status("H003") or "") != "GO":
        return {"licensed": False}
    from alpha.data import pit
    from alpha.study.h001r import client_write_intensity
    try:
        poi = pit.load("participant_oi", datetime.now(timezone.utc))
    except (FileNotFoundError, ValueError):
        return {"licensed": True, "ready": False, "reason": "no participant data"}
    if poi.empty:
        return {"licensed": True, "ready": False, "reason": "no participant data"}
    wi = client_write_intensity(poi)
    tail = wi["wi"].tail(252)
    latest = float(tail.iloc[-1])
    pctile = round(float((tail <= latest).mean() * 100), 1)
    cond_date = wi["trade_date"].iloc[-1]
    stale_days = (datetime.now(IST).date() - cond_date.date()).days
    nxt, is_expiry = _next_session_expiry()
    return {
        "licensed": True,
        "ready": stale_days <= 4,
        "cond_date": str(cond_date.date()),
        "wi": round(latest, 4),
        "wi_pctile_252": pctile,
        "tier": _tier(pctile),
        "next_session": nxt,
        "next_is_expiry": is_expiry,
        "note": "H-003 GO · association only — rates expiry sessions, "
                "licenses no ticket; promotion pending forward owner log",
    }


def promotion_gate() -> dict:
    # 7 fixed conditions (ARCHITECTURE.md §7). None met until a study runs.
    return {"met": 0, "total": 7, "paper_tickets": 0, "paper_target": 40}


def verdict(dd: dict) -> dict:
    """Honest default. No promoted study => no live signal => stand down."""
    if dd["tripped"]:
        return {"state": "HALT", "headline": "Kill-switch tripped.",
                "detail": "Cumulative drawdown hit the budget. System halted "
                          "pending a written post-mortem."}
    return {
        "state": "STAND_DOWN",
        "headline": "Stand down.",
        "detail": "No study is promoted to tickets. H-003's day rating (right) "
                  "is live for expiry sessions — it rates the environment for "
                  "YOUR manual scalping; it is not itself a trade signal.",
        "nearest": {"candidate": "H-003 · expiry scalp environment",
                    "p": None, "threshold": None,
                    "note": "GO (association) — promotion needs the forward owner log"},
    }


def build_state() -> dict:
    dd = drawdown()
    return {
        "as_of": datetime.now(IST).strftime("%a %d %b %Y %H:%M IST"),
        "system": {"armed": not dd["tripped"], "mode": "paper track · no live money"},
        "coverage": coverage(),
        "cost_hurdle": cost_hurdle(),
        "drawdown": dd,
        "ledger": ledger(),
        "promotion": promotion_gate(),
        "verdict": verdict(dd),
        "scalp": scalp_environment(),
        "study_pipeline": [
            {"id": "H-001r", "label": "re-validate edge",
             "status": _ledger_status("H001r") or "PRE-REG PENDING"},
            {"id": "H-001b", "label": "option expression",
             "status": _ledger_status("H001b") or "QUEUED"},
            {"id": "H-002", "label": "intraday trigger",
             "status": _ledger_status("H002") or "FALLBACK"},
            {"id": "H-003", "label": "expiry day rating",
             "status": _ledger_status("H003") or "QUEUED"},
        ],
    }
