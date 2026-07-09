from alpha.console import state


def test_build_state_has_all_panels():
    s = state.build_state()
    for key in ("as_of", "system", "coverage", "cost_hurdle", "drawdown",
                "ledger", "promotion", "verdict", "study_pipeline"):
        assert key in s, f"missing panel {key}"


def test_verdict_defaults_to_stand_down():
    # no promoted study exists -> honest default
    v = state.verdict({"tripped": False})
    assert v["state"] == "STAND_DOWN"
    assert "Stand down" in v["headline"]


def test_verdict_halts_when_kill_switch_tripped():
    v = state.verdict({"tripped": True})
    assert v["state"] == "HALT"


def test_cost_hurdle_is_real_and_positive():
    rows = state.cost_hurdle()
    assert len(rows) == 4
    for r in rows:
        assert r["round_trip"] > 0
        assert 0 < r["breakeven_pct"] < 5  # sane for NIFTY options


def test_drawdown_budget_is_kill_switch():
    dd = state.drawdown()
    assert dd["budget"] == state.KILL_SWITCH_RUPEES
    assert 0 <= dd["pct"] <= 100
    assert dd["used"] >= 0


def test_ledger_family_count_includes_imported():
    led = state.ledger()
    assert led["family_registered"] == 5
    assert led["go"] == 1 and led["nogo"] == 4


def test_parse_ledger_status():
    assert state._parse_ledger_status("- **Status:** NO-GO | done") == "NO-GO"
    assert state._parse_ledger_status("- **Status:** GO (imported)") == "GO"
    assert state._parse_ledger_status("no status here") == "UNKNOWN"
