import pandas as pd
import pytest

from alpha.measure.labeler import (
    STOP, TARGET, TIME, TRUNCATED, Barriers, triple_barrier,
)


def _path(bars):
    # bars: list of (high, low, close); timestamps are 1-min apart
    ts = pd.date_range("2026-07-06 09:16", periods=len(bars), freq="1min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "high": [b[0] for b in bars],
        "low": [b[1] for b in bars],
        "close": [b[2] for b in bars],
    })


BARRIERS = Barriers(target=120.0, stop=90.0, max_bars=5)  # entry 100


def test_target_hit_exits_at_target_price():
    path = _path([(105, 99, 104), (121, 110, 119)])
    lab = triple_barrier(path, entry_price=100.0, barriers=BARRIERS)
    assert lab.outcome == TARGET
    assert lab.exit_price == 120.0        # exits AT the barrier, not the high
    assert lab.bars_held == 2
    assert lab.ret == pytest.approx(0.20)
    assert not lab.ambiguous


def test_stop_hit_exits_at_stop_price():
    path = _path([(102, 95, 96), (98, 89, 91)])
    lab = triple_barrier(path, entry_price=100.0, barriers=BARRIERS)
    assert lab.outcome == STOP
    assert lab.exit_price == 90.0
    assert lab.ret == pytest.approx(-0.10)


def test_time_barrier_when_no_touch():
    path = _path([(105, 98, 101)] * 6)   # never reaches 120 or 90
    lab = triple_barrier(path, entry_price=100.0, barriers=BARRIERS)
    assert lab.outcome == TIME
    assert lab.bars_held == 5             # capped at max_bars
    assert lab.exit_price == 101.0        # last in-horizon close


def test_truncated_when_path_ends_before_time_barrier():
    # only 3 bars exist but max_bars is 5, no barrier touched -> missing info
    path = _path([(105, 98, 101), (106, 99, 102), (104, 97, 100)])
    lab = triple_barrier(path, entry_price=100.0, barriers=BARRIERS)
    assert lab.outcome == TRUNCATED
    assert not lab.is_gradeable           # grader must exclude, not score flat


def test_same_bar_ambiguity_resolves_to_stop():
    # one bar straddles both 120 and 90 -> unknowable order -> assume adverse
    path = _path([(125, 85, 100)])
    lab = triple_barrier(path, entry_price=100.0, barriers=BARRIERS)
    assert lab.outcome == STOP
    assert lab.ambiguous
    assert lab.exit_price == 90.0


def test_mae_recorded_even_on_winning_trade():
    # dips to 92 (mae ~ -0.08) before hitting target at 120
    path = _path([(103, 92, 95), (121, 118, 120)])
    lab = triple_barrier(path, entry_price=100.0, barriers=BARRIERS)
    assert lab.outcome == TARGET
    assert lab.mae == pytest.approx(-0.08, abs=1e-9)
    assert lab.mfe >= 0.20


def test_short_direction():
    # direction -1: favorable = price falling. target below, stop above.
    b = Barriers.from_returns(entry=100.0, direction=-1,
                              target_ret=0.20, stop_ret=0.10, max_bars=5)
    assert b.target == pytest.approx(80.0)
    assert b.stop == pytest.approx(110.0)
    path = _path([(101, 95, 97), (85, 79, 80)])
    lab = triple_barrier(path, entry_price=100.0, barriers=b, direction=-1)
    assert lab.outcome == TARGET
    assert lab.ret == pytest.approx(0.20)   # favorable-positive for a short


def test_from_returns_rejects_bad_input():
    with pytest.raises(ValueError):
        Barriers.from_returns(100.0, 0, 0.2, 0.1, 5)
    with pytest.raises(ValueError):
        Barriers.from_returns(100.0, 1, -0.2, 0.1, 5)
