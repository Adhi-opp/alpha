"""Parsers: archived raw files -> tidy DataFrames stamped with available_at.

available_at is the conservative publication moment (config.PUBLICATION_TIME_IST)
converted to UTC. It is the column the PIT accessor filters on; nothing
downstream may see a row before its available_at.
"""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from alpha.config import IST, PUBLICATION_TIME_IST

# Participant-OI CSV column order after "Client Type" (verified against the
# live file 2026-07-07; same map GammaLeak used in production).
PARTICIPANT_FIELDS = [
    "fut_idx_long", "fut_idx_short", "fut_stk_long", "fut_stk_short",
    "opt_idx_call_long", "opt_idx_put_long", "opt_idx_call_short",
    "opt_idx_put_short", "opt_stk_call_long", "opt_stk_put_long",
    "opt_stk_call_short", "opt_stk_put_short", "total_long", "total_short",
]
PARTICIPANT_TYPES = {"Client", "DII", "FII", "Pro", "TOTAL"}

# UDiFF instrument-type codes; legacy INSTRUMENT values are mapped onto them.
LEGACY_INSTRUMENT_MAP = {
    "FUTIDX": "IDF", "OPTIDX": "IDO", "FUTSTK": "STF", "OPTSTK": "STO",
}

BHAV_COLUMNS = [
    "trade_date", "symbol", "instrument", "expiry", "strike", "option_type",
    "open", "high", "low", "close", "last", "prev_close", "underlying",
    "settle", "oi", "oi_change", "volume", "turnover_inr", "trades", "lot",
    "available_at",
]


def available_at(dataset: str, trade_date: date) -> pd.Timestamp:
    h, m = PUBLICATION_TIME_IST[dataset]
    ist = datetime(trade_date.year, trade_date.month, trade_date.day, h, m,
                   tzinfo=IST)
    return pd.Timestamp(ist).tz_convert("UTC")


def parse_participant_oi(path: Path | str, trade_date: date) -> pd.DataFrame:
    """Parse the fao_participant_oi CSV into one row per participant type.

    Parses positionally (row[0] is the type, then 14 numeric columns) because
    NSE's header cells carry inconsistent trailing whitespace.
    """
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    rows = []
    for row in csv.reader(io.StringIO(text.strip())):
        if not row or row[0].strip() not in PARTICIPANT_TYPES:
            continue
        if len(row) < 15:
            raise ValueError(
                f"participant OI {trade_date}: row for {row[0]!r} has "
                f"{len(row)} columns, expected >=15"
            )
        values = [int(cell.strip().replace(",", "") or 0) for cell in row[1:15]]
        rows.append({"client_type": row[0].strip(),
                     **dict(zip(PARTICIPANT_FIELDS, values))})
    if not rows:
        raise ValueError(f"participant OI {trade_date}: no participant rows found")
    df = pd.DataFrame(rows)
    df.insert(0, "trade_date", pd.Timestamp(trade_date))
    df["available_at"] = available_at("nse_participant_oi", trade_date)
    return df


def _read_zip_csv(zip_path: Path | str) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"{zip_path}: expected exactly one CSV, got {names}")
        return zf.read(names[0]).decode("utf-8-sig", errors="replace")


def _parse_udiff(text: str) -> pd.DataFrame:
    raw = pd.read_csv(io.StringIO(text), dtype=str)
    out = pd.DataFrame({
        "trade_date": pd.to_datetime(raw["TradDt"], format="%Y-%m-%d"),
        "symbol": raw["TckrSymb"].str.strip(),
        "instrument": raw["FinInstrmTp"].str.strip(),
        "expiry": pd.to_datetime(raw["XpryDt"], format="%Y-%m-%d"),
        "strike": pd.to_numeric(raw["StrkPric"], errors="coerce"),
        "option_type": raw["OptnTp"].fillna("").str.strip(),
        "open": pd.to_numeric(raw["OpnPric"], errors="coerce"),
        "high": pd.to_numeric(raw["HghPric"], errors="coerce"),
        "low": pd.to_numeric(raw["LwPric"], errors="coerce"),
        "close": pd.to_numeric(raw["ClsPric"], errors="coerce"),
        "last": pd.to_numeric(raw["LastPric"], errors="coerce"),
        "prev_close": pd.to_numeric(raw["PrvsClsgPric"], errors="coerce"),
        "underlying": pd.to_numeric(raw["UndrlygPric"], errors="coerce"),
        "settle": pd.to_numeric(raw["SttlmPric"], errors="coerce"),
        "oi": pd.to_numeric(raw["OpnIntrst"], errors="coerce"),
        "oi_change": pd.to_numeric(raw["ChngInOpnIntrst"], errors="coerce"),
        "volume": pd.to_numeric(raw["TtlTradgVol"], errors="coerce"),
        "turnover_inr": pd.to_numeric(raw["TtlTrfVal"], errors="coerce"),
        "trades": pd.to_numeric(raw["TtlNbOfTxsExctd"], errors="coerce"),
        "lot": pd.to_numeric(raw["NewBrdLotQty"], errors="coerce"),
    })
    return out


def _parse_legacy(text: str) -> pd.DataFrame:
    raw = pd.read_csv(io.StringIO(text), dtype=str)
    raw.columns = [c.strip() for c in raw.columns]
    instrument = raw["INSTRUMENT"].str.strip().map(LEGACY_INSTRUMENT_MAP)
    option_type = raw["OPTION_TYP"].fillna("").str.strip().replace("XX", "")
    out = pd.DataFrame({
        "trade_date": pd.to_datetime(raw["TIMESTAMP"], format="%d-%b-%Y"),
        "symbol": raw["SYMBOL"].str.strip(),
        "instrument": instrument,
        "expiry": pd.to_datetime(raw["EXPIRY_DT"], format="%d-%b-%Y"),
        "strike": pd.to_numeric(raw["STRIKE_PR"], errors="coerce"),
        "option_type": option_type,
        "open": pd.to_numeric(raw["OPEN"], errors="coerce"),
        "high": pd.to_numeric(raw["HIGH"], errors="coerce"),
        "low": pd.to_numeric(raw["LOW"], errors="coerce"),
        "close": pd.to_numeric(raw["CLOSE"], errors="coerce"),
        "last": float("nan"),
        "prev_close": float("nan"),
        "underlying": float("nan"),  # legacy format has no underlying price column
        "settle": pd.to_numeric(raw["SETTLE_PR"], errors="coerce"),
        "oi": pd.to_numeric(raw["OPEN_INT"], errors="coerce"),
        "oi_change": pd.to_numeric(raw["CHG_IN_OI"], errors="coerce"),
        "volume": pd.to_numeric(raw["CONTRACTS"], errors="coerce"),
        # legacy turnover is in lakh INR; normalise to INR
        "turnover_inr": pd.to_numeric(raw["VAL_INLAKH"], errors="coerce") * 1e5,
        "trades": float("nan"),
        "lot": float("nan"),  # legacy bhavcopy has no lot-size column
    })
    return out


def parse_fo_bhavcopy(zip_path: Path | str) -> pd.DataFrame:
    """Parse a UDiFF or legacy FO bhavcopy zip into the standard schema."""
    text = _read_zip_csv(zip_path)
    header = text.split("\n", 1)[0]
    if header.startswith("TradDt"):
        df = _parse_udiff(text)
    elif header.startswith("INSTRUMENT"):
        df = _parse_legacy(text)
    else:
        raise ValueError(f"{zip_path}: unrecognised bhavcopy header: {header[:80]}")
    df = df[df["symbol"].notna() & (df["symbol"] != "")].reset_index(drop=True)
    trade_dates = df["trade_date"].dt.date.unique()
    if len(trade_dates) != 1:
        raise ValueError(f"{zip_path}: expected one trade date, got {trade_dates}")
    df["available_at"] = available_at("nse_fo_bhavcopy", trade_dates[0])
    return df[BHAV_COLUMNS]
