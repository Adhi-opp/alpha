"""Security-ID resolution join, tested against a synthetic master.

Column names/values mirror the real Dhan api-scrip-master-detailed.csv
(verified 2026-07-08): EXCH_ID, INSTRUMENT=OPTIDX, UNDERLYING_SYMBOL,
SM_EXPIRY_DATE (ISO), STRIKE_PRICE (float text), OPTION_TYPE, SECURITY_ID.
"""
import pandas as pd
import pytest

from alpha.data import dhan_bulk


def _master_csv(tmp_path):
    rows = [
        # exch, seg, secid, instr, undsym, expiry, strike, opt, lot
        ("NSE", "D", "35022", "OPTIDX", "NIFTY", "2026-07-28", "29300.00000", "CE", "65.0"),
        ("NSE", "D", "35023", "OPTIDX", "NIFTY", "2026-07-28", "24500.00000", "CE", "65.0"),
        ("NSE", "D", "35024", "OPTIDX", "NIFTY", "2026-07-28", "24500.00000", "PE", "65.0"),
        ("BSE", "D", "99999", "OPTIDX", "SENSEX", "2026-07-28", "24500.00000", "CE", "20.0"),
        ("NSE", "E", "1234", "EQUITY", "NIFTY", "", "", "", "1.0"),  # noise
    ]
    cols = ["EXCH_ID", "SEGMENT", "SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL",
            "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE", "LOT_SIZE"]
    p = tmp_path / "master.csv"
    pd.DataFrame(rows, columns=cols).to_csv(p, index=False)
    return p


def _universe(contracts):
    return pd.DataFrame(
        [{"symbol": "NIFTY", "expiry": pd.Timestamp(e), "strike": s, "option_type": o}
         for e, s, o in contracts]
    )


def test_resolves_matching_contracts(tmp_path):
    master = _master_csv(tmp_path)
    uni = _universe([("2026-07-28", 24500.0, "CE"), ("2026-07-28", 24500.0, "PE")])
    ids = dhan_bulk.resolve_security_ids(uni, master, symbol="NIFTY")
    assert ids[dhan_bulk.contract_key("NIFTY", "2026-07-28", 24500.0, "CE")] == "35023"
    assert ids[dhan_bulk.contract_key("NIFTY", "2026-07-28", 24500.0, "PE")] == "35024"


def test_does_not_cross_exchange(tmp_path):
    # a NIFTY(NSE) query must never pick up the SENSEX(BSE) 24500 CE
    master = _master_csv(tmp_path)
    uni = _universe([("2026-07-28", 24500.0, "CE")])
    ids = dhan_bulk.resolve_security_ids(uni, master, symbol="NIFTY", exchange="NSE")
    assert set(ids.values()) == {"35023"}


def test_missing_contract_raises_not_silently_dropped(tmp_path):
    # an expired/absent contract must fail loudly (95.7% of the 3-yr universe
    # is absent from the live master — a silent drop would shrink the pull)
    master = _master_csv(tmp_path)
    uni = _universe([("2026-07-28", 24500.0, "CE"), ("2020-01-01", 12000.0, "CE")])
    with pytest.raises(KeyError, match="not found in Dhan master"):
        dhan_bulk.resolve_security_ids(uni, master, symbol="NIFTY")
