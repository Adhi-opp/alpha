import asyncio
import gzip
import io

import pytest

from alpha.live import provider_upstox as up
from alpha.live import replay
from alpha.live.collector import SessionCapture
from alpha.live.recorder import Recorder, pump


# ---- instrument master / chain resolution --------------------------------

def _master_csv(rows: list[dict]) -> bytes:
    cols = ["instrument_key", "exchange", "tradingsymbol", "expiry", "name"]
    buf = io.StringIO()
    buf.write(",".join(cols) + "\n")
    for r in rows:
        buf.write(",".join(r.get(c, "") for c in cols) + "\n")
    return gzip.compress(buf.getvalue().encode())


SYNTH_MASTER = [
    # NIFTY front week (2026-07-14) + next week + a NIFTYNXT50 look-alike
    {"instrument_key": "NSE_FO|1", "exchange": "NSE_FO",
     "tradingsymbol": "NIFTY2671424050CE", "expiry": "2026-07-14", "name": "NIFTY"},
    {"instrument_key": "NSE_FO|2", "exchange": "NSE_FO",
     "tradingsymbol": "NIFTY2671424050PE", "expiry": "2026-07-14", "name": "NIFTY"},
    {"instrument_key": "NSE_FO|3", "exchange": "NSE_FO",
     "tradingsymbol": "NIFTY2671424100CE", "expiry": "2026-07-14", "name": "NIFTY"},
    {"instrument_key": "NSE_FO|9", "exchange": "NSE_FO",
     "tradingsymbol": "NIFTY2672124050CE", "expiry": "2026-07-21", "name": "NIFTY"},
    {"instrument_key": "NSE_FO|X", "exchange": "NSE_FO",
     "tradingsymbol": "NIFTYNXT502671430000CE", "expiry": "2026-07-14",
     "name": "NIFTYNXT50"},
    {"instrument_key": "NSE_FO|F", "exchange": "NSE_FO",
     "tradingsymbol": "NIFTY26JULFUT", "expiry": "2026-07-30", "name": "NIFTY"},
    # SENSEX + the SENSEX50 trap (name column separates them)
    {"instrument_key": "BSE_FO|1", "exchange": "BSE_FO",
     "tradingsymbol": "SENSEX2671677600CE", "expiry": "2026-07-16", "name": "SENSEX"},
    {"instrument_key": "BSE_FO|2", "exchange": "BSE_FO",
     "tradingsymbol": "SENSEX2671677600PE", "expiry": "2026-07-16", "name": "SENSEX"},
    {"instrument_key": "BSE_FO|T", "exchange": "BSE_FO",
     "tradingsymbol": "SENSEX502671677000CE", "expiry": "2026-07-16",
     "name": "SENSEX50"},
    # expired contract must be ignored
    {"instrument_key": "NSE_FO|D", "exchange": "NSE_FO",
     "tradingsymbol": "NIFTY2670724000CE", "expiry": "2026-07-07", "name": "NIFTY"},
]


def test_master_parse_and_front_week():
    rows = up.parse_master_bytes(_master_csv(SYNTH_MASTER))
    from datetime import date
    chain = up.front_week_chain(rows, "NIFTY", today=date(2026, 7, 12))
    assert chain.expiry == "2026-07-14"        # nearest, not next week
    assert (24050.0, "CE") in chain.options and (24050.0, "PE") in chain.options
    assert (30000.0, "CE") not in chain.options    # NIFTYNXT50 excluded
    assert chain.future_key == "NSE_FO|F"
    assert chain.strikes == [24050.0, 24100.0]

    sensex = up.front_week_chain(rows, "SENSEX", today=date(2026, 7, 12))
    assert sensex.expiry == "2026-07-16"
    assert (77600.0, "CE") in sensex.options
    assert (77000.0, "CE") not in sensex.options   # SENSEX50 excluded by name


def test_band_selection_and_retarget():
    strikes = [float(s) for s in range(24000, 25001, 50)]   # 21 strikes
    band = up.select_band(strikes, spot=24510.0, half_width=3)
    assert band == [24350.0, 24400.0, 24450.0, 24500.0,
                    24550.0, 24600.0, 24650.0]
    # spot inside the inner core -> no retarget
    assert not up.needs_retarget(band, 24500.0, inner=2)
    # spot beyond the inner core -> retarget
    assert up.needs_retarget(band, 24700.0, inner=2)
    assert up.needs_retarget(band, 24300.0, inner=2)
    # band clamped at grid edge
    edge = up.select_band(strikes, spot=23900.0, half_width=3)
    assert edge[0] == 24000.0 and len(edge) == 4


def test_sub_frame_shape():
    import json
    frame = json.loads(up.build_frame("sub", ["NSE_INDEX|Nifty 50"]))
    assert frame["method"] == "sub"
    assert frame["data"]["mode"] == "full"
    assert frame["data"]["instrumentKeys"] == ["NSE_INDEX|Nifty 50"]


# ---- protobuf decode round-trip -------------------------------------------

def test_decode_market_and_index_feeds():
    from upstox_client.feeder.proto import MarketDataFeedV3_pb2 as pb
    fr = pb.FeedResponse()
    fr.type = pb.live_feed
    fr.currentTs = 1770000000123

    mf = fr.feeds["NSE_FO|1"].fullFeed.marketFF
    mf.ltpc.ltp = 188.1
    mf.ltpc.ltt = 1770000000100
    mf.ltpc.ltq = 65
    mf.ltpc.cp = 180.0
    mf.vtt = 123456
    mf.oi = 5000000.0
    mf.iv = 14.2
    mf.tbq = 900.0
    mf.tsq = 700.0
    mf.optionGreeks.delta = 0.52
    mf.optionGreeks.gamma = 0.0021
    mf.optionGreeks.theta = -9.8
    mf.optionGreeks.vega = 3.3
    for bp, bq, ap, aq in [(188.0, 130, 188.2, 65), (187.9, 260, 188.3, 130)]:
        q = mf.marketLevel.bidAskQuote.add()
        q.bidP, q.bidQ, q.askP, q.askQ = bp, bq, ap, aq

    idx = fr.feeds["NSE_INDEX|Nifty 50"].fullFeed.indexFF
    idx.ltpc.ltp = 24123.45
    idx.ltpc.ltt = 1770000000100

    events = up.decode(fr.SerializeToString())
    by_kind = {e["kind"]: e for e in events}
    tick = by_kind["tick"]
    assert tick["key"] == "NSE_FO|1"
    assert tick["ltp"] == pytest.approx(188.1)
    assert tick["oi"] == 5000000.0
    assert tick["iv"] == pytest.approx(14.2)
    assert tick["greeks"]["gamma"] == pytest.approx(0.0021)
    assert tick["depth"][0] == [pytest.approx(188.0), 130.0,
                                pytest.approx(188.2), 65.0]
    assert tick["provider_ts"] == 1770000000123
    assert by_kind["index"]["ltp"] == pytest.approx(24123.45)


# ---- recorder + replay ------------------------------------------------------

def test_recorder_roundtrip_and_manifest(tmp_path):
    rec = Recorder(tmp_path / "s", keep_raw=True, rotate_events=2)
    rec.write_batch([{"kind": "tick", "t_local_ns": 1, "ltp": 1.0},
                     {"kind": "tick", "t_local_ns": 2, "ltp": 2.0}],
                    raws=[(1, b"abc")])
    # rotation happens at batch boundaries: this batch opens segment 2
    rec.write_batch([{"kind": "tick", "t_local_ns": 3, "ltp": 3.0},
                     {"kind": "note", "t_local_ns": 4}])
    manifest = rec.close(metadata={"run_id": "test-run"})
    assert manifest["n_events"] == 4
    assert manifest["n_raw"] == 1
    assert manifest["t_first_ns"] == 1 and manifest["t_last_ns"] == 4
    assert len(manifest["segments"]) == 2
    assert all(s.endswith(".gz") for s in manifest["segments"])
    assert manifest["metadata"]["run_id"] == "test-run"

    evs = list(replay.events(tmp_path / "s"))
    assert [e["t_local_ns"] for e in evs] == [1, 2, 3, 4]
    frames = list(replay.raw_frames(tmp_path / "s"))
    assert frames == [(1, b"abc")]


def test_pump_drains_and_stops(tmp_path):
    async def scenario():
        rec = Recorder(tmp_path / "p")
        q = asyncio.Queue()
        for i in range(7):
            q.put_nowait(([{"kind": "tick", "t_local_ns": i}], []))
        q.put_nowait(None)
        await pump(q, rec, batch_max=3)
        return rec.close()

    manifest = asyncio.run(scenario())
    assert manifest["n_events"] == 7
    evs = list(replay.events(tmp_path / "p"))
    assert [e["t_local_ns"] for e in evs] == list(range(7))


def test_one_raw_frame_per_decoded_message_and_shared_receipt(tmp_path):
    cap = SessionCapture("token", out_root=tmp_path, keep_raw=True)
    assert cap._enqueue_batch(
        [{"kind": "tick", "key": "A"}, {"kind": "tick", "key": "B"}],
        raw=b"one-wire-message", receipt_ns=123,
    )
    batch = cap.queue.get_nowait()
    assert [e["t_local_ns"] for e in batch[0]] == [123, 123]
    assert batch[1] == [(123, b"one-wire-message")]

    async def scenario():
        rec = Recorder(cap.dir, keep_raw=True)
        q = asyncio.Queue()
        q.put_nowait(batch)
        q.put_nowait(None)
        await pump(q, rec)
        rec.close()

    asyncio.run(scenario())
    assert list(replay.raw_frames(cap.dir)) == [(123, b"one-wire-message")]
    assert len(list(replay.events(cap.dir))) == 2


def test_queue_overflow_halts_instead_of_silently_dropping(tmp_path):
    cap = SessionCapture("token", out_root=tmp_path, queue_max=1)
    assert cap._enqueue_batch([{"kind": "tick"}], receipt_ns=1)
    assert not cap._enqueue_batch([{"kind": "tick"}], receipt_ns=2)
    assert cap._stop
    assert cap._queue_overflows == 1
    assert cap._degraded_reason


def test_retarget_commits_only_after_change_application(tmp_path):
    options = {}
    for strike in (100.0, 150.0, 200.0, 250.0, 300.0, 350.0, 400.0):
        for side in ("CE", "PE"):
            options[(strike, side)] = f"NSE_FO|{int(strike)}{side}"
    cap = SessionCapture("token", symbols=("NIFTY",), out_root=tmp_path,
                         half_width=2, inner=1)
    chain = up.Chain("NIFTY", "2026-07-14", "NSE_INDEX|Nifty 50",
                     "NSE_FO|F", options, sorted({k[0] for k in options}))
    old_band = [100.0, 150.0, 200.0, 250.0, 300.0]
    cap.chains["NIFTY"] = chain
    cap.bands["NIFTY"] = old_band.copy()
    cap.spots["NIFTY"] = 350.0
    cap._active_keys = {chain.index_key, chain.future_key, *chain.band_keys(old_band)}

    changes = cap._retarget_frames()
    # The live state remains honest until the websocket confirms each send.
    assert cap.bands["NIFTY"] == old_band
    for change in changes:
        cap._apply_subscription_change(change)
    assert cap.bands["NIFTY"] != old_band
    assert set(chain.band_keys(cap.bands["NIFTY"])).issubset(cap._active_keys)
    assert not set(chain.band_keys([100.0, 150.0])).intersection(cap._active_keys)


def test_capture_runs_never_reuse_a_label_directory(tmp_path):
    a = SessionCapture("token", out_root=tmp_path, label="probe")
    b = SessionCapture("token", out_root=tmp_path, label="probe")
    assert a.dir != b.dir


def test_firewall_no_reverse_imports():
    """alpha.data / alpha.study / console must never import alpha.live."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "alpha"
    for sub in ("data", "study", "measure", "console", "paper", "model"):
        for p in (root / sub).rglob("*.py"):
            assert "alpha.live" not in p.read_text(encoding="utf-8"), \
                f"{p} imports alpha.live — firewall breach"
