"""Option cost model for a Zerodha retail account.

Fitted to and verified against THREE real Zerodha contract notes
(tests/test_costs_golden.py reproduces their charge lines):
- CNT-26/27-55126969 (2026-07-07): 14 NSE NIFTY option orders.
- CNT-26/27-52636874 (2026-07-02): 22 BSE SENSEX option orders.
- CNT-26/27-51785770 (2026-07-01): 4 BSE SENSEX option orders.
If a rate changes upstream, the golden test failing is a cost-regime change
to investigate — never a test to "fix" silently.

Provenance of each rate (HUMAN-sourced from the notes, not model-assumed):
- brokerage_per_order 20.00 — VERIFIED: flat Rs 20/order cap. NSE note total
  280 = 14 x 20; BSE doc2 total 80 = 4 x 20. (On BSE doc1 some orders were
  split, so total brokerage = 20 x order_count, not 20 x summary_rows.)
- exchange_txn_rate is PER-EXCHANGE (measured, they genuinely differ):
    NSE 3.5529e-4 (0.0355%) — 168.25 / 473,546 turnover.
    BSE 3.25e-4  (0.0325%) — 123.87 / 381,132 and 7.23 / 22,255, agree to
    the 4th decimal across both BSE notes. Includes the IPF contribution.
- sebi_rate 1e-6 (Rs 10/crore, both sides) — VERIFIED across all 3 notes.
- stamp_buy_rate 3e-5 (0.003%, buy side only) — VERIFIED (7.00/233,739;
  6.00/190,304). Sub-rupee amounts round to 0 on some notes.
- stt_sell_rate 1.5e-3 (0.15% of SELL-side premium) — CONFIRMED, ambiguity
  RESOLVED. The 2.6%-asymmetric NSE note discriminates: sell-side predicts
  360.00 to Rs 0.29, both-sides basis is off by Rs 4.84. Matches the
  statutory fact that options STT is levied on the sale only.
- STT on exercised/expired ITM long options is a different, larger-base
  charge — deliberately UNMODELLED because the standing rule is
  sell-to-close, never let ITM expire (README constraints).
- gst_rate 0.18 on (brokerage + exchange txn + SEBI) — VERIFIED on all 3.
"""
from __future__ import annotations

from dataclasses import dataclass

EXCHANGES = ("NSE", "BSE")


@dataclass(frozen=True)
class OrderCharges:
    brokerage: float
    exchange_txn: float
    sebi: float
    stamp: float
    stt: float
    gst: float

    @property
    def total(self) -> float:
        return (self.brokerage + self.exchange_txn + self.sebi
                + self.stamp + self.stt + self.gst)


@dataclass(frozen=True)
class OptionCostModel:
    brokerage_per_order: float = 20.0
    exchange_txn_rate_nse: float = 3.5529e-4
    exchange_txn_rate_bse: float = 3.25e-4
    sebi_rate: float = 1e-6
    stamp_buy_rate: float = 3e-5
    stt_sell_rate: float = 1.5e-3
    gst_rate: float = 0.18

    def _txn_rate(self, exchange: str) -> float:
        rates = {"NSE": self.exchange_txn_rate_nse, "BSE": self.exchange_txn_rate_bse}
        if exchange not in rates:
            raise ValueError(f"exchange must be one of {EXCHANGES}, got {exchange!r}")
        return rates[exchange]

    def order_charges(
        self, side: str, premium_turnover: float, exchange: str = "NSE"
    ) -> OrderCharges:
        """All charges for one executed order. side: 'B' or 'S'.

        premium_turnover = qty x premium in rupees (option premium value,
        not notional). exchange picks the transaction-charge rate (NSE NIFTY
        vs BSE SENSEX differ — measured, not assumed).
        """
        if side not in ("B", "S"):
            raise ValueError(f"side must be 'B' or 'S', got {side!r}")
        if premium_turnover < 0:
            raise ValueError("premium_turnover must be >= 0")
        brokerage = self.brokerage_per_order
        exchange_txn = premium_turnover * self._txn_rate(exchange)
        sebi = premium_turnover * self.sebi_rate
        stamp = premium_turnover * self.stamp_buy_rate if side == "B" else 0.0
        stt = premium_turnover * self.stt_sell_rate if side == "S" else 0.0
        gst = self.gst_rate * (brokerage + exchange_txn + sebi)
        return OrderCharges(brokerage, exchange_txn, sebi, stamp, stt, gst)

    def round_trip_cost(
        self, buy_turnover: float, sell_turnover: float, exchange: str = "NSE"
    ) -> float:
        """Total cost in rupees of one long round trip (buy then sell)."""
        return (self.order_charges("B", buy_turnover, exchange).total
                + self.order_charges("S", sell_turnover, exchange).total)

    def breakeven_move(
        self, entry_premium: float, qty: int, exchange: str = "NSE"
    ) -> float:
        """Minimum premium rise (Rs/unit) for a long round trip to break even.

        This is the cost hurdle every long-premium hypothesis must clear
        (pre-registration requires stating it). Solved by fixed-point
        iteration since STT depends on the (unknown) exit premium.
        """
        if entry_premium <= 0 or qty <= 0:
            raise ValueError("entry_premium and qty must be positive")
        move = 0.0
        for _ in range(8):
            exit_turnover = (entry_premium + move) * qty
            cost = self.round_trip_cost(entry_premium * qty, exit_turnover, exchange)
            move = cost / qty
        return move


#: The model as measured from the user's own account. Studies must reference
#: a named instance (never construct ad-hoc rates inline).
ZERODHA_NSE_OPTIONS_2026_07 = OptionCostModel()
