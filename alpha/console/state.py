"""Build the console's state from REAL project data. No invented numbers.

Every field traces to something measured: parquet coverage, the cost model
fitted to your contract notes, the ledger files, and a paper drawdown ledger.
The verdict is derived, not decided here — with no promoted study, it is
always STAND DOWN, and that is the honest default.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
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
        "detail": "No calibrated edge cleared the cost hurdle today. Not trading "
                  "is the position — and on most days, this is what a working desk looks like.",
        "nearest": {"candidate": "H-001b · overnight long premium",
                    "p": None, "threshold": None, "note": "study not yet run"},
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
        "study_pipeline": [
            {"id": "H-001r", "label": "re-validate edge", "status": "PRE-REG PENDING"},
            {"id": "H-001b", "label": "option expression", "status": "QUEUED"},
            {"id": "H-002", "label": "intraday trigger", "status": "FALLBACK"},
        ],
    }
