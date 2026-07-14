# Live Desk — bounded real-time observation layer

Owner-directed 2026-07-12, after external review of the design by two other
models. This document is the synthesis and the build contract. It amends
docs/DATA.md (bounded capture) and changes NOTHING about the constitution:
manual execution, verdicts only from the ledger, pre-registration before any
claim.

## What this layer is for

1. **Pay three standing debts with one instrument:** measured option
   half-spreads (the 0.25% estimate is the weakest input in every study),
   real signal→fill latency at the paper stage, and seconds-level MAE for
   the owner log (the 1-min floor disappears for future sessions).
2. **A descriptive in-session cockpit** ("altimeter, not co-pilot"): OI
   walls + max pain with live migration, live spread width per strike (=
   the cost hurdle right now), intraday scalp-energy accumulation vs the
   H-003 pre-open rating. NO operational instructions, ever.
3. **A capture-first laboratory:** every session recorded becomes replayable
   data. Intraday claims (the owner's OI-wall test, IV-crush timing, a
   reformulated gamma hypothesis) get tested as pre-registered studies on
   minutes-scale n — thousands of observations, not 78 days.
4. **ML, later and honestly:** first model predicts an objective,
   trade-independent event — P(premium burst > live cost hurdle in next
   10 min | chain state) — logistic first, calibrated through the existing
   isotonic/Platt layer, purged walk-forward, shadow-scored until it earns
   a ledger entry. No model before enough sessions are captured.

## Decisions adopted from the external reviews

- **Dual-chain from day one (capture only):** NIFTY/NSE_FO AND
  SENSEX/BSE_FO. Four of the owner's six real sessions — and his largest
  P&L — are BSE SENSEX expiries; a NIFTY-only observation layer would
  instrument the wrong desk. BUT: capture ≠ modeling. No SENSEX-derived
  *claim* until a BSE study (with its own census) exists — mirrors the
  owner-log scope rule.
- **Static-wide strike band, not dynamic ATM chasing:** subscribe
  ATM±10 strikes AT OPEN and hold the band; retarget only if spot exits the
  inner ±5, and LOG every unsub/sub with timestamps so retargeting gaps are
  measured, not feared. (Review-flagged trap: chasing ATM during a fast
  move churns subscriptions exactly when data matters most.)
- **Ingestion isolated from disk:** the websocket recv loop only decodes
  and enqueues; a separate writer task batch-flushes segments. Every event
  carries provider timestamp / last-trade time AND one local receipt timestamp
  shared by all events from the same websocket message. That makes measured
  end-to-end receipt lag possible without calling a provider clock an exchange
  clock. (Review-flagged trap: blocking I/O in the recv loop poisons local
  timestamps.)
- **Replay before dashboard:** the recorder + replay tool ship first; the
  cockpit reads the same event stream, so any on-screen number can be
  reproduced offline from the session file. Live and offline math must
  agree or the feature is broken.
- **Naming discipline:** nothing is displayed as "dealer GEX". Public chain
  data supports "gamma concentration proxy" / "participant-positioning
  prior" — inference labels, not facts. The G002 NO-GO stands; any revived
  gamma claim needs a new registration.
- **On the "40 sessions is slow" critique:** H-004 gates the PROMOTION of
  the H-003 verdict; it does not gate this layer. Live-desk development and
  the forward log run in parallel — capture accrues while the log accrues.
  Nothing here waits on H-004, and H-004's bar does not loosen because
  waiting is boring.

## Architecture

```text
alpha/live/                     # firewalled: nothing outside imports it
  provider_upstox.py            # master, front-week resolution, ws frames, decode
  recorder.py                   # asyncio.Queue -> batched append-only segments
  collector.py                  # session orchestration: connect/subscribe/watchdog
  replay.py                     # re-emit a recorded session's events
data/live/<YYYY-MM-DD>/<run-id>/ # unique session captures (segments + manifest)
scripts/upstox_login.py         # OAuth token -> .env when setup/auth requires it
scripts/live_probe.py           # THE GATE: run one market session before
                                # any cockpit/feature code is written
scripts/live_capture.py         # normal bounded capture; never places orders
```

Truth-machine firewall: `alpha/data`, `alpha/study`, ledger machinery never
import `alpha/live`. Live capture becomes study-visible only after a normal
PIT ingest + census of the captured dataset.

## The probe gate (nothing else gets built until this runs green)

`scripts/live_probe.py` on the next market morning answers, with a written
findings file (docs/UPSTOX_FINDINGS.md, from real output — no guesses):

1. Token + REST sanity: LTP for NIFTY and SENSEX spot.
2. Master resolution: front-week expiry, strike step, band keys for BOTH
   chains (NSE_FO options + BSE_FO options + futures + indices).
3. Feed contents in `full` mode per instrument class: which of ltp/cp/vtt/
   oi/iv/greeks/tbq/tsq/5-level depth actually arrive, at what cadence.
4. Message and byte rates for the full dual-chain subscription (sizes the
   steady-state recorder; raw bytes kept during probe).
5. Subscription limit behavior: does the server accept ~90 keys in full
   mode on the free tier; what an over-limit rejection looks like.
6. The retarget drill: unsub 2 wing strikes, sub 2 new ones mid-session;
   measure handshake→first-tick latency.
7. Provider-ts / last-trade-ts vs local-receipt skew distribution.

## Sequencing

1. **Today (Sun):** package + probe + tests built offline. DONE = this doc.
2. **Mon 2026-07-13:** owner runs `upstox_login.py` if no valid token exists,
   then
   `live_probe.py --minutes 10` any time after 09:20 IST. Findings written.
3. **Tue 2026-07-14 (first rated expiry):** full-session capture for both
   chains (collector, no cockpit yet). Also the first H-004 forward session
   — journal as usual.
4. **Then:** seconds-level spread/MAE extraction from captures (replaces
   the 0.25% estimate with measured numbers; owner-log MAE gains a
   seconds-level upgrade path); cockpit v1 (walls, max pain, spread, energy
   vs rating); replay-verified.
5. **Later, each behind its own ledger entry:** OI-wall bounce study,
   IV-crush timing, gamma-concentration reformulation, then the first
   shadow ML state model.

## Commands

```text
# Interactive browser approval; paste the full callback URL when prompted.
# It writes the token only to gitignored .env and does not print credentials.
.venv\Scripts\python scripts\upstox_login.py

# Short raw probe. It writes a unique probe_<run-id> directory.
.venv\Scripts\python scripts\live_probe.py --minutes 10

# Normalized full-session capture; no order hooks. Add --keep-raw only when
# the additional raw storage is wanted explicitly.
.venv\Scripts\python scripts\live_capture.py
```

Every capture has a bounded recorder queue. A queue overflow halts the
session and marks its manifest degraded; a partial capture is never silently
treated as complete. Raw websocket payloads are written exactly once per
received provider message, while all normalized events derived from that
message share its local receipt timestamp.
