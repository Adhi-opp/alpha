import pandas as pd
import pytest

from alpha.measure.execution import FillModel


def _path(closes):
    ts = pd.date_range("2026-07-06 09:16", periods=len(closes), freq="1min", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "close": list(closes)})


def test_delay_fills_at_later_bar_not_signal_price():
    # signal bar close 100; market moves to 103 two bars later
    path = _path([100, 102, 103, 104])
    fm = FillModel(delay_bars=2, default_half_spread_frac=0.0)
    fill = fm.fill("B", path)
    assert fill.reference_mid == 103.0        # NOT the 100 signal price
    assert fill.fill_time == path["timestamp"].iloc[2]


def test_buyer_pays_ask_seller_hits_bid():
    path = _path([100, 100, 100])
    fm = FillModel(delay_bars=1, default_half_spread_frac=0.01)  # 1% half-spread
    buy = fm.fill("B", path)
    sell = fm.fill("S", path)
    assert buy.fill_price == pytest.approx(101.0)   # pays up
    assert sell.fill_price == pytest.approx(99.0)   # receives less
    assert buy.half_spread_paid == pytest.approx(1.0)


def test_missing_spread_raises_never_assumes_zero():
    path = _path([100, 100])
    fm = FillModel(delay_bars=1)  # no default spread
    with pytest.raises(ValueError, match="half_spread_frac is required"):
        fm.fill("B", path)


def test_spread_marked_estimated_until_measured_depth():
    path = _path([100, 100])
    fm = FillModel(delay_bars=1, default_half_spread_frac=0.005)
    assert fm.fill("B", path).spread_estimated is True
    fm2 = FillModel(delay_bars=1, default_half_spread_frac=0.005,
                    spread_is_measured=True)
    assert fm2.fill("B", path).spread_estimated is False


def test_cannot_fill_when_signal_too_close_to_close():
    path = _path([100, 101])           # only 2 bars
    fm = FillModel(delay_bars=3, default_half_spread_frac=0.0)
    assert fm.fill("B", path) is None  # a real "could not trade", not a free fill


def test_per_call_spread_overrides_default():
    path = _path([100, 100])
    fm = FillModel(delay_bars=1, default_half_spread_frac=0.005)
    fill = fm.fill("B", path, half_spread_frac=0.02)
    assert fill.fill_price == pytest.approx(102.0)
