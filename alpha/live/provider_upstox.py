"""Upstox v3 provider: instrument master, front-week chain resolution,
websocket frames, protobuf decode.

Patterns ported from GammaLeak (live-proven there), cleaned: direct wss
connect with a Bearer header, JSON sub/unsub frames, MarketDataFeedV3
protobuf payloads via the official SDK. Field names below were verified by
introspecting the SDK's descriptors, not guessed:

  FeedResponse{type, feeds{key: Feed}, currentTs, marketInfo}
  Feed.fullFeed.marketFF{ltpc{ltp,ltt,ltq,cp}, marketLevel.bidAskQuote
    [Quote{bidQ,bidP,askQ,askP} x5], optionGreeks{delta,theta,gamma,vega,
    rho}, atp, vtt, oi, iv, tbq, tsq}
  Feed.fullFeed.indexFF{ltpc}

SENSEX-vs-SENSEX50 trap (GammaLeak lesson): tradingsymbol prefixes collide;
only the master's `name` column separates underlyings reliably.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date

import requests

from upstox_client.feeder.proto import MarketDataFeedV3_pb2 as pb

MASTER_URL = ("https://assets.upstox.com/market-quote/instruments/"
              "exchange/complete.csv.gz")
WS_URL = "wss://api.upstox.com/v3/feed/market-data-feed"
LTP_URL = "https://api.upstox.com/v2/market-quote/ltp"

#: underlying -> (index instrument_key, derivatives exchange in the master)
INDEX_KEYS = {"NIFTY": "NSE_INDEX|Nifty 50", "SENSEX": "BSE_INDEX|SENSEX"}
SEGMENTS = {"NIFTY": "NSE_FO", "SENSEX": "BSE_FO"}

# GammaLeak-proven compact tradingsymbol split: lazy expiry-code middle,
# 4-5 digit strike (a 6+ digit window would let backtracking steal expiry
# digits into the strike — measured failure, not hypothetical)
_OPT_RE = re.compile(r"^([A-Z]+)(.*?)(\d{4,5})(CE|PE)$")


def _option_fields(r: dict) -> tuple[float, str] | None:
    """(strike, side) from the master row: dedicated columns first (probe
    records whether they exist), tradingsymbol regex as fallback."""
    side = ""
    for col in ("option_type", "instrument_type"):
        v = (r.get(col) or "").strip().upper()
        if v in ("CE", "PE"):
            side = v
            break
    strike = 0.0
    try:
        strike = float(r.get("strike") or 0)
    except (TypeError, ValueError):
        strike = 0.0
    if side and strike > 0:
        return strike, side
    m = _OPT_RE.match(r["tradingsymbol"])
    if m and m.group(1) == r["name"]:
        return float(m.group(3)), m.group(4)
    return None


def parse_master_bytes(payload: bytes) -> list[dict[str, str]]:
    """gz (or plain) CSV -> row dicts. Keeps every column the master offers
    (the probe records which ones actually exist) plus normalized basics."""
    try:
        decoded = gzip.decompress(payload)
    except (EOFError, OSError, gzip.BadGzipFile):
        decoded = payload
    reader = csv.DictReader(io.StringIO(decoded.decode("utf-8-sig")))
    rows = []
    for r in reader:
        ts = (r.get("tradingsymbol") or "").strip().upper()
        key = (r.get("instrument_key") or "").strip()
        exch = (r.get("exchange") or "").strip().upper()
        if not ts or not key or not exch:
            continue
        rows.append({**r, "tradingsymbol": ts, "instrument_key": key,
                     "exchange": exch,
                     "expiry": (r.get("expiry") or "").strip(),
                     "name": (r.get("name") or "").strip().upper()})
    return rows


def load_master(cache_path=None) -> list[dict[str, str]]:
    """Fetch the master from the CDN; fall back to (and refresh) the disk
    cache. Refuses to return empty — a dead master must fail loudly."""
    payload = None
    try:
        resp = requests.get(MASTER_URL, timeout=60)
        resp.raise_for_status()
        payload = resp.content
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(payload)
    except Exception:
        if cache_path is None or not cache_path.exists():
            raise
        payload = cache_path.read_bytes()
    rows = parse_master_bytes(payload)
    if not rows:
        raise RuntimeError("Upstox instrument master parsed empty")
    return rows


@dataclass
class Chain:
    """One underlying's front-week live universe."""
    symbol: str
    expiry: str                                   # YYYY-MM-DD
    index_key: str
    future_key: str | None
    options: dict[tuple[float, str], str]         # (strike, side) -> key
    strikes: list[float] = field(default_factory=list)

    def band_keys(self, strikes: list[float]) -> list[str]:
        return [self.options[(k, s)] for k in strikes for s in ("CE", "PE")
                if (k, s) in self.options]


def front_week_chain(rows: list[dict], symbol: str,
                     today: date | None = None) -> Chain:
    """Nearest-expiry option chain + front future for one underlying.
    Options keep expiry-day contracts (>= today); futures roll (> today)."""
    today_s = str(today or date.today())
    seg = SEGMENTS[symbol]
    opts: list[tuple[str, float, str, str]] = []   # (expiry, strike, side, key)
    futs: list[tuple[str, str]] = []
    for r in rows:
        if r["exchange"] != seg or r["name"] != symbol or not r["expiry"]:
            continue
        opt = _option_fields(r)
        if opt is not None and r["expiry"] >= today_s:
            opts.append((r["expiry"], opt[0], opt[1], r["instrument_key"]))
        elif r["tradingsymbol"].endswith("FUT") and r["expiry"] > today_s:
            futs.append((r["expiry"], r["instrument_key"]))
    if not opts:
        raise RuntimeError(f"no live {symbol} options in master")
    expiry = min(o[0] for o in opts)
    options = {(k, side): key for e, k, side, key in opts if e == expiry}
    strikes = sorted({k for k, _ in options})
    future_key = min(futs)[1] if futs else None
    return Chain(symbol=symbol, expiry=expiry, index_key=INDEX_KEYS[symbol],
                 future_key=future_key, options=options, strikes=strikes)


def select_band(strikes: list[float], spot: float,
                half_width: int = 10) -> list[float]:
    """The static wide band: half_width strikes each side of the strike
    nearest spot, clamped to the listed grid."""
    if not strikes:
        return []
    center = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    return strikes[max(0, center - half_width):center + half_width + 1]


def needs_retarget(band: list[float], spot: float, inner: int = 5) -> bool:
    """Retarget only when spot leaves the inner core of the current band —
    NOT on every ATM shift (subscription churn during a fast move is the
    review-flagged failure mode)."""
    if len(band) < 2 * inner + 1:
        return False
    return not (band[inner] <= spot <= band[-inner - 1])


def build_frame(method: str, keys: list[str], mode: str = "full",
                guid: str = "alpha-live") -> bytes:
    body = {"guid": guid, "method": method,
            "data": {"mode": mode, "instrumentKeys": list(keys)}}
    return json.dumps(body).encode("utf-8")


def _greeks(mf) -> dict:
    g = mf.optionGreeks
    return {"delta": g.delta, "theta": g.theta, "gamma": g.gamma,
            "vega": g.vega, "rho": g.rho}


def _depth(mf) -> list[list[float]]:
    return [[q.bidP, float(q.bidQ), q.askP, float(q.askQ)]
            for q in mf.marketLevel.bidAskQuote]


def decode(raw: bytes) -> list[dict]:
    """One websocket message -> normalized event dicts (no I/O, no state).
    Every event carries the provider's currentTs; the recorder adds the
    local receipt timestamp — both clocks, always."""
    fr = pb.FeedResponse()
    fr.ParseFromString(raw)
    ts = int(fr.currentTs)
    if fr.type == pb.market_info:
        return [{"kind": "market_info", "provider_ts": ts,
                 "segments": dict(fr.marketInfo.segmentStatus)}]
    events = []
    for key, feed in fr.feeds.items():
        union = feed.WhichOneof("FeedUnion")
        if union == "fullFeed":
            full = feed.fullFeed.WhichOneof("FullFeedUnion")
            if full == "marketFF":
                mf = feed.fullFeed.marketFF
                events.append({
                    "kind": "tick", "key": key, "provider_ts": ts,
                    "ltp": mf.ltpc.ltp, "ltt": int(mf.ltpc.ltt),
                    "ltq": int(mf.ltpc.ltq), "cp": mf.ltpc.cp,
                    "atp": mf.atp, "vtt": int(mf.vtt), "oi": mf.oi,
                    "iv": mf.iv, "tbq": mf.tbq, "tsq": mf.tsq,
                    "greeks": _greeks(mf), "depth": _depth(mf),
                })
            elif full == "indexFF":
                lt = feed.fullFeed.indexFF.ltpc
                events.append({"kind": "index", "key": key,
                               "provider_ts": ts, "ltp": lt.ltp,
                               "ltt": int(lt.ltt), "cp": lt.cp})
        elif union == "ltpc":
            events.append({"kind": "ltpc", "key": key, "provider_ts": ts,
                           "ltp": feed.ltpc.ltp, "ltt": int(feed.ltpc.ltt)})
    return events


def rest_ltp(keys: list[str], token: str) -> dict[str, float]:
    """v2 REST LTP sanity check (token + connectivity, pre-websocket)."""
    resp = requests.get(
        LTP_URL, params={"instrument_key": ",".join(keys)},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    return {v.get("instrument_token", k): v.get("last_price")
            for k, v in data.items()}
