from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from alpha.data import pit
from alpha.study import h004

_ASOF = datetime(2026, 8, 1, tzinfo=timezone.utc)
_LEDGER_HDR = ("session_date,wi_pctile_252,tier,is_nifty_expiry,"
               "computed_from,emitted_at_ist,outcome,note\n")


# ---- fixtures: a store where 2026-07-21 is a forward expiry with a FULLY
# FRESH backfilled T-1 participant trail (the trap scenario) --------------

def _seed_store(tmp_path: Path, expiry: str = "2026-07-21") -> None:
    e = pd.Timestamp(expiry)
    days = [e - pd.Timedelta(days=1), e]
    bhav = pd.DataFrame([
        {"trade_date": d, "symbol": "NIFTY", "instrument": "IDO",
         "expiry": e, "lot": 65,
         "available_at": (d + pd.Timedelta(hours=13)).tz_localize("UTC")}
        for d in days])
    pit.append("fo_bhavcopy", bhav,
               ["trade_date", "symbol", "instrument", "expiry"],
               root=tmp_path)
    # the backfilled participant file: trade_date = T-1, perfectly fresh BY
    # ITS DATES — assemble must never consult it for emission truth
    n = 30
    dates = pd.bdate_range(end=e - pd.Timedelta(days=1), periods=n)
    poi = pd.DataFrame({
        "trade_date": dates, "client_type": "Client",
        "opt_idx_call_long": 100.0, "opt_idx_put_long": 100.0,
        "opt_idx_call_short": 100.0 + np.arange(n),
        "opt_idx_put_short": 100.0 + np.arange(n),
        "available_at": (dates + pd.Timedelta(hours=17)).tz_localize("UTC"),
    })
    pit.append("participant_oi", poi, ["trade_date", "client_type"],
               root=tmp_path)


def _seed_journal(d: Path, ledger_rows: list[str] | None = None,
                  traded: bool = False) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    if traded:
        (d / "sessions_x.csv").write_text(
            "session_date,exchange,note_id,day_net_pnl,n_round_trips,"
            "trades_transcribed\n"
            "2026-07-21,NSE,X,500.0,1,1\n")
        (d / "trades_x.csv").write_text(
            "session_date,exchange,contract,expiry,qty,entry_time,exit_time,"
            "entry_wap,exit_wap\n"
            "2026-07-21,NSE,NIFTY2672124300CE,2026-07-21,65,10:00:00,"
            "10:05:00,100.0,110.0\n")
    else:
        # one benign OBSERVATIONAL (BSE) row: keeps the journal loadable
        # while leaving the NSE day-net map empty
        (d / "sessions_x.csv").write_text(
            "session_date,exchange,note_id,day_net_pnl,n_round_trips,"
            "trades_transcribed\n"
            "2026-07-16,BSE,OBS,100.0,1,1\n")
        (d / "trades_x.csv").write_text(
            "session_date,exchange,contract,expiry,qty,entry_time,exit_time,"
            "entry_wap,exit_wap\n"
            "2026-07-16,BSE,SENSEX2671676700PE,2026-07-16,20,10:00:00,"
            "10:05:00,100.0,110.0\n")
    if ledger_rows is not None:
        (d / "ratings_forward.csv").write_text(
            _LEDGER_HDR + "".join(ledger_rows))
    return d


# ---- the sample source is the ledger, never the (backfillable) store ----

def test_backfilled_file_cannot_rate_an_unemitted_session(tmp_path):
    """The 2026-07-21 regression, synthetic form: the store holds a fresh
    backfilled T-1 participant file, but no rating was ever emitted — the
    session must stay unrated-excluded, not become a favorable abstention."""
    _seed_store(tmp_path)
    j = _seed_journal(tmp_path / "j")     # no ratings_forward.csv at all
    frame, unrated, pending = h004.assemble(_ASOF, root=tmp_path,
                                            journal_dir=j)
    assert unrated == ["2026-07-21"]
    assert frame.empty
    assert pending == []


def test_forward_sample_is_ledger_sourced_on_real_data():
    """Real repo state: Jul-21's rating was never emitted (fetch dead that
    week); the Jul-15..23 backfill later restored its T-1 file. The ledger
    decides: Jul-14 in-sample with its ledger X verbatim, Jul-21 unrated."""
    frame, unrated, pending = h004.assemble(
        asof=datetime(2026, 7, 24, 18, 0, tzinfo=timezone.utc))
    assert "2026-07-21" in unrated
    assert pending == []
    assert [str(d.date()) for d in frame["session_date"]] == ["2026-07-14"]
    row = frame.iloc[0]
    assert row["wi_pctile"] == pytest.approx(52.8)     # ledger X, verbatim
    assert row["day_net_pnl"] == pytest.approx(57789.21)
    assert not row["abstained"]


def test_ledger_x_is_verbatim_even_without_any_store_trail(tmp_path):
    """X can only come from the emission row: the confirmed abstention
    enters at the ledger's 41.0 / Y=0 although no participant trail exists
    from which any X could be recomputed."""
    _seed_store(tmp_path)
    j = _seed_journal(tmp_path / "j", ledger_rows=[
        "2026-07-21,41.0,NEUTRAL,True,2026-07-20,2026-07-21T08:55,"
        "abstained,\n"])
    frame, unrated, pending = h004.assemble(_ASOF, root=tmp_path,
                                            journal_dir=j)
    assert unrated == [] and pending == []
    assert len(frame) == 1
    assert frame["wi_pctile"].iloc[0] == 41.0
    assert frame["day_net_pnl"].iloc[0] == 0.0
    assert bool(frame["abstained"].iloc[0])
    assert frame["y_clean"].iloc[0] == 0.0


def test_pending_outcome_never_becomes_abstention_zero(tmp_path):
    _seed_store(tmp_path)
    j = _seed_journal(tmp_path / "j", ledger_rows=[
        # a non-expiry context emission must be tolerated and ignored
        "2026-07-20,39.0,NEUTRAL,False,2026-07-17,2026-07-20T08:50,"
        "pending,\n",
        "2026-07-21,41.0,NEUTRAL,True,2026-07-20,2026-07-21T08:55,"
        "pending,\n"])
    frame, unrated, pending = h004.assemble(_ASOF, root=tmp_path,
                                            journal_dir=j)
    assert pending == ["2026-07-21"]
    assert frame.empty and unrated == []


def test_traded_outcome_takes_journal_day_net(tmp_path):
    _seed_store(tmp_path)
    j = _seed_journal(tmp_path / "j", traded=True, ledger_rows=[
        "2026-07-21,41.0,NEUTRAL,True,2026-07-20,2026-07-21T08:55,"
        "traded,\n"])
    frame, unrated, pending = h004.assemble(_ASOF, root=tmp_path,
                                            journal_dir=j)
    assert len(frame) == 1 and unrated == [] and pending == []
    assert frame["day_net_pnl"].iloc[0] == pytest.approx(500.0)
    assert not frame["abstained"].iloc[0]


def test_outcome_journal_contradictions_raise(tmp_path):
    _seed_store(tmp_path)
    j1 = _seed_journal(tmp_path / "j1", ledger_rows=[
        "2026-07-21,41.0,NEUTRAL,True,2026-07-20,2026-07-21T08:55,"
        "traded,\n"])
    with pytest.raises(ValueError, match="no NSE session row"):
        h004.assemble(_ASOF, root=tmp_path, journal_dir=j1)
    j2 = _seed_journal(tmp_path / "j2", traded=True, ledger_rows=[
        "2026-07-21,41.0,NEUTRAL,True,2026-07-20,2026-07-21T08:55,"
        "abstained,\n"])
    with pytest.raises(ValueError, match="finalize as 'traded'"):
        h004.assemble(_ASOF, root=tmp_path, journal_dir=j2)


def test_ledger_expiry_flag_must_match_calendar(tmp_path):
    _seed_store(tmp_path)                 # calendar: Jul-21 IS an expiry
    j = _seed_journal(tmp_path / "j", ledger_rows=[
        "2026-07-21,41.0,NEUTRAL,False,2026-07-20,2026-07-21T08:55,"
        "pending,\n"])
    with pytest.raises(ValueError, match="contradicts the bhavcopy"):
        h004.assemble(_ASOF, root=tmp_path, journal_dir=j)


def test_unknown_outcome_value_raises(tmp_path):
    _seed_store(tmp_path)
    j = _seed_journal(tmp_path / "j", ledger_rows=[
        "2026-07-21,41.0,NEUTRAL,True,2026-07-20,2026-07-21T08:55,"
        "maybe,\n"])
    with pytest.raises(ValueError, match="unknown outcome"):
        h004.assemble(_ASOF, root=tmp_path, journal_dir=j)


# ---- run(): single look, deadline, gates (assemble monkeypatched) -------

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
                        lambda *a, **k: (_frame(12, rng), [], []))
    with pytest.raises(h004.SingleLookError, match="12/40"):
        h004.run(asof=datetime(2026, 10, 1, tzinfo=timezone.utc))


def test_pending_session_blocks_the_single_look(monkeypatch):
    """40 finalized rows exist, but an emission dated inside the first 40
    is still pending: the sequence is unsettled — refuse the evaluation."""
    rng = np.random.default_rng(1)
    monkeypatch.setattr(h004, "assemble",
                        lambda *a, **k: (_frame(40, rng), [],
                                         ["2026-08-04"]))
    monkeypatch.setattr(h004, "run_holdout_replication",
                        lambda *a, **k: _HOLDOUT_PASS)
    with pytest.raises(RuntimeError, match="pending"):
        h004.run(asof=datetime(2027, 5, 1, tzinfo=timezone.utc))


def test_deadline_lapse_is_no_go(monkeypatch):
    rng = np.random.default_rng(0)
    monkeypatch.setattr(h004, "assemble",
                        lambda *a, **k: (_frame(12, rng), ["2027-03-02"], []))
    out = h004.run(asof=datetime(2028, 1, 5, tzinfo=timezone.utc))
    assert out["verdict"] == "NO-GO"
    assert out["gates"][0]["name"] == "accrual"
    assert not out["gates"][0]["passed"]
    assert out["unrated_sessions"] == ["2027-03-02"]
    assert out["pending_sessions"] == []


def test_promoted_path_all_gates(monkeypatch):
    rng = np.random.default_rng(1)
    monkeypatch.setattr(h004, "assemble",
                        lambda *a, **k: (_frame(40, rng), [], []))
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
                        lambda *a, **k: (_frame(40, rng, breach=True), [], []))
    monkeypatch.setattr(h004, "run_holdout_replication",
                        lambda *a, **k: _HOLDOUT_PASS)
    out = h004.run(asof=datetime(2027, 5, 1, tzinfo=timezone.utc))
    assert out["verdict"] == "NO-GO"
    gate = {g["name"]: g for g in out["gates"]}["kill_switch"]
    assert not gate["passed"]


def test_discipline_sign_flip_blocks_promotion(monkeypatch):
    rng = np.random.default_rng(1)
    monkeypatch.setattr(h004, "assemble",
                        lambda *a, **k: (_frame(40, rng, flip_clean=True),
                                         [], []))
    monkeypatch.setattr(h004, "run_holdout_replication",
                        lambda *a, **k: _HOLDOUT_PASS)
    out = h004.run(asof=datetime(2027, 5, 1, tzinfo=timezone.utc))
    assert out["verdict"] == "NO-GO"
    gate = {g["name"]: g for g in out["gates"]}["discipline_sign"]
    assert not gate["passed"]


def test_holdout_failure_blocks_promotion(monkeypatch):
    rng = np.random.default_rng(1)
    monkeypatch.setattr(h004, "assemble",
                        lambda *a, **k: (_frame(40, rng), [], []))
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
