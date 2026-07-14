r"""OPTIONAL fallback: mint a daily OAuth UPSTOX_ACCESS_TOKEN into .env.

Alpha's PRIMARY Upstox credential is the read-only **Analytics Token**
(UPSTOX_ANALYTICS_TOKEN in .env, ~one-year validity, market data + v3
websocket streaming) — pasted once from the Upstox developer console. There
is NO daily login requirement.

Run this ONLY when no analytics token is available and a temporary daily
OAuth access_token (expires ~03:30 IST next day) is needed as a fallback:

  d:\alpha\.venv\Scripts\python scripts\upstox_login.py

Reads UPSTOX_API_KEY / UPSTOX_API_SECRET / UPSTOX_REDIRECT_URI from
d:\alpha\.env, falling back to d:\GammaLeak\.env (same machine, same owner —
values are never printed or committed). Opens the login URL, you approve and
paste back the `code=` from the redirect, and the fresh token is written to
d:\alpha\.env in place — it writes ONLY the UPSTOX_ACCESS_TOKEN line and
never touches UPSTOX_ANALYTICS_TOKEN.
"""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path
from secrets import token_urlsafe
from urllib.parse import parse_qs, quote, urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
ENV_PATHS = [ROOT / ".env", Path(r"d:\GammaLeak\.env")]
AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def credential(name: str) -> str:
    for p in ENV_PATHS:
        v = read_env(p).get(name, "")
        if v and "your_" not in v:
            return v
    sys.exit(f"{name} not found in any of: "
             + ", ".join(str(p) for p in ENV_PATHS))


def write_token(env_path: Path, token: str) -> None:
    lines = (env_path.read_text(encoding="utf-8").splitlines()
             if env_path.exists() else [])
    key = "UPSTOX_ACCESS_TOKEN"
    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={token}"
            replaced = True
    if not replaced:
        lines.append(f"{key}={token}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    api_key = credential("UPSTOX_API_KEY")
    api_secret = credential("UPSTOX_API_SECRET")
    redirect = credential("UPSTOX_REDIRECT_URI")

    state = token_urlsafe(24)
    url = (f"{AUTH_URL}?client_id={quote(api_key, safe='')}"
           f"&redirect_uri={quote(redirect, safe='')}"
           f"&response_type=code&scope=default&state={quote(state, safe='')}")
    print("1. Opening the Upstox approval page in your browser.\n")
    webbrowser.open(url)
    try:
        pasted = input("2. Paste the FULL redirect URL: ").strip()
    except EOFError:
        sys.exit("OAuth approval needs an interactive terminal; run this command yourself")
    query = parse_qs(urlparse(pasted).query)
    code = query.get("code", [""])[0]
    returned_state = query.get("state", [""])[0]
    if not code or returned_state != state:
        sys.exit("invalid OAuth callback: missing code or state mismatch")

    resp = requests.post(TOKEN_URL, data={
        "code": code, "client_id": api_key, "client_secret": api_secret,
        "redirect_uri": redirect, "grant_type": "authorization_code",
    }, headers={"Accept": "application/json"}, timeout=30)
    if resp.status_code != 200:
        sys.exit(f"token exchange failed HTTP {resp.status_code}: "
                 f"{resp.text[:300]}")
    token = resp.json().get("access_token", "")
    if not token:
        sys.exit(f"no access_token in response: {resp.text[:300]}")
    write_token(ROOT / ".env", token)
    print("3. Fresh UPSTOX_ACCESS_TOKEN written to .env "
          "(valid until ~03:30 IST tomorrow).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
