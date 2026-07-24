# Upstox v3 findings (from real probe output — no guesses)

## Token types (operational fact, 2026-07-14)

Upstox issues TWO distinct token types and they must not be conflated:

- **Analytics Token** (`UPSTOX_ANALYTICS_TOKEN`) — read-only, ~ONE-YEAR
  validity, supports market-data REST and v3 websocket streaming. This is
  **Alpha's primary credential** (`alpha/live/auth.py` prefers it
  automatically). There is NO daily-login requirement in normal operation.
- **Standard OAuth access_token** (`UPSTOX_ACCESS_TOKEN`) — expires ~03:30
  IST the next day (decoded from the token's own `exp`). OPTIONAL fallback
  only; `scripts/upstox_login.py` mints one when explicitly needed and
  writes ONLY that line, never touching the analytics token.

**Probe #1 below ran on a standard daily OAuth token** (the analytics
token was not yet in `.env`). Normal Alpha operation uses the Analytics
Token; its REST + websocket behavior must be verified once when it lands
(the probe does both on every run).

## Probe #2 — 2026-07-24 ~14:12 IST (MARKET OPEN; gate = GREEN) ✅

Recording: `data/live/2026-07-24/probe_141223_431602_fb5cf8d4/` (raw kept).
The market-hours gate the project was blocked on. Clock verified correct
(preflight skew **−0.35 s**), analytics token, both gate segments
NORMAL_OPEN. Everything PENDING after probe #1 is now measured:

- **Live streaming CONFIRMED:** 69,400 `live_feed` messages (probe #1: 0),
  66,514 option ticks + 2,978 index ticks over 597 s = **111 ticks/s**
  across 86 subscribed instruments; 92 `initial_feed` snapshots on connect.
- **Field coverage (option ticks):** depth-5 100%, oi 100%, tbq 100%,
  atp 100%, iv 97.8%, gamma 97.8%. The full instrument set the cockpit
  needs — per-strike spreads, OI, greeks — is on the wire in `full` mode
  on this analytics token (`isPlusPlan: false`).
- **Retarget drill:** unsub 2 wing strikes → resub → first tick = **40 ms**.
  The static-band + measured-retarget design works and is fast.
- **Clocks:** provider-vs-local preflight skew −0.35 s; per-tick receipt
  skew median −348 ms / p95 −324 ms (network + provider stamp lag — the
  local clock is sound). Exchange `ltt` runs ~1 s ahead of receipt.
- **Recorder under real load:** 44 KB/s raw (≈1 GB per full 6.25 h session
  if `--keep-raw`; normalized events far smaller), queue high-water
  **4 / 10,000**, **0 reconnects, 0 errors, 0 degradation**. Replayable.
- **Front-week resolution live:** NIFTY 2026-07-28 (105 strikes, band
  23300..24300), SENSEX 2026-07-30 (189 strikes, band 75100..77100),
  both futures resolved.

**Gate GREEN with zero failures.** The cockpit build (walls, max pain,
spread-vs-hurdle, energy-vs-rating) and seconds-level spread/MAE extraction
are unblocked. Next: full-session `live_capture.py` runs, then the desk.

## Probe #1 — 2026-07-14 ~21:22 IST (MARKET CLOSED; gate = PARTIAL)

Recording: `data/live/2026-07-14/probe_092152_014524_4cd0fae0/` (raw kept).
A valid AFTER-HOURS INFRASTRUCTURE test — explicitly NOT a green
market-hours gate. Under the hardened grading (added after this run) it
scores PARTIAL: every infra check passed; live market behavior was
unobservable.

### The clock incident (root cause of a misread session)

The machine's Windows clock was **exactly 12 hours behind** (AM/PM flip):
local said Tue 09:21, reality was Tue 21:21 (verified against an external
HTTP `Date` header: local 09:39:36 vs Google 16:09:34 GMT = 21:39 IST).
Every "anomaly" the probe surfaced was the feed being RIGHT about a world
we had mislabeled:

- `market_info` segmentStatus: NSE_FO/BSE_FO `NORMAL_CLOSE`, NSE_INDEX
  `CLOSING_END`, MCX_FO + US_EQ `NORMAL_OPEN` — correct for ~21:40 IST.
- Feed `currentTs` "12h ahead of local" — the feed was on time; we weren't.
- REST LTP + ws snapshots frozen at the session's closing values.
- Dhan served a complete 375-candle day for "today" — because today was
  already over.

**Standing lesson (cheap to keep):** before any session-time logic, sanity
check the local clock against an external source; the collector's
session-end guard and every `t_local_ns` ride on it. A PIT platform on a
wrong clock poisons its own receipts.

### What IS verified from this probe (valid regardless of market state)

- **Auth:** the daily OAuth token works for v2 REST LTP, direct-Bearer v3
  websocket connect, AND the `/v3/feed/market-data-feed/authorize` flow
  (both ws paths accepted the connection and served data). The Analytics
  Token (the primary) still needs its one-time REST+ws verification when
  it lands in `.env`.
- **Master + resolution:** CDN master parses; front-week resolution landed
  NIFTY 2026-07-14 (99 strikes) and SENSEX 2026-07-16 (166 strikes) with
  futures; SENSEX50/NIFTYNXT50 disambiguation held on real rows.
- **Subscription:** 88 keys in `full` mode accepted in two 50-key frames —
  no rejection, no error frame, all 86 subscribed instruments returned
  initial snapshots. Free-tier limit is therefore >= 88 in full mode.
- **Snapshot field coverage** (initial_feed, options): depth 5-level 100%,
  oi 100%, atp 100%, iv 73%, greeks (gamma nonzero) 52%, tbq/tsq 76% —
  zeros plausibly genuine (far wings) rather than absent fields.
- **Closed-market behavior:** snapshot-per-subscribe only, `initial_feed`
  type, zero `live_feed` messages; a silent-feed watchdog then reconnects
  every 30 s (19 clean reconnect cycles — the reconnect path is
  battle-tested now).
- **Recorder/replay:** ~1.8k events + 57 raw frames recorded, replayed,
  and re-decoded offline (message-type census done from raw bytes alone).
- **Recorder headroom:** queue high-water 4 / 10,000 — no overflow, no
  degradation, across 19 reconnect cycles.

### PENDING — needs a probe during a LIVE session

- `live_feed` streaming cadence + per-instrument update rates in full mode
- message/byte rates for the dual-chain 88-key subscription (recorder sizing)
- retarget drill (unsub/resub handshake -> first tick latency)
- real clock-skew distribution (provider `currentTs` and exchange `ltt` vs
  a CORRECT local clock)
- whether `full` mode streams on the free/non-Plus plan at all (token
  claims `isPlusPlan: false`; snapshot behavior can't discriminate — a
  closed market serves snapshots to everyone)

Next probe: first trading morning with (1) the Windows clock fixed —
the probe now runs a clock preflight and ABORTS (CLOCK_INVALID, exit 3)
when |local − provider| > 5 s, publishing no market statistics; (2) a
token in `.env` — the Analytics Token if available, else a fresh daily
OAuth fallback; (3) market open — `scripts\live_probe.py --minutes 10`
any time 09:20–15:15. GREEN requires live_feed streaming, fresh trades,
and a measured drill latency; a closed market can only ever grade PARTIAL.
