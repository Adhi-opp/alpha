from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from alpha.study import h004


def _wi_frame(n: int, last_gap_days: int, session: pd.Timestamp) -> pd.DataFrame:
    dates = pd.date_range(end=session - pd.Timedelta(days=last_gap_days),
                          periods=n, freq="B")
    return pd.DataFrame({"trade_date": dates,
                         "wi": np.linspace(0.3, 0.7, n)})


def test_rating_stale_guard_and_history_floor():
    session = pd.Timestamp("2026-08-04")
    # fresh file within the 4-day console guard -> rated
    assert h004._rating_for(session, _wi_frame(60, 1, session)) is not None
    assert h004._rating_for(session, _wi_frame(60, 4, session)) is not None
    # fetch dead for 5+ days -> the console showed nothing -> unrated
    assert h004._rating_for(session, _wi_frame(60, 5, session)) is None
    # under the 20-file history floor -> unrated
    assert h004._rating_for(session, _wi_frame(19, 1, session)) is None


def test_rating_percentile_matches_owner_log_formula():
    session = pd.Timestamp("2026-08-04")
    wi = _wi_frame(60, 1, session)
    # monotone increasing wi -> the latest value is the max of its window
    assert h004._rating_for(session, wi) == 100.0
    wi.loc[wi.index[-1], "wi"] = -1.0     # latest is the minimum
    assert h004._rating_for(session, wi) == pytest.approx(round(100 / 60, 1))


def _frame(n: int, rng: np.random.Generator, breach: bool = False,
           flip_clean: bool = False) -> pd.DataFrame:
    x = np.linspace(5, 95, n)
    y = 60.0 * x + rng.normal(0, 300, n)          # strong positive association
    if breach:
        y[n // 2] = -7000.0
    y_clean = -y if flip_clean else y.copy()
    return pd.DataFrame({
        "session_date": pd.date_range("2026-07-14", periods=n, freq="7D"),
        "wi_pctile": x, "day_net_pnl": y,
        "abstained": [i % 5 == 0 for i in range(n)],
        "y_clean": y_clean,
    })


_HOLDOUT_PASS = {"holdout_n": 24, "holdout_rho": 0.21, "dev_rho": 0.287,
                 "combined_n": 102, "combined_rho": 0.26,
                 "combined_ci": [0.09, 0.42], "combined_p": 0.004,
                 "same_sign": True}


def test_single_look_guard_refuses_early(monkeypatch):
    rng = np.random.default_rng(0)
    monkeypatch.setattr(h004, "assemble",
                        lambda *a, **k: (_frame(12, rng), []))
    with pytest.raises(h004.SingleLookError, match="12/40"):
        h004.run(asof=datetime(2026, 10, 1, tzinfo=timezone.utc))


def test_deadline_lapse_is_no_go(monkeypatch):
    rng = np.random.default_rng(0)
    monkeypatch.setattr(h004, "assemble",
                        lambda *a, **k: (_frame(12, rng), ["2027-03-02"]))
    out = h004.run(asof=datetime(2028, 1, 5, tzinfo=timezone.utc))
    assert out["verdict"] == "NO-GO"
    assert out["gates"][0]["name"] == "accrual"
    assert not out["gates"][0]["passed"]
    assert out["unrated_sessions"] == ["2027-03-02"]


def test_promoted_path_all_gates(monkeypatch):
    rng = np.random.default_rng(1)
    monkeypatch.setattr(h004, "assemble",
                        lambda *a, **k: (_frame(40, rng), []))
    monkeypatch.setattr(h004, "run_holdout_replication",
                        lambda *a, **k: _HOLDOUT_PASS)
    out = h004.run(asof=datetime(2027, 5, 1, tzinfo=timezone.utc))
    assert out["verdict"] == "PROMOTED"
    assert all(g["passed"] for g in out["gates"])
    assert out["primary"]["ci"][0] > 0
    assert out["primary"]["p"] <= h004.BH_ALPHA
    assert out["n_days"] == 40


def test_kill_switch_breach_blocks_promotion(monkeypatch):
    rng = np.random.default_rng(1)
    monkeypatch.setattr(h004, "assemble",
                        lambda *a, **k: (_frame(40, rng, breach=True), []))
    monkeypatch.setattr(h004, "run_holdout_replication",
                        lambda *a, **k: _HOLDOUT_PASS)
    out = h004.run(asof=datetime(2027, 5, 1, tzinfo=timezone.utc))
    assert out["verdict"] == "NO-GO"
    gate = {g["name"]: g for g in out["gates"]}["kill_switch"]
    assert not gate["passed"]


def test_discipline_sign_flip_blocks_promotion(monkeypatch):
    rng = np.random.default_rng(1)
    monkeypatch.setattr(h004, "assemble",
                        lambda *a, **k: (_frame(40, rng, flip_clean=True), []))
    monkeypatch.setattr(h004, "run_holdout_replication",
                        lambda *a, **k: _HOLDOUT_PASS)
    out = h004.run(asof=datetime(2027, 5, 1, tzinfo=timezone.utc))
    assert out["verdict"] == "NO-GO"
    gate = {g["name"]: g for g in out["gates"]}["discipline_sign"]
    assert not gate["passed"]


def test_holdout_failure_blocks_promotion(monkeypatch):
    rng = np.random.default_rng(1)
    monkeypatch.setattr(h004, "assemble",
                        lambda *a, **k: (_frame(40, rng), []))
    monkeypatch.setattr(h004, "run_holdout_replication",
                        lambda *a, **k: {**_HOLDOUT_PASS,
                                         "holdout_rho": -0.05,
                                         "same_sign": False})
    out = h004.run(asof=datetime(2027, 5, 1, tzinfo=timezone.utc))
    assert out["verdict"] == "NO-GO"
    gate = {g["name"]: g for g in out["gates"]}["h003_holdout"]
    assert not gate["passed"]


def test_prereg_is_frozen():
    from alpha.study import prereg
    from alpha.config import PROJECT_ROOT
    path = PROJECT_ROOT / "ledger" / "H004-forward-owner-log.md"
    prereg.assert_frozen(path)   # raises if unfrozen or edited after freeze
