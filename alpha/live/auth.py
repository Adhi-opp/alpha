"""Upstox token loading — Analytics Token first, daily OAuth as fallback.

Upstox issues two distinct token types and Alpha treats them differently:

- **Analytics Token** (`UPSTOX_ANALYTICS_TOKEN`): read-only, ~one-year
  validity, supports market-data REST and v3 websocket streaming. This is
  Alpha's PRIMARY credential — the desk is read-only by constitution, so a
  read-only token is exactly the right shape. No morning ritual.
- **Standard OAuth access_token** (`UPSTOX_ACCESS_TOKEN`): expires ~03:30
  IST the next day. OPTIONAL fallback only, minted by
  scripts/upstox_login.py when explicitly needed. Using the fallback must
  never overwrite the analytics token (the login script only writes the
  UPSTOX_ACCESS_TOKEN line).

Token contents are never printed or logged — only which SOURCE was used.
"""
from __future__ import annotations

import os
from pathlib import Path

from alpha.config import PROJECT_ROOT

ANALYTICS_VAR = "UPSTOX_ANALYTICS_TOKEN"
OAUTH_VAR = "UPSTOX_ACCESS_TOKEN"


def read_env_file(path: Path | None = None) -> dict[str, str]:
    p = path or (PROJECT_ROOT / ".env")
    out: dict[str, str] = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_upstox_token(env: dict[str, str] | None = None) -> tuple[str, str]:
    """Return (token, source); source is "analytics" or "oauth".

    Preference order: process environment beats .env file; within each,
    the analytics token beats the daily OAuth token. Raises RuntimeError
    (naming no secret values) when neither is available.
    """
    if env is None:
        env = {**read_env_file(), **{k: v for k, v in os.environ.items()
                                     if k in (ANALYTICS_VAR, OAUTH_VAR)}}
    analytics = (env.get(ANALYTICS_VAR) or "").strip()
    oauth = (env.get(OAUTH_VAR) or "").strip()
    if analytics:
        return analytics, "analytics"
    if oauth:
        return oauth, "oauth"
    raise RuntimeError(
        f"no Upstox token available: set {ANALYTICS_VAR} (preferred, "
        f"one-year read-only Analytics Token) or {OAUTH_VAR} (daily OAuth "
        f"fallback via scripts/upstox_login.py) in .env")
