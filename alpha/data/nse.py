"""NSE archive fetchers: participant-wise OI and F&O bhavcopy.

Fetch quirks ported from GammaLeak's fii_dii_scraper.py (proven in
production there) and re-verified live 2026-07-07:
- browser-like headers or NSE returns 403;
- best-effort cookie prefetch of nseindia.com;
- dual archive hosts (nsearchives.nseindia.com preferred).

Every successful fetch goes straight into the immutable raw archive; callers
get back the archived Path, never loose bytes.
"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import requests

from alpha.config import UDIFF_START
from alpha.data import archive

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/zip,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
HOSTS = ("https://nsearchives.nseindia.com", "https://archives.nseindia.com")

SOURCE = "nse"


class NotPublished(FileNotFoundError):
    """404 on all hosts — holiday, weekend, or not yet published."""


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    try:  # cookie prefetch is best-effort; archive hosts usually don't need it
        s.get("https://www.nseindia.com/", timeout=10)
    except requests.RequestException:
        pass
    return s


def _get(session: requests.Session, url_path: str, retries: int = 2) -> bytes:
    last_error: Exception | None = None
    all_404 = True
    for attempt in range(retries + 1):
        for host in HOSTS:
            url = host + url_path
            try:
                resp = session.get(url, timeout=30)
            except requests.RequestException as exc:
                last_error, all_404 = exc, False
                continue
            if resp.status_code == 200 and resp.content:
                return resp.content
            if resp.status_code != 404:
                all_404 = False
                last_error = RuntimeError(f"HTTP {resp.status_code} for {url}")
        if all_404:
            raise NotPublished(url_path)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fetch failed for {url_path}: {last_error}")


def participant_oi_archived(d: date, root: Path | None = None) -> bool:
    return archive.is_archived(
        SOURCE, f"participant_oi/{d:%Y}/fao_participant_oi_{d:%d%m%Y}.csv", root)


def fo_bhavcopy_archived(d: date, root: Path | None = None) -> bool:
    return any(
        archive.is_archived(
            SOURCE, f"fo_bhavcopy/{d:%Y}/{p.rsplit('/', 1)[-1]}", root)
        for p in (_udiff_url_path(d), _legacy_url_path(d))
    )


def fetch_participant_oi(
    d: date, session: requests.Session | None = None, root: Path | None = None
) -> Path:
    relpath = f"participant_oi/{d:%Y}/fao_participant_oi_{d:%d%m%Y}.csv"
    if archive.is_archived(SOURCE, relpath, root):
        return archive.path_of(SOURCE, relpath, root)
    session = session or make_session()
    url_path = f"/content/nsccl/fao_participant_oi_{d:%d%m%Y}.csv"
    content = _get(session, url_path)
    if b"Client Type" not in content:
        # NSE serves HTML error pages with HTTP 200 sometimes
        raise NotPublished(f"participant OI for {d}: response is not the CSV")
    return archive.store(SOURCE, relpath, content, HOSTS[0] + url_path,
                         meta={"trade_date": d.isoformat()}, root=root)


def _udiff_url_path(d: date) -> str:
    return f"/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def _legacy_url_path(d: date) -> str:
    mon = d.strftime("%b").upper()
    return (
        f"/content/historical/DERIVATIVES/{d:%Y}/{mon}/"
        f"fo{d:%d}{mon}{d:%Y}bhav.csv.zip"
    )


def fetch_fo_bhavcopy(
    d: date, session: requests.Session | None = None, root: Path | None = None
) -> Path:
    # Preferred format by date, with the other as cutover-date insurance:
    # a wrong UDIFF_START costs one extra request, not data.
    candidates = (
        [("udiff", _udiff_url_path(d)), ("legacy", _legacy_url_path(d))]
        if d >= UDIFF_START
        else [("legacy", _legacy_url_path(d)), ("udiff", _udiff_url_path(d))]
    )
    for fmt, url_path in candidates:
        relpath = f"fo_bhavcopy/{d:%Y}/{url_path.rsplit('/', 1)[-1]}"
        if archive.is_archived(SOURCE, relpath, root):
            return archive.path_of(SOURCE, relpath, root)
    session = session or make_session()
    last_exc: NotPublished | None = None
    for fmt, url_path in candidates:
        try:
            content = _get(session, url_path)
        except NotPublished as exc:
            last_exc = exc
            continue
        if not content.startswith(b"PK"):
            last_exc = NotPublished(f"FO bhavcopy for {d}: response is not a zip")
            continue
        relpath = f"fo_bhavcopy/{d:%Y}/{url_path.rsplit('/', 1)[-1]}"
        return archive.store(SOURCE, relpath, content, HOSTS[0] + url_path,
                             meta={"trade_date": d.isoformat(), "format": fmt},
                             root=root)
    raise last_exc or NotPublished(f"FO bhavcopy for {d}")
