# NEXT_STEPS — solo-continuation runbook

Written so any step can be done without Claude. Do them in order; each has a
"done when" so you know it worked. Nothing here spends money except step 4,
and it says so loudly.

## 0. Daily habit (from today)

```
cd d:\alpha
.venv\Scripts\python scripts\fetch_daily.py
```
Run any evening after ~22:30 IST (or next morning — it defaults to the last
weekday). **Done when:** exit code 0 and both datasets print `-> derived`.
Red days (exit 1) are integrity failures: do not use that day downstream;
investigate first.

Optional: Windows Task Scheduler, daily 22:45, action =
`d:\alpha\.venv\Scripts\python.exe d:\alpha\scripts\fetch_daily.py`.

## 1. Backfill 3 years of the free layer (~1–2 hours, resumable)

```
.venv\Scripts\python scripts\backfill.py --start 2023-07-01 --end 2026-07-06
```
Safe to Ctrl-C and re-run; archived days are skipped. Legacy vs UDiFF format
is handled automatically. **Done when:** the summary prints 0 failures and
`data/derived/fo_bhavcopy/` has 2023–2026 parquets.

Then the gap census (paste into a `python` shell):
```python
from alpha.data import pit, integrity, calendars
bhav = pit.load_all_unsafe("fo_bhavcopy")
poi  = pit.load_all_unsafe("participant_oi")
tdays = calendars.trading_days(bhav)
pdays = sorted(poi["trade_date"].dt.date.unique())
for issue in integrity.gap_report("participant_oi", pdays, tdays):
    print(issue)
print(calendars.expiry_weekday_counts(bhav, "NIFTY"))
```
**Done when:** gaps are listed and explained (NSE holidays are fine), and the
expiry weekday table matches expectations (Tuesdays dominate recent years,
Thursdays in the legacy era, scattered holiday shifts — that mix is exactly
why nothing hardcodes a weekday).

## 2. Dhan free account (~15 min, ₹0)

Open the account, complete KYC, subscribe to NOTHING. Get the client ID and
an access token from the DhanHQ web console when ready.

## 3. Dhan downloader, still ₹0 — REPLANNED 2026-07-09 (rolling model)

Steps 1–3 of the original plan are DONE (master archived, columns verified,
`resolve_security_ids()` implemented). But the absolute-strike bulk plan is
the WRONG FRAME for history: the live master only lists live contracts, so
expired strikes can't be resolved from it. The right endpoint is
**POST /v2/charts/rollingoption** (expired-options data): pass the UNDERLYING
securityId + expiryFlag WEEK/MONTH + expiryCode + CALL/PUT + strike as an
ATM-relative offset (ATM, ATM±1…±10); get 1-min open/high/low/close/volume/
oi/iv/strike/spot back, up to 5 years, 30 days/call. Full spec + recomputed
pull size (~610 calls for NIFTY front-week ATM±2): docs/DHAN_FINDINGS.md.

Remaining ₹0 step: run `scripts/dhan_probe.py` with a fresh env token to pin
down `expiryCode` semantics, the underlying securityId, and the timestamp
convention — then build `alpha/data/dhan_rolling.py` against the verified
response, never a guess.

**Done when:** one probe response is archived and the rolling client's
request/parse code is written against it, with tests.

## 4. THE PAID STEP (≈₹590 once)

Subscribe to Data APIs. Set env vars and burn the pull immediately:
```
set DHAN_ACCESS_TOKEN=...   (or $env:DHAN_ACCESS_TOKEN='...' in PowerShell)
set DHAN_CLIENT_ID=...
python scripts/dhan_pull.py --execute
```
Resumable — a crash costs nothing, rerun it. Then census: per-session gap
check on minutes; cross-check ~20 sampled contract closes/OI against our
bhavcopy parquet. Refetch discrepancies within the month. Then **cancel the
subscription and empty the trading ledger** (auto-debit warning in
docs/DATA.md). **Done when:** raw JSON archived per chunk + census written
up as a short note in docs/, subscription cancelled.

## 5. Phase 1 measurement layer — BUILT 2026-07-08 (53 tests green)

All four pieces exist and are tested. Files landed as `costs.py`,
`labeler.py`, `execution.py`, `grader.py` under `alpha/measure/`.

1. **Cost model** (`alpha/measure/costs.py`): fitted to and verified against
   your REAL **Zerodha** contract note (CNT-26/27-55126969) — not Upstox;
   you trade on Zerodha and Upstox is only the project's data API. The
   golden test (`tests/test_costs_golden.py`) reproduces that note's every
   charge line to the rupee. `breakeven_move()` gives the cost hurdle every
   long-premium hypothesis must clear (measured: ~0.4–1.5% of premium for
   1–4 NIFTY lots).
2. **Triple-barrier labeler** (`alpha/measure/labeler.py`): target/stop/time,
   MAE+MFE, same-bar ambiguity resolves to the STOP, data gaps become
   `truncated` (never a silent time-exit).
3. **Execution fill model** (`alpha/measure/execution.py`): manual signal→
   fill delay + half-spread; spread is a REQUIRED input (no silent zero) and
   every fill is flagged `spread_estimated` until real depth data exists.
4. **Counterfactual grader** (`alpha/measure/grader.py`): composes the three;
   grades taken tickets AND abstentions identically; `summarize()` reports
   them apart so censoring stays visible.

Remaining for full Phase 1 acceptance (do at the study-runner stage):
a synthetic strategy with known true EV recovered within CI (grader tests
already show the deterministic version; the CI version needs the bootstrap
from Phase 2), and a lookahead-poisoned variant caught by the PIT accessor.

### >>> HUMAN INPUT NEEDED (AI must not invent these) <<<

RESOLVED 2026-07-08 (three more Zerodha notes supplied):
- ~~STT basis~~ → CONFIRMED sell-side 0.15% (asymmetric NSE note discriminates:
  sell-side fits 360.00 to Rs 0.29, both-sides off by Rs 4.84).
- ~~Exchange txn rate cross-check~~ → done, and it revealed BSE (0.0325%) ≠ NSE
  (0.0355%); model is now exchange-aware with golden tests for both.
- ~~Dhan instrument-master columns~~ → verified; URL corrected;
  `resolve_security_ids()` implemented and tested.

STILL OPEN (load-bearing; promotion blocked until supplied):
- **[DHAN — probe before pull]** RESOLVED in principle 2026-07-09: expired
  option history EXISTS via /v2/charts/rollingoption (ATM-relative, underlying
  id, 5yr, 30d/call — see §3 and docs/DHAN_FINDINGS.md; the earlier "95.7%
  missing" conclusion was an error from querying the live-only master). Still
  needed from you: a fresh token in `.env`, then `python scripts/dhan_probe.py`
  once, so `expiryCode` semantics and the timestamp convention are verified
  before the rolling client is written and the paid month is spent.
- **[SPREAD — real half-spreads]** The fill model needs a half-spread passed
  in and marks every fill `estimated`. Source: GammaLeak's `.depth.csv`
  option order-book collection — point me at it once it has accumulated and
  I'll flip `spread_is_measured=True`.
- **[LEDGER — the 3 missing dead studies]** `ledger/README.md` needs the
  other three GammaLeak-era NO-GO hypotheses named, so the multiple-testing
  family count is exact. One line each is enough.
- **[TOKEN — revoke the pasted one]** Revoke the access token shared in chat
  and generate a fresh one; keep tokens in `.env` (gitignored), never chat.

## 6. Only then: studies

H-001r pre-registration (copy `ledger/TEMPLATE.md` → freeze criteria →
run). Then H-001b. The study runner that enforces pre-reg hashing gets
built as part of this step.

## Standing rules (apply to every step above)

- Studies read data ONLY via `pit.load(dataset, asof)`. `load_all_unsafe`
  is for ops/calendars/integrity, and its name is the grep handle.
- Raw files are immutable; a changed refetch becomes `.revN`, never an
  overwrite.
- Anything tagged VERIFY blocks the step that depends on it.
- No strategy code before Phase 1 is green. No live money, period — paper
  gates are in docs/ARCHITECTURE.md §7.
