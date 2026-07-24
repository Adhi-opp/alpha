"""Browser Live Desk: runtime bridge contract, console API, decoupling."""
import asyncio
import json
import time

import pytest

from alpha.console import app as console_app
from alpha.live.cockpit import (RUNTIME_SCHEMA, Cockpit, publish_runtime,
                                runtime_payload)
from tests.test_cockpit import _MAP, _events


def _cp() -> Cockpit:
    cp = Cockpit(_MAP)
    for ev in _events():
        cp.apply(ev)
    return cp


def _payload(mode="live", **run):
    meta = {"run_id": "r1", "label": "capture", "day": "2026-07-27",
            "queue_high_water": 4, "queue_max": 10000,
            "queue_overflows": 0, "degraded_reason": None, **run}
    return runtime_payload(_cp(), meta, mode=mode)


# ---- bridge: schema, atomicity, no credentials --------------------------

def test_runtime_payload_schema_and_publish(tmp_path):
    target = tmp_path / "rt" / "cockpit_runtime.json"
    p = _payload()
    assert publish_runtime(p, target) is True
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["schema"] == RUNTIME_SCHEMA
    assert on_disk["mode"] == "live"
    assert on_disk["run"]["run_id"] == "r1"
    assert on_disk["run"]["queue_max"] == 10000
    sym = on_disk["snapshot"]["per_symbol"]["NIFTY"]
    assert sym["atm"] == 24100.0
    assert sym["max_pain"]["strike"] == 24100.0
    assert on_disk["snapshot"]["expiries"]["NIFTY"] == "2026-07-28"
    # nothing credential-shaped may ever cross the bridge
    blob = json.dumps(on_disk).lower()
    for word in ("token", "authorization", "secret", "bearer"):
        assert word not in blob


def test_publish_never_raises(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a directory must go")
    target = blocker / "sub" / "cockpit_runtime.json"
    assert publish_runtime(_payload(), target) is False   # no exception


def test_capture_metadata_is_allowlisted():
    """Only the allowlisted capture fields cross; anything else a caller
    passes (by accident) is dropped."""
    p = runtime_payload(_cp(), {"run_id": "r1", "token": "LEAK-ME",
                                "queue_max": 5}, mode="live")
    assert "token" not in p["run"]
    assert p["run"]["queue_max"] == 5


# ---- console API: contract, staleness, SSE ------------------------------

def test_live_payload_contract(tmp_path):
    target = tmp_path / "cockpit_runtime.json"
    publish_runtime(_payload(), target)
    out = console_app.live_payload(target)
    assert out["available"] is True
    assert out["stale"] is False
    assert out["age_s"] < 5
    assert out["snapshot"]["health"]["banner"]
    # missing file -> honest envelope, never an exception
    gone = console_app.live_payload(tmp_path / "nope.json")
    assert gone == {"available": False, "stale": True, "age_s": None}


def test_live_payload_goes_stale_but_replay_does_not(tmp_path):
    target = tmp_path / "cockpit_runtime.json"
    old_ns = time.time_ns() - int(60e9)
    live = _payload(); live["published_at_ns"] = old_ns
    publish_runtime(live, target)
    assert console_app.live_payload(target)["stale"] is True
    rep = _payload(mode="replay"); rep["published_at_ns"] = old_ns
    publish_runtime(rep, target)
    out = console_app.live_payload(target)
    assert out["stale"] is False          # a replay preview is a static view
    assert out["mode"] == "replay"


def test_sse_stream_yields_heartbeat_frames(tmp_path):
    target = tmp_path / "cockpit_runtime.json"
    publish_runtime(_payload(), target)

    async def take(n):
        frames = []
        gen = console_app.sse_frames(target, period_s=0.01)
        async for chunk in gen:
            frames.append(chunk)
            if len(frames) >= n:
                break
        return frames

    frames = asyncio.run(take(3))
    assert frames[0].startswith("retry:")            # reconnect priming
    for frame in frames[1:]:                         # every frame = heartbeat
        assert frame.startswith("data: ")
        body = json.loads(frame[len("data: "):])
        assert body["available"] is True
        assert body["snapshot"]["per_symbol"]["NIFTY"]["atm"] == 24100.0


def test_api_routes_answer_without_a_publisher():
    """Console must serve an honest envelope even when no cockpit process
    has ever run — the bridge file simply may not exist."""
    resp = console_app.api_live_snapshot()
    body = json.loads(resp.body)
    assert "available" in body and "stale" in body


# ---- decoupling / firewall / parity -------------------------------------

def test_console_never_imports_alpha_live():
    """The bridge is the FILE, not an import — a console crash or browser
    disconnect therefore cannot reach the recorder process at all."""
    from pathlib import Path
    src_dir = Path(console_app.__file__).parent
    for p in src_dir.rglob("*.py"):
        assert "alpha.live" not in p.read_text(encoding="utf-8")


def test_replay_payload_matches_terminal_board():
    """The browser renders the same reducer output the terminal prints —
    one source, two skins."""
    from scripts.cockpit import render
    cp = _cp()
    payload = runtime_payload(cp, {"run_id": "x"}, mode="replay")
    sym = payload["snapshot"]["per_symbol"]["NIFTY"]
    board = render(cp)
    assert sym["atm"] == cp.atm_strike("NIFTY")
    assert sym["max_pain"]["strike"] == cp.max_pain("NIFTY")["strike"]
    assert "24,100" in board                     # ATM on the terminal board
    assert sym["churn"]["tick_path_rs_per_lot"] == pytest.approx(
        cp.churn_panel("NIFTY")["tick_path_rs_per_lot"])
