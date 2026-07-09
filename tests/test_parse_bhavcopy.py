import zipfile
from pathlib import Path

import pytest

from alpha.data import parse

FIXTURES = Path(__file__).parent / "fixtures"


def _zip_of(csv_name: str, tmp_path: Path) -> Path:
    zpath = tmp_path / f"{csv_name}.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(FIXTURES / csv_name, arcname=csv_name)
    return zpath


def test_udiff_parses_real_sample(tmp_path):
    df = parse.parse_fo_bhavcopy(_zip_of("fo_bhavcopy_udiff_sample.csv", tmp_path))
    assert list(df.columns) == parse.BHAV_COLUMNS
    # hand-checked row: NIFTY 28-Jul-2026 25550 CE, close 12.85, lot 65
    row = df[(df["symbol"] == "NIFTY") & (df["strike"] == 25550.0)
             & (df["option_type"] == "CE")].iloc[0]
    assert row["instrument"] == "IDO"
    assert row["close"] == 12.85
    assert row["lot"] == 65
    assert row["expiry"].date().isoformat() == "2026-07-28"
    assert str(df["available_at"].iloc[0].tz) == "UTC"
    # 19:30 IST == 14:00 UTC
    assert df["available_at"].iloc[0].isoformat() == "2026-07-06T14:00:00+00:00"


def test_legacy_parses_real_sample(tmp_path):
    df = parse.parse_fo_bhavcopy(_zip_of("fo_bhavcopy_legacy_sample.csv", tmp_path))
    assert list(df.columns) == parse.BHAV_COLUMNS
    # hand-checked row: OPTIDX NIFTY 11-Jan-2024 19400 CE close 2290, VAL_INLAKH 10.84
    row = df[(df["strike"] == 19400.0) & (df["option_type"] == "CE")].iloc[0]
    assert row["instrument"] == "IDO"  # OPTIDX mapped to UDiFF code
    assert row["close"] == 2290.0
    assert row["turnover_inr"] == pytest.approx(10.84e5)
    assert row["trade_date"].date().isoformat() == "2024-01-05"
    # futures row: option_type XX normalised to empty
    fut = df[df["instrument"] == "IDF"].iloc[0]
    assert fut["option_type"] == ""


def test_unknown_header_raises(tmp_path):
    bad_csv = tmp_path / "weird.csv"
    bad_csv.write_text("FOO,BAR\n1,2\n")
    zpath = tmp_path / "weird.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(bad_csv, arcname="weird.csv")
    with pytest.raises(ValueError, match="unrecognised"):
        parse.parse_fo_bhavcopy(zpath)
