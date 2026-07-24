"""FastAPI decision console. Local, self-contained, read-only over the data.

Run: python scripts/run_console.py  ->  http://127.0.0.1:8787
Serves the cockpit page, a /api/state JSON the page polls, and the Live
Desk bridge: /api/live/snapshot + /api/live/stream (SSE). No external
calls, no order placement — this is a window, not a trigger.

Firewall note: this module must NEVER import from the live capture
package (test_firewall_no_reverse_imports greps for it). The cockpit
process publishes an atomic JSON runtime file
(alpha.config.LIVE_RUNTIME_SNAPSHOT); this app only reads that file.
Neither process depends on the other being alive: a browser disconnect or
a console crash cannot touch the recorder.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from alpha.config import LIVE_RUNTIME_SNAPSHOT
from alpha.console.state import build_state

STATIC = Path(__file__).parent / "static"
#: no fresh runtime file for longer than this = the page must show STALE
STALE_AFTER_S = 6.0
SSE_PERIOD_S = 2.0

app = FastAPI(title="Alpha Decision Console", docs_url=None, redoc_url=None)


@app.get("/api/state")
def api_state() -> JSONResponse:
    return JSONResponse(build_state())


def live_payload(path: Path | None = None,
                 now_ns: int | None = None) -> dict:
    """One envelope for the Live Desk: the cockpit's runtime file plus
    server-computed freshness. All cockpit numbers pass through verbatim —
    the browser formats, it never calculates."""
    p = path or LIVE_RUNTIME_SNAPSHOT
    now_ns = now_ns if now_ns is not None else time.time_ns()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "stale": True, "age_s": None}
    age_s = max(0.0, (now_ns - int(raw.get("published_at_ns") or 0)) / 1e9)
    return {"available": True,
            "stale": (age_s > STALE_AFTER_S
                      and raw.get("mode") != "replay"),
            "age_s": round(age_s, 1), **raw}


@app.get("/api/live/snapshot")
def api_live_snapshot() -> JSONResponse:
    return JSONResponse(live_payload())


async def sse_frames(path: Path | None = None,
                     period_s: float = SSE_PERIOD_S):
    """SSE generator: a data frame every period (the frame IS the
    heartbeat — stale/unavailable states are frames too, so the page
    always knows the truth). `retry:` primes EventSource auto-reconnect."""
    yield "retry: 3000\n\n"
    while True:
        payload = await asyncio.to_thread(live_payload, path)
        yield f"data: {json.dumps(payload, default=str)}\n\n"
        await asyncio.sleep(period_s)


@app.get("/api/live/stream")
def api_live_stream() -> StreamingResponse:
    return StreamingResponse(sse_frames(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))
