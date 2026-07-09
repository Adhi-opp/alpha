"""FastAPI decision console. Local, self-contained, read-only over the data.

Run: python scripts/run_console.py  ->  http://127.0.0.1:8787
Serves the cockpit page and a /api/state JSON the page polls. No external
calls, no order placement — this is a window, not a trigger.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from alpha.console.state import build_state

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Alpha Decision Console", docs_url=None, redoc_url=None)


@app.get("/api/state")
def api_state() -> JSONResponse:
    return JSONResponse(build_state())


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))
