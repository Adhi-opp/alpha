"""Cockpit v1 — descriptive chain views over the recorded event stream.

Altimeter, not co-pilot (docs/LIVE_DESK.md): one PURE reducer consumes the
same normalized events the recorder writes. Live mode tees events into it
straight off the collector path; replay feeds it `replay.events(dir)`.
Live and offline numbers agree because they are the same function over the
same stream — any figure on screen is recomputable from the session dir.

Panels:
  feed    — health: event age, tick rate, market segments, reconnects,
            degraded state. The banner is the first thing that must be
            honest: a stale or degraded feed poisons every other panel.
  hurdle  — top-of-book quoted spread per near-ATM strike + the statutory
            round trip = the INDICATIVE all-in hurdle (labelled indicative
            until it models actual ask entry / projected bid exit with
            fixed-point STT). A display; frozen studies keep their
            registered inputs.
  walls   — per-strike OI concentration + intraday migration over ACTIVE
            subscriptions (retarget-dropped strikes excluded as stale).
            Labelled "OI concentration (proxy)" — public chain data
            supports an inference label, never "dealer GEX" (G002 stands).
  maxpain — captured-band max-pain proxy: band-local (the recorder sees
            ATM+/-10, not the whole chain), stale strikes excluded.
  churn   — ATM pair tick path length (includes bid/ask bounce, grows
            with message frequency — NOT capturable energy; no economic
            multiple is derived), alongside the frozen pre-open rating.
            DESCRIPTIVE — deliberately NOT h003.scalp_energy.

NO tickets, no entry arrows, no predictions, no order hooks — ever.
"""
from __future__ import annotations

from collections import deque

from alpha.measure.costs import ZERODHA_NSE_OPTIONS_2026_07 as COST

#: display-context lot sizes (journal-verified 2026-07: NIFTY 65, SENSEX
#: qty rows are multiples of 20). Used only to express costs per lot on
#: screen — never in any study.
LOTS = {"NIFTY": 65, "SENSEX": 20}
#: statutory model is exchange-aware (calibrated against real NSE and BSE
#: contract notes — measured txn rates differ); both symbols get all-in
#: hurdles
EXCHANGE = {"NIFTY": "NSE", "SENSEX": "BSE"}
_RATE_WINDOW_S = 10.0
#: max-pain migration is sampled every Nth option tick per symbol —
#: event-count-driven (deterministic in replay), and cheap enough for the
#: live recv path where a per-tick O(strikes^2) recompute would not be
MAXPAIN_SAMPLE_EVERY = 500


class Cockpit:
    """Pure event reducer + derived read-only views. apply() must stay
    cheap (dict writes only — it runs on the live recv path) and must
    never touch disk, network, or the wall clock."""

    def __init__(self, instrument_map: dict[str, dict] | None = None):
        self.meta = dict(instrument_map or {})
        self.inst: dict[str, dict] = {}
        self.spots: dict[str, float] = {}
        self.symbols: list[str] = []
        self.expiries: dict[str, str] = {}
        self.segments: dict[str, str] = {}
        self.counts: dict[str, int] = {}
        self.churn = {"sub": 0, "unsub": 0, "retarget_noop": 0}
        self.n_reconnects = 0
        self.n_errors = 0
        self.n_silent = 0
        self.degraded_reason: str | None = None
        self.ended = False
        self.t_first_ns: int | None = None
        self.t_last_ns: int | None = None
        self.last_tick_ns: int | None = None
        self._tick_times: deque[int] = deque(maxlen=4096)
        self._maxpain_hist: dict[str, list[tuple[int, float]]] = {}
        self._mp_ticks: dict[str, int] = {}
        #: keys unsubscribed by retargeting — their last-seen state is
        #: STALE and must not feed walls/max-pain
        self._inactive: set[str] = set()
        self.rating: dict | None = None      # display context, not an event

    # ---- context (not part of the event stream) -------------------------
    def set_rating(self, rating: dict | None) -> None:
        """Attach the frozen pre-open rating row (ledger) for display."""
        self.rating = rating

    # ---- the reducer ----------------------------------------------------
    def apply(self, ev: dict) -> None:
        kind = ev.get("kind")
        self.counts[kind] = self.counts.get(kind, 0) + 1
        t = ev.get("t_local_ns")
        if t is not None:
            if self.t_first_ns is None:
                self.t_first_ns = t
            self.t_last_ns = t

        if kind == "session_start":
            self.symbols = list(ev.get("symbols", []))
            for sym, spot in (ev.get("spots") or {}).items():
                self.spots[sym] = float(spot)
            for sym, chain in (ev.get("chains") or {}).items():
                self.expiries[sym] = chain.get("expiry")
        elif kind == "tick":
            self._tick(ev)
        elif kind == "index":
            sym = self.meta.get(ev.get("key"), {}).get("symbol")
            if sym and ev.get("ltp"):
                self.spots[sym] = float(ev["ltp"])
            if t is not None:
                self.last_tick_ns = t
                self._tick_times.append(t)
        elif kind == "market_info":
            self.segments = dict(ev.get("segments") or {})
        elif kind == "ws_connected":
            if ev.get("attempt", 1) > 1:
                self.n_reconnects += 1
        elif kind == "ws_error":
            self.n_errors += 1
        elif kind == "ws_silent":
            self.n_silent += 1
        elif kind == "sub":
            self.churn["sub"] += 1
            self._inactive.difference_update(ev.get("keys") or [])
        elif kind == "unsub":
            self.churn["unsub"] += 1
            self._inactive.update(ev.get("keys") or [])
        elif kind == "retarget_noop":
            self.churn["retarget_noop"] += 1
        elif kind == "session_end":
            self.ended = True
            self.degraded_reason = ev.get("degraded_reason")

    def _tick(self, ev: dict) -> None:
        key = ev["key"]
        s = self.inst.get(key)
        if s is None:
            s = self.inst[key] = {
                "n": 0, "ltp": None, "cp": None, "oi": None,
                "oi_open": None, "iv": None, "bid": None, "ask": None,
                "bid_q": None, "ask_q": None, "ltt": None,
                "cum_abs_dltp": 0.0,
            }
        ltp = ev.get("ltp") or None
        if ltp and s["ltp"]:
            s["cum_abs_dltp"] += abs(float(ltp) - float(s["ltp"]))
        if ltp:
            s["ltp"] = float(ltp)
        s["n"] += 1
        if ev.get("cp"):
            s["cp"] = float(ev["cp"])
        oi = ev.get("oi")
        if oi is not None and oi > 0:
            if s["oi_open"] is None:
                s["oi_open"] = float(oi)
            s["oi"] = float(oi)
        if ev.get("iv"):
            s["iv"] = float(ev["iv"])
        if ev.get("ltt"):
            s["ltt"] = int(ev["ltt"])
        depth = ev.get("depth") or []
        if depth and depth[0]:
            bid_p, bid_q, ask_p, ask_q = depth[0][:4]
            if bid_p or ask_p:
                s["bid"], s["bid_q"] = float(bid_p), float(bid_q)
                s["ask"], s["ask_q"] = float(ask_p), float(ask_q)
        t = ev.get("t_local_ns")
        if t is not None:
            self.last_tick_ns = t
            self._tick_times.append(t)
        sym = self.meta.get(key, {}).get("symbol")
        if sym and oi is not None:
            n = self._mp_ticks.get(sym, 0) + 1
            self._mp_ticks[sym] = n
            if n % MAXPAIN_SAMPLE_EVERY == 1:      # first oi tick, then every Nth
                mp = self.max_pain(sym).get("strike")
                hist = self._maxpain_hist.setdefault(sym, [])
                if mp is not None and (not hist or hist[-1][1] != mp):
                    hist.append((int(t or 0), float(mp)))

    # ---- derived views (pure reads) -------------------------------------
    def _options(self, symbol: str) -> dict[tuple[float, str], dict]:
        """Active option states only — an unsubscribed strike's last-seen
        values are stale by definition and are excluded until re-subbed."""
        out = {}
        for key, st in self.inst.items():
            if key in self._inactive:
                continue
            m = self.meta.get(key)
            if (m and m.get("symbol") == symbol
                    and m.get("kind") == "option"):
                out[(float(m["strike"]), m["side"])] = st
        return out

    def feed_health(self, now_ns: int | None = None) -> dict:
        now_ns = now_ns if now_ns is not None else self.t_last_ns
        age = ((now_ns - self.last_tick_ns) / 1e9
               if now_ns is not None and self.last_tick_ns else None)
        cutoff = (now_ns or 0) - int(_RATE_WINDOW_S * 1e9)
        rate = (sum(1 for t in self._tick_times if t >= cutoff)
                / _RATE_WINDOW_S if now_ns else 0.0)
        gate_open = (bool(self.segments)
                     and all(self.segments.get(s) == "NORMAL_OPEN"
                             for s in ("NSE_FO", "BSE_FO")))
        if self.degraded_reason:
            banner = f"DEGRADED — {self.degraded_reason}"
        elif self.ended:
            banner = "SESSION ENDED"
        elif self.segments and not gate_open:
            banner = "MARKET CLOSED (per provider)"
        elif age is not None and age > 15:
            banner = f"STALE FEED — last tick {age:.0f}s ago"
        else:
            banner = "OK"
        return {"banner": banner, "last_tick_age_s": age,
                "tick_rate_10s": round(rate, 1),
                "n_instruments": len(self.inst),
                "segments_gate_open": gate_open,
                "reconnects": self.n_reconnects, "errors": self.n_errors,
                "silent_timeouts": self.n_silent,
                "subscription_churn": dict(self.churn),
                "degraded_reason": self.degraded_reason,
                "ended": self.ended}

    def atm_strike(self, symbol: str) -> float | None:
        spot = self.spots.get(symbol)
        strikes = sorted({k for k, _ in self._options(symbol)})
        if spot is None or not strikes:
            return None
        return min(strikes, key=lambda k: abs(k - spot))

    def spread_table(self, symbol: str, width: int = 3) -> list[dict]:
        """ATM +/- width strikes, both sides: quoted top-of-book spread and
        the INDICATIVE all-in hurdle (spread paid once + statutory round
        trip, both at mid turnover) as a % of mid. Indicative until it uses
        actual ask entry / projected bid exit with the cost model's
        fixed-point STT — labelled so on screen."""
        atm = self.atm_strike(symbol)
        opts = self._options(symbol)
        if atm is None:
            return []
        strikes = sorted({k for k, _ in opts})
        i = strikes.index(atm)
        window = strikes[max(0, i - width):i + width + 1]
        lot = LOTS.get(symbol, 1)
        rows = []
        for k in window:
            for side in ("CE", "PE"):
                st = opts.get((k, side))
                if not st or not st.get("bid") or not st.get("ask"):
                    rows.append({"strike": k, "side": side, "bid": None,
                                 "ask": None, "mid": None, "spread": None,
                                 "spread_pct": None, "breakeven_pct": None})
                    continue
                bid, ask = st["bid"], st["ask"]
                mid = (bid + ask) / 2
                spread = ask - bid
                row = {"strike": k, "side": side, "bid": bid, "ask": ask,
                       "mid": round(mid, 2), "spread": round(spread, 2),
                       "spread_pct": round(spread / mid * 100, 2),
                       "breakeven_pct": None}
                exch = EXCHANGE.get(symbol)
                if exch and mid > 0:
                    statutory = COST.round_trip_cost(mid * lot, mid * lot,
                                                     exchange=exch)
                    row["breakeven_pct"] = round(
                        (spread * lot + statutory) / (mid * lot) * 100, 2)
                rows.append(row)
        return rows

    def oi_walls(self, symbol: str, top: int = 5) -> list[dict]:
        """OI concentration (proxy) by strike, with intraday migration
        (delta vs first-seen OI). Inference label — never 'dealer GEX'."""
        by_strike: dict[float, dict] = {}
        for (k, side), st in self._options(symbol).items():
            if st.get("oi") is None:
                continue
            row = by_strike.setdefault(
                k, {"strike": k, "ce_oi": 0.0, "pe_oi": 0.0,
                    "d_ce": 0.0, "d_pe": 0.0})
            row["ce_oi" if side == "CE" else "pe_oi"] += st["oi"]
            row["d_ce" if side == "CE" else "d_pe"] += (
                st["oi"] - (st["oi_open"] or st["oi"]))
        rows = sorted(by_strike.values(),
                      key=lambda r: r["ce_oi"] + r["pe_oi"], reverse=True)
        return rows[:top]

    def max_pain(self, symbol: str) -> dict:
        """CAPTURED-BAND max-pain proxy: the payout-minimizing strike over
        the OI of currently-subscribed instruments only. The recorder sees
        ATM+/-10, not the complete chain, and retarget-dropped strikes are
        excluded as stale — so this is a band-local proxy, never the
        market-wide max pain quoted elsewhere."""
        opts = self._options(symbol)
        strikes = sorted({k for (k, _), st in opts.items()
                          if st.get("oi") is not None})
        if not strikes:
            return {"strike": None, "history": []}
        best, best_pay = None, None
        for settle in strikes:
            pay = 0.0
            for (k, side), st in opts.items():
                oi = st.get("oi")
                if oi is None:
                    continue
                if side == "CE":
                    pay += oi * max(0.0, settle - k)
                else:
                    pay += oi * max(0.0, k - settle)
            if best_pay is None or pay < best_pay:
                best, best_pay = settle, pay
        return {"strike": best,
                "history": list(self._maxpain_hist.get(symbol, []))}

    def churn_panel(self, symbol: str) -> dict:
        """Cumulative tick-by-tick |ΔLTP| of the current ATM pair, per lot.
        This is LTP PATH LENGTH: it includes bid/ask bounce, grows with
        message frequency, and is NOT capturable trading energy — no
        economic multiple is derived from it (an earlier draft compared it
        to one round-trip hurdle; that comparison was misleading and is
        deliberately absent). DESCRIPTIVE — not h003.scalp_energy."""
        atm = self.atm_strike(symbol)
        if atm is None:
            return {"atm": None}
        opts = self._options(symbol)
        lot = LOTS.get(symbol, 1)
        churn_units = sum(
            (opts.get((atm, s)) or {}).get("cum_abs_dltp", 0.0)
            for s in ("CE", "PE"))
        return {"atm": atm,
                "tick_path_rs_per_lot": round(churn_units * lot, 0)}

    def snapshot(self) -> dict:
        """Deterministic full-state view (the replay/live agreement and
        determinism tests hash this; the browser renders it verbatim)."""
        return {
            "counts": dict(sorted(self.counts.items())),
            "spots": dict(sorted(self.spots.items())),
            "expiries": dict(sorted(self.expiries.items())),
            "segments": dict(sorted(self.segments.items())),
            "health": self.feed_health(),
            "per_symbol": {
                sym: {"atm": self.atm_strike(sym),
                      "max_pain": self.max_pain(sym),
                      "walls": self.oi_walls(sym),
                      "spread": self.spread_table(sym),
                      "churn": self.churn_panel(sym)}
                for sym in sorted(self.symbols)
            },
        }


# ---- runtime bridge (cockpit process -> console webpage) ----------------
#
# The live cockpit atomically replaces a small JSON file every ~2 s; the
# console (which may NOT import this package — firewall) reads and serves
# it over SSE. Publishing must never be able to disturb the capture: it
# runs in the render task (never the recv path), and failures return False
# instead of raising.

RUNTIME_SCHEMA = "cockpit-runtime-v1"
#: only these capture-metadata keys may cross the bridge — never the
#: token, never raw frames
_CAPTURE_FIELDS = ("run_id", "label", "day", "queue_high_water",
                   "queue_max", "queue_overflows", "degraded_reason")


def runtime_payload(cp: Cockpit, run: dict, mode: str = "live",
                    now_ns: int | None = None) -> dict:
    """The full browser contract: reducer snapshot + run identity +
    bounded capture telemetry. No calculations happen downstream of this
    — the page formats these values, nothing more."""
    import time as _time
    now_ns = now_ns if now_ns is not None else _time.time_ns()
    return {
        "schema": RUNTIME_SCHEMA,
        "mode": mode,                          # "live" | "replay"
        "published_at_ns": now_ns,
        "run": {k: run.get(k) for k in _CAPTURE_FIELDS},
        "rating": cp.rating,
        "snapshot": cp.snapshot() if mode == "replay"
        else {**cp.snapshot(), "health": cp.feed_health(now_ns)},
    }


def publish_runtime(payload: dict, path=None) -> bool:
    """Atomic tmp+replace write of the runtime file. Returns False on ANY
    failure — the bridge is best-effort by design; recording must never
    depend on it."""
    import json
    import os
    from alpha.config import LIVE_RUNTIME_SNAPSHOT
    target = path or LIVE_RUNTIME_SNAPSHOT
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"), default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        return True
    except OSError:
        return False
