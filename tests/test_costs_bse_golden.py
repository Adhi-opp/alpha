"""Golden tests for BSE SENSEX notes + the STT-basis resolution.

Sources (transcribed by the account owner from the PDF contract notes):
- CNT-26/27-51785770 (2026-07-01): 2 SENSEX contracts, 4 orders. Clean:
  summary rows == orders, so fully reconstructible.
- CNT-26/27-52636874 (2026-07-02): used for the per-exchange transaction
  rate and the STT-basis check (turnover-based lines only; its brokerage
  came from 22 split orders, not the 20 summary rows).

These confirm two things established this session: BSE's exchange
transaction rate (0.0325%) differs from NSE's (0.0355%), and options STT is
levied on the SELL side (0.15%), not both sides.
"""
import pytest

from alpha.measure.costs import ZERODHA_NSE_OPTIONS_2026_07 as CM

# --- doc2: 4 orders, all BSE SENSEX, (side, qty, wap) ---
DOC2 = [("B", 20, 259.95), ("S", 20, 272.00), ("B", 20, 281.15), ("S", 20, 299.65)]
DOC2_NOTE = {"brokerage": 80.00, "exchange_txn": 7.23, "sebi": 0.02,
             "stt": 17.00, "gst": 15.71}  # stamp shown blank (Rs 0.32 -> 0)


def test_bse_doc2_reconstructs():
    charges = [CM.order_charges(s, q * w, exchange="BSE") for s, q, w in DOC2]
    got = {
        "brokerage": sum(c.brokerage for c in charges),
        "exchange_txn": sum(c.exchange_txn for c in charges),
        "sebi": sum(c.sebi for c in charges),
        "stt": sum(c.stt for c in charges),
        "gst": sum(c.gst for c in charges),
    }
    for line, expected in DOC2_NOTE.items():
        assert abs(got[line] - expected) <= 1.0, f"{line}: {got[line]:.2f} vs {expected}"


def test_bse_exchange_rate_differs_from_nse():
    # doc1 BSE: exchange txn 123.87 on total turnover 381,132
    bse_txn = CM.order_charges("B", 381132.0, exchange="BSE").exchange_txn
    assert bse_txn == pytest.approx(123.87, abs=0.5)
    # same turnover on NSE would cost more (0.0355% vs 0.0325%)
    nse_txn = CM.order_charges("B", 381132.0, exchange="NSE").exchange_txn
    assert nse_txn > bse_txn + 8


def test_stt_is_sell_side_only():
    # the resolution: STT hits the sell, never the buy
    assert CM.order_charges("B", 100000.0).stt == 0.0
    assert CM.order_charges("S", 100000.0).stt == pytest.approx(150.0)


def test_stt_basis_matches_asymmetric_nse_note():
    # original NSE note, buy 233,739.35 / sell 239,806.45 (2.6% asymmetric),
    # STT line 360.00. Sell-side basis must fit far better than both-sides.
    sell_side = CM.order_charges("S", 239806.45).stt          # 0.15% of sell
    both_sides = 0.00075 * (233739.35 + 239806.45)            # 0.075% of total
    assert abs(sell_side - 360.00) < 0.5
    assert abs(both_sides - 360.00) > 4.0                     # the discriminator


def test_unknown_exchange_rejected():
    with pytest.raises(ValueError, match="exchange must be"):
        CM.order_charges("B", 1000.0, exchange="MCX")
