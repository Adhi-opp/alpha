"""Golden test: the cost model must reproduce a REAL Zerodha contract note.

Source: tests/fixtures/zerodha_contract_note_2026-07-07.md
(CNT-26/27-55126969), transcribed by the account owner from the PDF.

Turnovers are reconstructed from qty x WAP, and WAP is only given to 2
decimals, so per-line totals carry sub-rupee rounding noise. Tolerances
below reflect that measurement limit, not sloppiness: each statutory line
is asserted to <= Rs 1, and the grand total to <= Rs 2.
"""
from alpha.measure.costs import ZERODHA_NSE_OPTIONS_2026_07 as CM

# (side, qty, wap) — the 14 executed orders from the note.
TRADES = [
    ("B", 260, 151.00), ("S", 260, 134.05),
    ("B", 195, 94.35), ("S", 195, 102.00),
    ("B", 520, 78.83), ("S", 520, 80.96),
    ("B", 1300, 30.25), ("S", 1300, 32.20),
    ("B", 195, 90.15), ("S", 195, 97.15),
    ("B", 325, 119.35), ("S", 325, 126.00),
    ("B", 325, 121.22), ("S", 325, 126.80),
]

# Charge lines from the note (rupees).
NOTE = {
    "brokerage": 280.00,
    "exchange_txn": 168.25,
    "sebi": 0.47,
    "gst": 80.77,
    "stt": 360.00,
    "stamp": 7.00,
    "total": 896.49,
}


def _all_charges():
    charges = [CM.order_charges(side, qty * wap) for side, qty, wap in TRADES]
    return charges


def test_reproduces_every_charge_line():
    charges = _all_charges()
    got = {
        "brokerage": sum(c.brokerage for c in charges),
        "exchange_txn": sum(c.exchange_txn for c in charges),
        "sebi": sum(c.sebi for c in charges),
        "gst": sum(c.gst for c in charges),
        "stt": sum(c.stt for c in charges),
        "stamp": sum(c.stamp for c in charges),
    }
    for line, expected in NOTE.items():
        if line == "total":
            continue
        assert abs(got[line] - expected) <= 1.0, (
            f"{line}: model {got[line]:.2f} vs note {expected:.2f}"
        )


def test_reproduces_total_charges_to_two_rupees():
    total = sum(c.total for c in _all_charges())
    assert abs(total - NOTE["total"]) <= 2.0, f"total {total:.2f} vs 896.49"


def test_brokerage_is_exactly_20_per_order():
    # brokerage is a flat Rs 20/order, capped — no rounding excuse here
    assert sum(c.brokerage for c in _all_charges()) == 20.0 * len(TRADES)


def test_breakeven_move_is_positive_and_sane():
    # a cheap 1-lot (75) NIFTY option must clear a few paise/unit to break even;
    # this is the cost hurdle every long-premium hypothesis must beat.
    move = CM.breakeven_move(entry_premium=100.0, qty=75)
    assert 0 < move < 5.0
    # sanity: hurdle shrinks per-unit as size grows (brokerage amortises)
    assert CM.breakeven_move(100.0, 750) < move
