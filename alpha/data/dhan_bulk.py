"""Dhan historical bulk downloader — plan/dry-run first, spend second.

Purpose: one-time pull of ~3 years of 1-minute NIFTY (optionally BANKNIFTY)
option candles for the instrument-P&L label family (H-001b needs premium
paths, not underlying paths).

SPEND RULE (docs/DATA.md): do NOT subscribe to Dhan Data APIs until
`python scripts/dhan_pull.py --dry-run` output has been reviewed. The
subscription clock must not run while code is still being written.

Everything tagged VERIFY below is unverified lore until checked against
https://dhanhq.co/docs/v2/ with a real account: endpoint paths, auth headers,
per-request date-span limit, rate limits, and the response schema. The
planning half (contract universe + request chunking from our own bhavcopy)
is real and tested; the HTTP half is deliberately thin and isolated in
`_fetch_chunk` so schema surprises stay in one function.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from alpha.data import archive

# VERIFIED 2026-07-08: this api-data path returns HTTP 200 (36 MB); the
# api-scrip path 403s. Columns confirmed against real NIFTY option rows.
INSTRUMENT_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
INTRADAY_CHART_URL = "https://api.dhan.co/v2/charts/intraday"  # VERIFY body/response vs docs/v2
MAX_SPAN_DAYS = 30       # VERIFY per-request date-span limit for 1-min intraday history
REQUEST_SLEEP_S = 0.5    # VERIFY documented rate limit; stay well under it
SOURCE = "dhan"

# Instrument-master columns for the join (verified against the real file).
MASTER_COLS = [
    "EXCH_ID", "SEGMENT", "SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL",
    "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE", "LOT_SIZE",
]


@dataclass
class Chunk:
    """One planned API request: a contract and a date window."""
    symbol: str
    expiry: date
    strike: float
    option_type: str
    start: date
    end: date

    @property
    def key(self) -> str:
        return (f"{self.symbol}_{self.expiry:%Y%m%d}_{self.strike:g}"
                f"{self.option_type}_{self.start:%Y%m%d}_{self.end:%Y%m%d}")

    @property
    def contract_key(self) -> str:
        return contract_key(self.symbol, self.expiry, self.strike, self.option_type)


def contract_key(symbol: str, expiry, strike: float, option_type: str) -> str:
    """Stable key identifying one option contract across bhavcopy and master."""
    return f"{symbol}|{pd.Timestamp(expiry).date()}|{float(strike):g}|{option_type}"


def contract_universe(
    bhav: pd.DataFrame,
    symbol: str = "NIFTY",
    strike_window_pct: float = 0.06,
    min_traded_days: int = 1,
) -> pd.DataFrame:
    """Contracts worth pulling, from our own bhavcopy history.

    Keeps index options of `symbol` whose strike came within
    strike_window_pct of the underlying close on at least one traded day —
    wide enough for ATM structures plus stop/target context, narrow enough
    to keep the request count sane.
    Returns one row per contract: first/last traded date + traded-day count.
    """
    opts = bhav[
        (bhav["symbol"] == symbol)
        & (bhav["instrument"] == "IDO")
        & (bhav["volume"] > 0)
        & bhav["underlying"].notna()
    ].copy()
    if opts.empty:
        raise ValueError(f"no traded {symbol} index options in supplied bhavcopy")

    opts["moneyness"] = (opts["strike"] / opts["underlying"] - 1.0).abs()
    near = opts[opts["moneyness"] <= strike_window_pct]

    grouped = near.groupby(["symbol", "expiry", "strike", "option_type"])
    uni = grouped.agg(
        first_traded=("trade_date", "min"),
        last_traded=("trade_date", "max"),
        traded_days=("trade_date", "nunique"),
    ).reset_index()
    return uni[uni["traded_days"] >= min_traded_days].reset_index(drop=True)


def build_plan(universe: pd.DataFrame, chunk_days: int = MAX_SPAN_DAYS) -> list[Chunk]:
    """Chunk each contract's traded life into <=chunk_days request windows."""
    plan: list[Chunk] = []
    for row in universe.itertuples(index=False):
        start = pd.Timestamp(row.first_traded).date()
        last = pd.Timestamp(row.last_traded).date()
        while start <= last:
            end = min(start + timedelta(days=chunk_days - 1), last)
            plan.append(Chunk(
                symbol=row.symbol,
                expiry=pd.Timestamp(row.expiry).date(),
                strike=float(row.strike),
                option_type=row.option_type,
                start=start,
                end=end,
            ))
            start = end + timedelta(days=1)
    return plan


def summarize_plan(universe: pd.DataFrame, plan: list[Chunk]) -> str:
    est_minutes = len(plan) * REQUEST_SLEEP_S / 60
    lines = [
        f"contracts        : {len(universe):,}",
        f"api requests     : {len(plan):,} (<= {MAX_SPAN_DAYS}-day windows)",
        f"est. wall time   : ~{est_minutes:.0f} min at {REQUEST_SLEEP_S}s/request",
        f"expiries         : {universe['expiry'].nunique():,} "
        f"({pd.Timestamp(universe['expiry'].min()).date()} .. "
        f"{pd.Timestamp(universe['expiry'].max()).date()})",
        "",
        "Review this before subscribing. The pull must comfortably fit the",
        "first few days of one Data-API month, leaving the rest as refetch",
        "buffer after the gap census.",
    ]
    return "\n".join(lines)


INDEX_OPTION_SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
                        "SENSEX", "BANKEX")


def snapshot_index_option_master(
    master_csv: Path, asof_date, root: Path | None = None
) -> Path:
    """Archive today's index-option slice of the master, stamped with the date.

    The full master (36 MB) lists only LIVE contracts — expired ones drop off,
    so ~96% of a 3-year universe is absent from any single day's file. Running
    this daily builds a security_id + lot_size + expiry map FORWARD, which is
    the only free way to make future contracts resolvable once they expire.
    Filtered to index options, a day's slice is a few thousand rows.
    """
    master = pd.read_csv(master_csv, usecols=MASTER_COLS, dtype=str)
    slice_ = master[
        (master["INSTRUMENT"] == "OPTIDX")
        & (master["UNDERLYING_SYMBOL"].isin(INDEX_OPTION_SYMBOLS))
    ]
    payload = slice_.to_csv(index=False).encode()
    relpath = f"master_snapshots/{pd.Timestamp(asof_date):%Y}/index_options_{pd.Timestamp(asof_date):%Y%m%d}.csv"
    return archive.store(SOURCE, relpath, payload, INSTRUMENT_MASTER_URL,
                         meta={"asof": str(asof_date), "rows": len(slice_)},
                         root=root)


def resolve_security_ids(
    universe: pd.DataFrame,
    master_csv: Path,
    symbol: str = "NIFTY",
    exchange: str = "NSE",
) -> dict[str, str]:
    """Map each contract in `universe` to its Dhan SECURITY_ID.

    Joins on (underlying symbol, expiry date, strike, option type) for index
    options (INSTRUMENT == OPTIDX) on the given exchange. Returns
    {contract_key: security_id}. Raises if any universe contract is
    unmatched — a silent drop would quietly shrink the pull.
    """
    master = pd.read_csv(master_csv, usecols=MASTER_COLS, dtype=str)
    opts = master[
        (master["EXCH_ID"] == exchange)
        & (master["INSTRUMENT"] == "OPTIDX")
        & (master["UNDERLYING_SYMBOL"] == symbol)
        & master["OPTION_TYPE"].isin(["CE", "PE"])
    ].copy()
    opts["_key"] = [
        contract_key(symbol, e, s, o)
        for e, s, o in zip(opts["SM_EXPIRY_DATE"], opts["STRIKE_PRICE"],
                           opts["OPTION_TYPE"])
    ]
    lookup = dict(zip(opts["_key"], opts["SECURITY_ID"]))

    resolved: dict[str, str] = {}
    missing = []
    for row in universe.itertuples(index=False):
        key = contract_key(row.symbol, row.expiry, row.strike, row.option_type)
        sid = lookup.get(key)
        if sid is None:
            missing.append(key)
        else:
            resolved[key] = sid
    if missing:
        raise KeyError(
            f"{len(missing)} contracts not found in Dhan master, e.g. "
            f"{missing[:3]}. Expired contracts may be absent from the current "
            f"master — pull those from the daily master snapshot for their era."
        )
    return resolved


def _fetch_chunk(chunk: Chunk, security_id: str, token: str, client_id: str) -> dict:
    """One intraday-chart request. Isolated so schema surprises stay here.

    VERIFY on first authenticated call: exact body field names, header names,
    and response schema (docs/v2). Save the first raw response and eyeball it
    before writing any parser.
    """
    import requests

    body = {  # VERIFY field names against docs/v2 before first run
        "securityId": security_id,
        "exchangeSegment": "NSE_FNO",
        "instrument": "OPTIDX",
        "interval": "1",
        "fromDate": chunk.start.isoformat(),
        "toDate": chunk.end.isoformat(),
    }
    headers = {"access-token": token, "client-id": client_id,
               "Content-Type": "application/json"}
    resp = requests.post(INTRADAY_CHART_URL, json=body, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()


def execute_plan(
    plan: list[Chunk],
    security_ids: dict[str, str],
    root: Path | None = None,
) -> None:
    """Run the pull: every raw response archived immutably before parsing.

    Requires DHAN_ACCESS_TOKEN and DHAN_CLIENT_ID in the environment.
    Resumable: already-archived chunks are skipped, so a crash or a
    rate-limit stop costs nothing.
    """
    token = os.environ.get("DHAN_ACCESS_TOKEN", "").strip()
    client_id = os.environ.get("DHAN_CLIENT_ID", "").strip()
    if not token or not client_id:
        raise RuntimeError(
            "DHAN_ACCESS_TOKEN / DHAN_CLIENT_ID not set. This is the paid "
            "step — see docs/DATA.md for the subscribe-late sequence."
        )
    for i, chunk in enumerate(plan):
        relpath = f"intraday_1m/{chunk.expiry:%Y}/{chunk.key}.json"
        if archive.is_archived(SOURCE, relpath, root):
            continue
        payload = _fetch_chunk(chunk, security_ids[chunk.contract_key], token, client_id)
        archive.store(
            SOURCE, relpath,
            json.dumps(payload).encode(),
            INTRADAY_CHART_URL,
            meta={"chunk": chunk.key},
            root=root,
        )
        if i % 100 == 0:
            print(f"{i}/{len(plan)} chunks archived")
        time.sleep(REQUEST_SLEEP_S)
