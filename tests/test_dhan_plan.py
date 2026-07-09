import pandas as pd
import pytest

from alpha.data import dhan_bulk


def _bhav():
    rows = []
    # 70 trading days of one near-ATM contract, plus one far-OTM contract
    days = pd.bdate_range("2026-03-02", periods=70)
    for d in days:
        rows.append({
            "trade_date": d, "symbol": "NIFTY", "instrument": "IDO",
            "expiry": pd.Timestamp("2026-07-28"), "strike": 24500.0,
            "option_type": "CE", "underlying": 24400.0, "volume": 100,
        })
    rows.append({
        "trade_date": days[0], "symbol": "NIFTY", "instrument": "IDO",
        "expiry": pd.Timestamp("2026-07-28"), "strike": 30000.0,  # ~23% OTM
        "option_type": "CE", "underlying": 24400.0, "volume": 100,
    })
    rows.append({  # untraded contract must be excluded
        "trade_date": days[0], "symbol": "NIFTY", "instrument": "IDO",
        "expiry": pd.Timestamp("2026-07-28"), "strike": 24450.0,
        "option_type": "PE", "underlying": 24400.0, "volume": 0,
    })
    return pd.DataFrame(rows)


def test_universe_filters_moneyness_and_volume():
    uni = dhan_bulk.contract_universe(_bhav(), strike_window_pct=0.06)
    assert len(uni) == 1
    assert uni["strike"].iloc[0] == 24500.0
    assert uni["traded_days"].iloc[0] == 70


def test_plan_chunks_at_max_span():
    uni = dhan_bulk.contract_universe(_bhav())
    plan = dhan_bulk.build_plan(uni, chunk_days=30)
    # 70 bdays span ~96 calendar days -> 4 chunks of <=30 days
    assert 3 <= len(plan) <= 4
    assert all((c.end - c.start).days < 30 for c in plan)
    # chunks tile the traded life without overlap
    for a, b in zip(plan, plan[1:]):
        assert (b.start - a.end).days == 1


def test_execute_refuses_without_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError, match="paid step"):
        dhan_bulk.execute_plan([], {}, root=tmp_path)
