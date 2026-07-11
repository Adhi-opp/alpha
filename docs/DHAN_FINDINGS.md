# Dhan integration findings (2026-07-08)

Verified against the real account/data + the DhanHQ v2 docs. Updates as we learn.

## CORRECTION (supersedes the earlier "95.7% missing" conclusion)

An earlier version of this file concluded historical option data was largely
unavailable, because it looked for expired contracts in the daily active
security master (which by definition only holds LIVE instruments). That was
the wrong endpoint and the wrong data model. **The data exists.** Dhan serves
expired-option history through a dedicated rolling endpoint that never needs
an expired contract's security id. The absolute-strike universe approach in
`dhan_bulk.py` is the wrong frame for HISTORICAL options and is being
superseded by the rolling model below (it stays valid only for live-contract
lookups).

## The right endpoint: `/charts/rollingoption` (expired options, rolling ATM)

- **POST** `https://api.dhan.co/v2/charts/rollingoption`
- You pass the **UNDERLYING** securityId (e.g. NIFTY index — one stable id),
  NOT an expired option token. Strikes are requested **relative to ATM**, so
  there is nothing per-expiry to resolve.
- Request params (verified from docs):
  `exchangeSegment`, `interval` ∈ {1,5,15,25,60}, `securityId` (underlying),
  `instrument` (e.g. OPTIDX), `expiryCode` (which expiry — enum int),
  `expiryFlag` ∈ {WEEK, MONTH}, `strike` ∈ {ATM, ATM+10..ATM-10 for index
  options}, `drvOptionType` ∈ {CALL, PUT}, `requiredData` (array subset of
  open/high/low/close/iv/volume/strike/oi/spot), `fromDate`, `toDate`
  (YYYY-MM-DD, end non-inclusive).
- Response: `data.ce` and `data.pe` (the one not requested is null), each with
  arrays `open, high, low, close, volume, oi, iv, strike, spot, timestamp`.
- Limits: **up to 5 years** history, **30 days per call**, minute granularity.

### Why this is the right shape for H-001b (not just a fix)

H-001b needs rolling front-week **ATM straddle / near-ATM directional**
premium paths, entry near open, exit by close. The rolling endpoint returns
exactly that — a continuous front-week ATM series with spot, IV and OI
alongside — so the moneyness is always defined relative to spot, which is
what the strategy actually conditions on. Absolute strikes were never the
natural unit here.

### Recomputed pull size (tiny vs the old plan)

NIFTY front-week, offsets {ATM, ±1, ±2} × {CALL, PUT} = 10 rolling series ×
(~5 yr / 30-day windows ≈ 61 calls) ≈ **~610 calls**, ~5 min at 0.5s/call —
versus the ~thousands of per-contract requests the absolute-strike plan
implied. Widen offsets to ±5 only if a study needs the wings.

## Instrument master (still correct, for LIVE lookups + the underlying id)

- **URL:** `https://images.dhan.co/api-data/api-scrip-master-detailed.csv`
  (36 MB; the `api-scrip/...` path 403s).
- Columns verified: `EXCH_ID, INSTRUMENT (OPTIDX), UNDERLYING_SYMBOL,
  SM_EXPIRY_DATE, STRIKE_PRICE, OPTION_TYPE, SECURITY_ID, LOT_SIZE`.
- Still used for: the **underlying** securityId the rolling endpoint needs,
  live-contract resolution, and daily lot-size/expiry snapshots. The daily
  index-option snapshot (`snapshot_index_option_master`, 13,516 rows/day)
  stays useful for forward lot-size/expiry provenance.

## VERIFIED LIVE 2026-07-09 (probe matrix, raw responses in data/raw/dhan/_probe/)

- **securityId = Dhan's own INDEX id from the master's INSTRUMENT=INDEX row
  (NIFTY = "13")**. NSE's underlying id (26000) returns HTTP 200 + empty
  arrays — a silent wrong-id trap.
- **exchangeSegment = "NSE_FNO"** (IDX_I → empty).
- **expiryCode is 1-indexed**: 1 = front weekly, 2 = next weekly (confirmed
  by the IV differential 14.17 vs 11.64 on identical strike/spot). 0 is
  rejected by a falsy server-side "required" check (DH-905).
- **toDate is INCLUSIVE** — docs say non-inclusive; reality wins.
- Sessions arrive complete: 375 one-minute candles 09:15–15:29 IST.
- **The front-week series ROLLS the morning after expiry** (verified across
  2026-06-30: expiry-day IV spikes 17.2 at open, dies to 0.000 on the
  expiring contract's last candles, reopens 12.8 on the new front week).
- **The series is a rolling-ATM COMPOSITE, not one contract**: the
  per-candle `strike` re-selects intraday as spot moves. Tradeable
  fixed-strike paths are reconstructed by pulling the ATM±10 offset fan and
  re-keying rows by (timestamp, strike, side) — `alpha/data/dhan_rolling.py`
  `tidy_archive_to_parquet` does exactly this.
- Client: `alpha/data/dhan_rolling.py`; pull: `scripts/dhan_pull_rolling.py`
  (~1,554 calls, resumable). Rate limit still undocumented — 0.5 s/req held.

## SENSEX / BSE — VERIFIED LIVE 2026-07-11

- **securityId = "51"** (Dhan's own INDEX row for SENSEX),
  **exchangeSegment = "BSE_FNO"**. The options rows' UNDERLYING_SECURITY_ID
  ("1") is the SAME silent trap as NIFTY's 26000: HTTP 200 + empty arrays.
- Verified: 375 candles/session, ATM strike tracks spot (76600 vs 76587.55),
  weekly expiryFlag works, lot 20 (from master).
- Pull: `scripts/dhan_pull_rolling.py --symbol sensex` (then `--tidy`) →
  `derived/dhan_rolling_1m_sensex/`.
- **CAVEAT: single-source.** No BSE bhavcopy layer exists, so SENSEX
  premiums have no independent cross-check. Certified for owner-log MAE
  diagnostics ONLY; any pre-registered SENSEX study first needs a BSE
  bhavcopy ingest + census (the NIFTY census's close-definition lesson
  will apply there too).

## Cost model note (measured from the same session's contract notes)

BSE SENSEX options charge a different exchange transaction rate (0.0325%) than
NSE NIFTY (0.0355%); options STT is confirmed sell-side 0.15%. Both encoded in
`alpha/measure/costs.py` with golden tests. You trade SENSEX (BSE) and NIFTY
(NSE).

## Sources

- https://dhanhq.co/docs/v2/expired-options-data/
- https://dhanhq.co/docs/v2/historical-data/
