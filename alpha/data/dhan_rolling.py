"""Dhan expired-options ROLLING client — constants verified live 2026-07-09.

Verified against real responses (data/raw/dhan/_probe/):
- POST https://api.dhan.co/v2/charts/rollingoption
- securityId = the UNDERLYING INDEX id from Dhan's own master INDEX row
  (NIFTY = "13"). NSE's underlying id (26000) returns HTTP 200 + empty.
- exchangeSegment = "NSE_FNO" (IDX_I returns empty).
- expiryCode is 1-INDEXED: 1 = front weekly (rolls to the next contract the
  morning after expiry — verified across the 2026-06-30 expiry), 2 = next.
  0 is rejected by a falsy server-side "required" check.
- toDate is INCLUSIVE (docs say non-inclusive; reality wins).
- Sessions come back complete: 375 one-minute candles 09:15..15:29 IST.
- Response arrays: open/high/low/close/volume/oi/iv/strike/spot/timestamp
  (epoch seconds). iv is 0.0 on the expiring contract's final candles.
- The series is a rolling-ATM COMPOSITE: the per-candle `strike` re-selects
  as spot moves. A tradeable fixed-strike path must be reconstructed by
  pulling the ATM+/-k offset fan and re-keying rows by (timestamp, strike,
  side) — which is exactly what the tidy parquet layer does.
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from alpha.data import archive

ROLLING_URL = "https://api.dhan.co/v2/charts/rollingoption"
SOURCE = "dhan"
NIFTY_UNDERLYING_ID = "13"     # from master INDEX row, verified live
MAX_SPAN_DAYS = 30             # per-call window; toDate inclusive
REQUEST_SLEEP_S = 0.5
FIELDS = ["open", "high", "low", "close", "volume", "iv", "oi", "strike", "spot"]


def offset_str(k: int) -> str:
    return "ATM" if k == 0 else (f"ATM+{k}" if k > 0 else f"ATM{k}")


def windows(start: date, end: date, span: int = MAX_SPAN_DAYS) -> list[tuple[date, date]]:
    out, s = [], start
    while s <= end:
        e = min(s + timedelta(days=span - 1), end)   # inclusive toDate
        out.append((s, e))
        s = e + timedelta(days=1)
    return out


def plan_pull(start: date, end: date, offsets: range = range(-10, 11),
              sides: tuple[str, ...] = ("CALL", "PUT"), expiry_code: int = 1) -> list[dict]:
    return [
        {"offset": k, "side": side, "expiry_code": expiry_code, "start": s, "end": e}
        for k in offsets for side in sides for (s, e) in windows(start, end)
    ]


def _relpath(job: dict, symbol: str = "NIFTY") -> str:
    return (f"rolling_1m/{symbol}/ec{job['expiry_code']}/{job['side']}/"
            f"{offset_str(job['offset'])}/{job['start']:%Y%m%d}_{job['end']:%Y%m%d}.json")


#: SENSEX: Dhan's own INDEX-row id, verified live 2026-07-11 (BSE_FNO,
#: 375 candles/session). The options rows' UNDERLYING_SECURITY_ID "1" is
#: the same silent HTTP-200-empty trap NIFTY's 26000 was.
SENSEX_UNDERLYING_ID = "51"


def fetch_job(job: dict, token: str, client_id: str,
              security_id: str = NIFTY_UNDERLYING_ID,
              exchange_segment: str = "NSE_FNO") -> dict:
    body = {
        "exchangeSegment": exchange_segment,
        "interval": 1,
        "securityId": security_id,
        "instrument": "OPTIDX",
        "expiryCode": job["expiry_code"],
        "expiryFlag": "WEEK",
        "strike": offset_str(job["offset"]),
        "drvOptionType": job["side"],
        "requiredData": FIELDS,
        "fromDate": job["start"].isoformat(),
        "toDate": job["end"].isoformat(),
    }
    headers = {"access-token": token, "client-id": client_id,
               "Content-Type": "application/json", "Accept": "application/json"}
    r = requests.post(ROLLING_URL, json=body, headers=headers, timeout=90)
    r.raise_for_status()
    return r.json()


def execute_pull(plan: list[dict], token: str, client_id: str,
                 symbol: str = "NIFTY", root: Path | None = None,
                 security_id: str = NIFTY_UNDERLYING_ID,
                 exchange_segment: str = "NSE_FNO") -> dict:
    """Archive every raw response. Resumable: archived jobs are skipped."""
    done = skipped = empty = 0
    for job in plan:
        rel = _relpath(job, symbol)
        if archive.is_archived(SOURCE, rel, root):
            skipped += 1
            continue
        payload = fetch_job(job, token, client_id, security_id,
                            exchange_segment)
        side_key = "ce" if job["side"] == "CALL" else "pe"
        n = len(((payload.get("data") or {}).get(side_key) or {}).get("close") or [])
        if n == 0:
            empty += 1
        archive.store(SOURCE, rel, json.dumps(payload).encode(), ROLLING_URL,
                      meta={**{k: str(v) for k, v in job.items()}, "candles": n},
                      root=root)
        done += 1
        if done % 50 == 0:
            print(f"progress: {done} fetched, {skipped} cached, {empty} empty",
                  flush=True)
        time.sleep(REQUEST_SLEEP_S)
    return {"fetched": done, "cached": skipped, "empty": empty}


def payload_to_frame(payload: dict, side: str) -> pd.DataFrame:
    """One raw response -> tidy rows keyed by (timestamp, strike, side)."""
    key = "ce" if side == "CALL" else "pe"
    d = (payload.get("data") or {}).get(key) or {}
    if not d.get("timestamp"):
        return pd.DataFrame()
    df = pd.DataFrame({f: d.get(f, []) for f in ["timestamp", *FIELDS]})
    df["ts"] = pd.to_datetime(df.pop("timestamp"), unit="s", utc=True)
    df["side"] = "CE" if side == "CALL" else "PE"
    return df


def tidy_archive_to_parquet(root: Path | None = None, symbol: str = "NIFTY",
                            out_dataset: str = "dhan_rolling_1m") -> int:
    """All archived raw JSONs -> one deduplicated tidy parquet per year.

    Rows: ts (UTC), side, strike, open..close, volume, oi, iv, spot, offset,
    expiry_code. Duplicate (ts, strike, side) rows from overlapping offsets
    keep the first seen. available_at = end of the bar's trading day (these
    are pure-history OUTCOME paths, never conditioning).
    """
    from alpha.config import DERIVED_ROOT, IST
    base = (root or archive.RAW_ROOT) / SOURCE / "rolling_1m" / symbol
    frames = []
    for p in sorted(base.rglob("*.json")):
        if p.name.endswith(".manifest.json"):
            continue
        side = "CALL" if "/CALL/" in str(p).replace("\\", "/") else "PUT"
        df = payload_to_frame(json.loads(p.read_text()), side)
        if df.empty:
            continue
        parts = str(p).replace("\\", "/").split("/")
        df["offset"] = parts[-2]
        df["expiry_code"] = int(parts[-4].removeprefix("ec"))
        frames.append(df)
    if not frames:
        return 0
    allf = pd.concat(frames, ignore_index=True)
    allf = allf.drop_duplicates(subset=["ts", "strike", "side"], keep="first")
    ist_day_end = allf["ts"].dt.tz_convert(IST).dt.normalize() + pd.Timedelta(hours=15, minutes=35)
    allf["available_at"] = ist_day_end.dt.tz_convert("UTC")
    allf["trade_date"] = allf["ts"].dt.tz_convert(IST).dt.normalize().dt.tz_localize(None)
    out_dir = DERIVED_ROOT / out_dataset
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for year, chunk in allf.groupby(allf["trade_date"].dt.year):
        path = out_dir / f"{year}.parquet"
        if path.exists():
            prior = pd.read_parquet(path)
            chunk = pd.concat([prior, chunk], ignore_index=True).drop_duplicates(
                subset=["ts", "strike", "side"], keep="first")
        chunk.sort_values(["ts", "side", "strike"]).to_parquet(path, index=False)
        n += len(chunk)
    return n
