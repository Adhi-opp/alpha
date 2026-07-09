import pandas as pd
import pytest

from alpha.measure.costs import ZERODHA_NSE_OPTIONS_2026_07 as CM
from alpha.measure.execution import FillModel
from alpha.measure.grader import NO_FILL, Ticket, grade_ticket, summarize
from alpha.measure.labeler import TRUNCATED

FM = FillModel(delay_bars=1, default_half_spread_frac=0.01)  # 1% half-spread


def _path(bars):
    ts = pd.date_range("2026-07-06 09:16", periods=len(bars), freq="1min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "high": [b[0] for b in bars],
        "low": [b[1] for b in bars],
        "close": [b[2] for b in bars],
    })


def _ticket(acted=True, target=0.20, stop=0.15, max_bars=5):
    return Ticket(ticket_id="t1", signal_time=pd.Timestamp("2026-07-06 09:16", tz="UTC"),
                  qty=75, target_ret=target, stop_ret=stop, max_bars=max_bars, acted=acted)


def test_winner_pnl_is_internally_consistent():
    # bar0 signal, bar1 fill (mid 100 -> ask 101), bar2 spikes through target
    path = _path([(100, 100, 100), (100, 100, 100), (130, 120, 125)])
    g = grade_ticket(_ticket(), path, FM, CM)
    assert g.outcome == "target"
    assert g.entry_price == pytest.approx(101.0)          # paid the ask
    # target = 101 * 1.20 = 121.2 (mid); received the bid = 121.2 * 0.99
    assert g.exit_price == pytest.approx(121.2 * 0.99)
    assert g.gross_pnl == pytest.approx((g.exit_price - g.entry_price) * 75)
    assert g.costs > 0
    assert g.net_pnl == pytest.approx(g.gross_pnl - g.costs)
    assert g.net_pnl < g.gross_pnl                        # costs always bite
    assert g.spread_estimated is True                     # no measured depth yet


def test_loser_hits_stop_and_costs_deepen_the_loss():
    path = _path([(100, 100, 100), (100, 100, 100), (90, 80, 82)])
    g = grade_ticket(_ticket(), path, FM, CM)
    assert g.outcome == "stop"
    assert g.net_pnl < g.gross_pnl < 0


def test_no_fill_when_signal_too_close_to_close():
    path = _path([(100, 100, 100)])   # only the signal bar; delay can't land
    g = grade_ticket(_ticket(), path, FM, CM)
    assert g.outcome == NO_FILL
    assert not g.gradeable
    assert pd.isna(g.net_pnl)


def test_truncated_path_is_not_scored():
    # fills at bar1, then only one post bar with no barrier touch, max_bars=5
    path = _path([(100, 100, 100), (100, 100, 100), (103, 98, 101)])
    g = grade_ticket(_ticket(max_bars=5), path, FM, CM)
    assert g.outcome == TRUNCATED
    assert not g.gradeable
    assert g.mae <= 0 <= g.mfe                            # excursions still kept


def test_abstention_is_graded_counterfactually():
    path = _path([(100, 100, 100), (100, 100, 100), (130, 120, 125)])
    g = grade_ticket(_ticket(acted=False), path, FM, CM)
    assert g.acted is False
    assert g.gradeable                                    # still fully graded
    assert g.net_pnl == pytest.approx(g.gross_pnl - g.costs)


def test_summarize_separates_taken_from_abstained():
    win = _path([(100, 100, 100), (100, 100, 100), (130, 120, 125)])
    lose = _path([(100, 100, 100), (100, 100, 100), (90, 80, 82)])
    graded = [
        grade_ticket(_ticket(acted=True), win, FM, CM),
        grade_ticket(_ticket(acted=True), lose, FM, CM),
        grade_ticket(_ticket(acted=False), win, FM, CM),   # counterfactual
    ]
    s = summarize(graded)
    assert s["taken"]["n"] == 2
    assert s["abstained_counterfactual"]["n"] == 1
    assert s["taken"]["win_rate"] == 0.5
    assert s["spread_estimated"] is True


def test_known_ev_recovered_from_batch():
    # a batch of identical winners: total net must equal n x per-ticket net,
    # and be strictly less than the cost-free gross (the whole point)
    win = _path([(100, 100, 100), (100, 100, 100), (130, 120, 125)])
    graded = [grade_ticket(_ticket(), win, FM, CM) for _ in range(20)]
    s = summarize(graded)
    per = graded[0].net_pnl
    assert s["taken"]["net_pnl_total"] == pytest.approx(20 * per)
    assert s["taken"]["net_pnl_mean"] == pytest.approx(per)
    assert s["taken"]["win_rate"] == 1.0
