r"""Launch the decision console at http://127.0.0.1:8787.

  d:\alpha\.venv\Scripts\python scripts\run_console.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

if __name__ == "__main__":
    uvicorn.run("alpha.console.app:app", host="127.0.0.1", port=8787, reload=False)
