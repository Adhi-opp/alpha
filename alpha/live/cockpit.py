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
            round-trip at that premium = the REAL live cost hurdle. This
            replaces the 0.25% half-spread ESTIMATE as a display; frozen
            studies keep their registered inputs.
  walls   — per-strike OI concentration + intraday migration. Labelled
            "OI concentration (proxy)" — public chain data supports an
            inference label, never "dealer GEX" (G002 NO-GO stands).
  maxpain — strike minimizing aggregate option payout at expiry, with its
            migration over the session.
  churn   — cumulative |Δ premium| of the ATM pair vs the statutory
            hurdle, alongside the frozen pre-open rating. DESCRIPTIVE
            gross premium churn — deliberately NOT h003.scalp_energy
            (different formula; naming discipline).

NO tickets, no entry arrows, no predictions, no order hooks — ever.
"""
from __future__ import annotations

from collections import deque

from alpha.measure.costs import ZERODHA_NSE_OPTIONS_2026_07 as COST

#: display-context lot sizes (journal-verified 2026-07: NIFTY 65, SENSEX
#: qty rows are multiples of 20). Used only to express costs per lot on
#: screen — never in any study.
LOTS = {"NIFTY": 65, "SENSEX": 20}
#: statutory model is fitted to NSE contract notes; SENSEX rows show
#: quoted spread only until a BSE-fitted model exists
COSTED_SYMBOLS = ("NIFTY",)
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
        elif kind in self.churn:
            self.churn[kind] += 1
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
        out = {}
        for key, st in self.inst.items():
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
        the all-in breakeven (spread paid once + statutory round trip) as a
        % of mid — the number a scalp must beat RIGHT NOW."""
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
                if symbol in COSTED_SYMBOLS and mid > 0:
                    statutory = COST.round_trip_cost(mid * lot, mid * lot)
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
        """Strike minimizing total option payout at expiry settlement —
        standard arithmetic over currently-seen OI, nothing more."""
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
        """Cumulative |Δ premium| of the current ATM pair, per lot, vs the
        statutory round-trip hurdle. DESCRIPTIVE — not h003.scalp_energy."""
        atm = self.atm_strike(symbol)
        if atm is None:
            return {"atm": None}
        opts = self._options(symbol)
        lot = LOTS.get(symbol, 1)
        churn_units = sum(
            (opts.get((atm, s)) or {}).get("cum_abs_dltp", 0.0)
            for s in ("CE", "PE"))
        mids = [(st["bid"] + st["ask"]) / 2
                for s in ("CE", "PE")
                if (st := opts.get((atm, s))) and st.get("bid") and st.get("ask")]
        out = {"atm": atm, "churn_rs_per_lot": round(churn_units * lot, 0),
               "hurdle_rs": None, "hurdle_multiples": None}
        if symbol in COSTED_SYMBOLS and mids:
            mid = sum(mids) / len(mids)
            hurdle = COST.round_trip_cost(mid * lot, mid * lot)
            out["hurdle_rs"] = round(hurdle, 0)
            if hurdle > 0:
                out["hurdle_multiples"] = round(churn_units * lot / hurdle, 1)
        return out

    def snapshot(self) -> dict:
        """Deterministic full-state view (the replay/live agreement and
        determinism tests hash this)."""
        return {
            "counts": dict(sorted(self.counts.items())),
            "spots": dict(sorted(self.spots.items())),
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
