from datetime import date
from pathlib import Path

import pytest

from alpha.data import parse

FIXTURE = Path(__file__).parent / "fixtures" / "participant_oi_20260706.csv"
TRADE_DATE = date(2026, 7, 6)


def test_parses_real_file():
    df = parse.parse_participant_oi(FIXTURE, TRADE_DATE)
    assert set(df["client_type"]) == {"Client", "DII", "FII", "Pro", "TOTAL"}
    client = df[df["client_type"] == "Client"].iloc[0]
    # values hand-checked against the raw file downloaded 2026-07-07
    assert client["fut_idx_long"] == 232341
    assert client["fut_idx_short"] == 67709
    fii = df[df["client_type"] == "FII"].iloc[0]
    assert fii["fut_idx_long"] == 32686
    total = df[df["client_type"] == "TOTAL"].iloc[0]
    assert total["total_long"] == 22894415


def test_available_at_is_2200_ist_in_utc():
    df = parse.parse_participant_oi(FIXTURE, TRADE_DATE)
    ts = df["available_at"].iloc[0]
    assert str(ts.tz) == "UTC"
    assert ts.isoformat() == "2026-07-06T16:30:00+00:00"  # 22:00 IST


def test_garbage_raises(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("<html>rate limited</html>")
    with pytest.raises(ValueError, match="no participant rows"):
        parse.parse_participant_oi(bad, TRADE_DATE)
