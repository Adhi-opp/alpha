r"""One cheap, SAFE authenticated probe of Dhan's EXPIRED-OPTIONS endpoint.

Target: POST /v2/charts/rollingoption (docs/DHAN_FINDINGS.md). Answers the
open VERIFY items before any bulk pull spends the Dhan Pro month:
  1. expiryCode semantics — does 0 mean the front expiry, rolling across the
     requested window?
  2. The correct exchangeSegment/instrument enums and the NIFTY underlying
     securityId (read from our archived instrument master, not guessed).
  3. Response reality: timestamp convention (epoch/tz), array alignment,
     whether iv/oi/strike/spot arrive as documented.

Every raw response is archived under data/raw/dhan/_probe/ so the rolling
client is written against reality, never a guess.

SAFETY: credentials come from .env (gitignored) or the environment — never
from code or arguments. Dhan tokens expire ~daily; on HTTP 401 generate a
fresh one in the DhanHQ console and update .env.

Usage:
  d:\alpha\.venv\Scripts\python scripts\dhan_probe.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import requests

from alpha.config import PROJECT_ROOT
from alpha.data import archive, dhan_bulk

ROLLING_URL = "https://api.dhan.co/v2/charts/rollingoption"
IST = timezone(timedelta(hours=5, minutes=30))


def load_env() -> dict[str, str]:
    """Minimal .env parser — no extra dependency for two variables."""
    env: dict[str, str] = {}
    envfile = PROJECT_ROOT / ".env"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    import os
    for k in ("DHAN_ACCESS_TOKEN", "DHAN_CLIENT_ID"):
        env.setdefault(k, os.environ.get(k, ""))
    return env


def nifty_underlying_id() -> str:
    master = archive.path_of("dhan", "instrument_master/api-scrip-master-detailed.csv")
    if not master.exists():
        raise SystemExit("instrument master not archived — run dhan_pull.py --fetch-master")
    m = pd.read_csv(master, usecols=["EXCH_ID", "INSTRUMENT", "UNDERLYING_SYMBOL",
                                     "UNDERLYING_SECURITY_ID"], dtype=str)
    rows = m[(m.EXCH_ID == "NSE") & (m.INSTRUMENT == "OPTIDX")
             & (m.UNDERLYING_SYMBOL == "NIFTY")]
    ids = rows["UNDERLYING_SECURITY_ID"].dropna().unique()
    if len(ids) != 1:
        print(f"note: {len(ids)} distinct underlying ids in master: {ids[:5]}")
    return ids[0]


def probe_once(token: str, client_id: str, security_id: str,
               expiry_code: int, segment: str = "NSE_FNO") -> tuple[int, object]:
    body = {
        "exchangeSegment": segment,
        "interval": 1,
        "securityId": str(security_id),
        "instrument": "OPTIDX",
        "expiryCode": expiry_code,
        "expiryFlag": "WEEK",
        "strike": "ATM",
        "drvOptionType": "CALL",
        "requiredData": ["open", "high", "low", "close", "volume",
                         "iv", "oi", "strike", "spot"],
        "fromDate": "2026-06-29",
        "toDate": "2026-07-03",   # docs: end non-inclusive; spans one full week-cycle start
    }
    headers = {"access-token": token, "client-id": client_id,
               "Content-Type": "application/json", "Accept": "application/json"}
    r = requests.post(ROLLING_URL, json=body, headers=headers, timeout=60)
    try:
        payload = r.json()
    except ValueError:
        payload = r.text[:400]
    return r.status_code, payload


def describe(payload: object) -> str:
    if not isinstance(payload, dict):
        return f"non-JSON: {payload!r}"
    data = payload.get("data") or {}
    ce = data.get("ce") or {}
    if not ce:
        return f"keys={list(payload)[:6]} (no data.ce) body~{json.dumps(payload)[:200]}"
    ts = ce.get("timestamp") or []
    close = ce.get("close") or []
    strike = ce.get("strike") or []
    spot = ce.get("spot") or []
    iv = ce.get("iv") or []
    out = [f"candles={len(close)}"]
    if ts:
        t0 = datetime.fromtimestamp(ts[0], tz=IST)
        t1 = datetime.fromtimestamp(ts[-1], tz=IST)
        out.append(f"span {t0:%Y-%m-%d %H:%M} .. {t1:%Y-%m-%d %H:%M} IST")
    if strike and spot:
        out.append(f"first strike={strike[0]} spot={spot[0]}")
    if iv:
        out.append(f"iv[0]={iv[0]}")
    return "  ".join(out)


def main() -> int:
    env = load_env()
    token, client_id = env.get("DHAN_ACCESS_TOKEN", ""), env.get("DHAN_CLIENT_ID", "")
    if not token or not client_id:
        print("DHAN_ACCESS_TOKEN / DHAN_CLIENT_ID missing — put them in .env")
        return 1

    sid = nifty_underlying_id()
    print(f"NIFTY underlying securityId from master: {sid}\n")

    for expiry_code in (0, 1):
        status, payload = probe_once(token, client_id, sid, expiry_code)
        print(f"expiryCode={expiry_code} -> HTTP {status}: {describe(payload)}")
        if status == 401:
            print("token rejected/expired — generate a fresh one in the DhanHQ console")
            return 1
        if isinstance(payload, (dict, list)):
            relpath = f"_probe/rollingoption_ec{expiry_code}_{datetime.now():%Y%m%d}.json"
            p = archive.store("dhan", relpath, json.dumps(payload).encode(),
                              ROLLING_URL, meta={"expiryCode": expiry_code,
                                                 "securityId": str(sid)})
            print(f"  raw response archived -> {p}")
    print("\nRead the archived responses before writing dhan_rolling.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
