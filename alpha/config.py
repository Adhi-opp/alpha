"""Project-wide constants. No logic here."""
from __future__ import annotations

from datetime import date, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"
RAW_ROOT = DATA_ROOT / "raw"
DERIVED_ROOT = DATA_ROOT / "derived"

IST = timezone(timedelta(hours=5, minutes=30), "IST")

# First trade date published in UDiFF format (BhavCopy_NSE_FO_...); earlier
# dates use legacy foDDMMMYYYYbhav.csv.zip. Both fetchers verified live
# 2026-07-07 (UDiFF: 2026-07-06 file; legacy: 2024-01-05 file).
# VERIFY the exact cutover date the first time a backfill crosses mid-2024:
# the fetcher falls back to the other format on NotPublished, so a wrong
# constant costs one extra request, not data.
UDIFF_START = date(2024, 7, 8)

# Conservative publication times in IST used to stamp available_at.
# nse_fo_bhavcopy: zip mtime observed 18:17 IST (2026-07-06) -> 19:30 buffer.
# nse_participant_oi: evening publication, not yet measured -> 22:00.
# Tighten only with measured evidence (log observed publish times in ops).
PUBLICATION_TIME_IST: dict[str, tuple[int, int]] = {
    "nse_fo_bhavcopy": (19, 30),
    "nse_participant_oi": (22, 0),
}
