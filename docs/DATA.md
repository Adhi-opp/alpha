# Data: sources, lag discipline, and the broker decision

## The broker/data decision (2026-07-07)

**Dhan: yes — free account now, one paid Data-API month later, then cancel.**
**Upstox: keep, free tier only. Do not buy any Upstox paid tier for Alpha.**
**No live tick infrastructure in Alpha at all.**
*(the "no live tick infrastructure" line is AMENDED 2026-07-12 — see
"Bounded live capture amendment" below; the rest of this decision stands)*

Reasoning, so this doesn't get relitigated:

- Alpha's studies need **historical minute-level option premium paths**
  (H-001b labels P&L on the option, not the underlying). Dhan's Data API
  bulk pull (≈₹499+GST for a month, ~₹590; second month only if the gap
  census demands refetches, worst case ~₹1,180) is the only clean-provenance
  source at rounding-error cost. That pull is **one-time**: history lands on
  our disk, ongoing dailies come free from NSE archives.
- Alpha does **not** need live continuous ticks. It is a positional system:
  tickets are emitted in the evening or at the open, from EOD files. The only
  live data it ever uses is a REST quote snapshot at ticket-emission time —
  free Upstox does that. Real-time is GammaLeak's lane; rebuilding tick
  infrastructure here would repeat the exact pain Alpha was designed to avoid.
- If H-002 (intraday trigger entries) ever earns a live slot, Dhan's
  market feed on the free account covers the handful of instruments a
  ticket names. Decide then, not now.
- GammaLeak's `.depth.csv` collection keeps running and will hand Alpha
  measured option-book spreads for the slippage model — no money buys that
  historically.

### Dhan sequence (order matters; the clock shouldn't run while coding)

1. Open the free Dhan account now (KYC, ~15 min). Subscribe to nothing.
2. Free layer first (done 2026-07-07): NSE fetchers + backfill in this repo.
3. Dry-run the bulk downloader before paying:
   `python scripts/dhan_pull.py --fetch-master` (free), implement
   `_resolve_security_ids()` against the real master columns, then
   `python scripts/dhan_pull.py --dry-run` and review the request plan.
4. Subscribe to Data APIs (≈₹499+GST) and burn the pull in the first days:
   NIFTY (and BANKNIFTY if wanted) weeklies, 3 years back, 1-minute.
5. Census before trust: gap census per session + cross-check sampled
   closes/OI against our bhavcopy parquet. Refetch inside the same month.
6. **Cancel.** Dhan auto-debits renewal from the trading ledger every 30
   days — set a calendar reminder AND keep the ledger empty after the pull
   so it cannot renew silently.

## Bounded live capture amendment (owner-directed, 2026-07-12)

The 2026-07-07 line "no live tick infrastructure in Alpha at all" existed to
stop Alpha becoming GammaLeak. The owner has now explicitly directed a live
observation layer (docs/LIVE_DESK.md), so the line is amended to a BOUNDED
definition instead of a blanket ban:

**Allowed:** session-scoped capture of the Upstox v3 websocket feed for a
defined instrument set (index spot, front future, front-week option chain in
a fixed strike band, both NIFTY/NSE_FO and SENSEX/BSE_FO), recorded
append-only under `data/live/` with dual timestamps (exchange + local
receipt). Purpose: measured half-spreads, latency, seconds-level MAE, and a
descriptive in-session cockpit. Everything it shows is an instrument
reading; verdicts still come only from the ledger.

**Still excluded, permanently:** full-depth tick-by-tick order-book
reconstruction, any order-routing or execution hook (execution is manual by
constitution), any live feature becoming a trade rule without its own
pre-registered ledger entry, and any paid Upstox tier.

The live layer is firewalled: `alpha/live/` may import from `alpha/`, but
nothing in `alpha/data`, `alpha/study`, or the ledger machinery may import
from `alpha/live`. Live capture feeds studies only after it lands as a
normal PIT dataset with a census.

## Source inventory

| Dataset | Source & URL pattern | Format | available_at (IST) | Status |
|---|---|---|---|---|
| Participant-wise OI | `nsearchives.nseindia.com/content/nsccl/fao_participant_oi_DDMMYYYY.csv` | CSV, rows Client/DII/FII/Pro/TOTAL | 22:00 (conservative; publication observed evenings, not yet measured) | fetcher live-verified 2026-07-07 |
| F&O bhavcopy (UDiFF, ≥2024-07-08) | `.../content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip` | zip/CSV, TradDt schema | 19:30 (zip mtime observed 18:17) | fetcher live-verified 2026-07-07 |
| F&O bhavcopy (legacy, <2024-07-08) | `.../content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip` | zip/CSV, INSTRUMENT schema | 19:30 | fetcher live-verified 2026-07-07 (2024-01-05 file) |
| Dhan 1-min option candles | Data API, see `alpha/data/dhan_bulk.py` | JSON | historical only | skeleton; endpoints/schema UNVERIFIED |
| Upstox candles/quotes | v3 API, OAuth token | JSON | live/historical | not yet ported (Phase 1) |
| Global context (USDINR, Brent, UST) | yfinance | — | next IST open, conservative | not yet built |

## Measured facts (data beats lore)

- **NIFTY lot size is 65** in the 2026-07-06 bhavcopy (`NewBrdLotQty`). It
  has changed repeatedly; always read per-contract from the file.
- **NSE's participant-OI TOTAL row is internally off by ±1** on some columns
  (observed 2026-07-06: put-long sum 5,647,549 vs TOTAL 5,647,550).
  Integrity guard tolerates |diff| ≤ 2 as WARN, errors beyond.
- FO bhavcopy zip published **18:17 IST** on 2026-07-06 → `available_at`
  19:30 IST is honest.
- Legacy bhavcopy has **no lot size and no underlying price** columns; both
  are NaN pre-2024-07-08 and anything needing them must handle that.

## VERIFY ledger (unverified until checked; blocks paid/live steps)

- Dhan: instrument-master URL & columns, intraday endpoint path, request
  body field names, per-request span limit (30d assumed), rate limit,
  response schema. Verify in step 3 above, against docs + one real response.
- Exact UDiFF cutover date (2024-07-08 assumed; fetcher self-heals near it).
- Participant-OI actual publication time (log observed times in ops; only
  then consider tightening `PUBLICATION_TIME_IST`).
- Upstox historical candle retention limits per interval (Phase 1).
