# H002 — Intraday calm-bar entry: same signal, expression redesigned around the killer

- **Status:** INVERTED (redesign worked mechanically; the structure still loses)
- **Registered:** 2026-07-11 (frozen 353648e4b068d872)  **Verdict date:** 2026-07-11
- **Family index:** 8

## Hypothesis

[[H001b]] proved the conditioning is real (+₹1,603 top-vs-bottom differential,
CI [+805, +2270]) and named what killed the expression: adverse fills at the
volatile open (−₹560 of the −₹804 loss). H002 is the pre-registered fallback
that H001b's NO-GO clause anticipated: on the SAME heavy-writing days, delay
entry past the open-volatility window to the first CALM bar. If the trend
persists through the day (H001r's claim is day-level trendiness, not
first-hour trendiness), the conditioning edge should survive a later entry
while the −₹560 entry drag collapses toward the calm-bar base rate.

## Pre-registration (FROZEN before any result is seen)

- **Universe & period:** NIFTY front-week options (`dhan_rolling_1m` tidy,
  census GREEN 2026-07-09 for premium levels), decision days
  2024-07-09 → 2026-01-08. Holdout 2026-01-09 → 2026-07-06 stays locked.
- **Conditioning:** identical to [[H001b]] — ticket-eligible on days where
  wi(T−1) ≥ trailing-252-session 66.7th percentile (PIT rolling cut);
  counterfactual book: days below the trailing 33.3rd percentile.
- **Entry trigger (the redesign):** scan bars t ∈ [30, 225] (intents
  09:45–13:00 IST; never earlier than bar 30 so the volatility test always
  has full trailing history). Trigger = the FIRST bar t where BOTH legs of
  the minute-t ATM strike are calm — range ≤ trailing-30-bar 75th
  percentile, i.e. NOT volatile under the same frozen AdverseFillModel test
  H001b used (a NaN-history bar counts volatile, hence never triggers).
  The trigger is deterministic per day. **No calm bar by 13:00 → no ticket
  that day** (counted and reported per book; the strategy chooses not to
  trade, it does not get to pretend the day never happened).
- **Structure:** long 1 lot ATM straddle, strike nearest spot at the ENTRY
  ARRIVAL minute (re-selected at arrival, as H001b). Lot from bhavcopy.
  No intraday stop.
- **Entry:** order intent at the close of trigger bar t; entry time =
  t + latency draw. Latency: OWNER_2026_07 LogNormal(μ=4.55, σ=0.90) s,
  NO-FILL past 900 s. FOCUSED_DESK (μ=3.4, σ=0.5) reported as sensitivity,
  never baseline.
- **Exit:** order intent at the 15:20 bar, independent latency draw, fills
  capped at 15:29. Both legs.
- **Fills:** AdverseFillModel semantics exactly as H001b — volatile arrival
  bar ⇒ buy at bar HIGH / sell at bar LOW, else close; half-spread on top:
  **0.25% baseline (ESTIMATED), 0.50% stress**. The entry arrival bar gets
  no special treatment: if the market turns volatile between trigger and
  arrival, the fill pays for it (that risk is the strategy's to carry).
- **Costs:** ZERODHA_NSE_OPTIONS_2026_07, 4 orders/ticket.
- **Monte Carlo:** 400 latency draws per ticket-day (seed 12); day-level EV
  = mean net ₹ across draws (no-fill draws contribute 0; truncated draws
  excluded and counted; day dropped and listed if > 50% truncated).
- **Bootstrap:** day-level EVs → MBB (block 10 sessions, 4,000 resamples,
  seed 46) for CIs; two-sided bootstrap p.
- **Primary outcome:** mean net ₹/ticket across TRIGGERED top-cut days at
  half-spread 0.25% under the owner latency model.
- **GO criteria (ALL):**
  1. Primary mean net EV > 0 with 90% MBB CI excluding 0;
  2. Point EV still > 0 at the 0.50% half-spread stress;
  3. Conditioning differential: triggered top-cut EV − triggered bottom-cut
     EV > 0 with 90% MBB CI excluding 0;
  4. Bootstrap p ≤ 0.0125 (BH q=0.10, family m=8);
  5. Split-half: primary EV same sign in both chronological halves.
- **NO-GO:** any gate fails → record the attribution (gross-ex-friction /
  latency / adverse / spread / statutory) and the entry adverse-hit rate;
  if the adverse drag did NOT collapse versus H001b's −₹560, the redesign
  premise itself is wrong and calm-bar timing is dead as a family branch.
- **Secondary (reported, NOT gated):** entry adverse-hit rate (design
  target: near the ~25% calm-regime base rate vs H001b's 100%); trigger
  rate per book; hold-time distribution (trigger bar histogram); expiry-day
  vs non-expiry split; FOCUSED_DESK sensitivity; per-leg attribution;
  fill/no-fill rates; bottom-book EV.
- **Data:** `dhan_rolling_1m` (census green, candle OI not consumed),
  `participant_oi`, `fo_bhavcopy`; cost model as of commit 363546f.

## Data used

Identical stack to [[H001b]]: `dhan_rolling_1m` tidy (census GREEN for
premium levels, candle OI not consumed), `participant_oi` conditioning,
`fo_bhavcopy` lot/expiry, `ZERODHA_NSE_OPTIONS_2026_07`, `OWNER_2026_07`
latency. Only the entry rule differs — by design, so the verdict delta is
attributable to it. Results JSON: ledger/results/h002_20260711.json.

## Results

n = 248 gradeable ticket-days (173 top / 75 bottom), 1 untriggered top day,
0 dropped. Trigger fires almost immediately once eligible (bar quartiles
30/30/31 — by 09:45 the open storm has usually passed the relative test).

| gate | result | detail |
|---|---|---|
| 1 primary EV CI | **FAIL** | mean net **−₹382**/ticket, 90% CI [−769, −25] |
| 2 stress 0.50% | **FAIL** | −₹453 |
| 3 conditioning diff | **PASS** | top − bottom **+₹1,486**, CI [+852, +2137] |
| 4 BH p | FAIL | p=0.0775 vs 0.0125 |
| 5 split-half sign | PASS | −321 / −443 (both negative) |

**The redesign delivered exactly its mechanical promise:**

| metric | H001b (open entry) | H002 (calm entry) |
|---|---|---|
| entry adverse-hit rate | 100% (by construction) | **28.6%** (≈ the ~25% base rate predicted) |
| adverse drag | −₹560 | **−₹164** |
| total EV | −₹804 | **−₹382** (loss halved) |
| conditioning differential | +₹1,603 | +₹1,486 (robust to the redesign) |

Attribution (₹/ticket): gross ex-friction −84, latency **+62** (latency now
mildly HELPS — arriving late on a trending day means buying after the move
started less often than it means missing decay), adverse −164, spread −72,
statutory −128.

Secondary: **expiry-day EV +₹1,328** (n=25) vs non-expiry **−₹671** —
stronger than H001b's +924/−1,096 split. Per-leg CE +261 / PE −518.
Bottom book −₹1,868. FOCUSED_DESK −₹440 (faster hands still don't save it).

## Verdict & rationale

**INVERTED.** Fixing the fill problem was necessary but not sufficient: with
adverse drag collapsed to −164, the residual loss is now dominated by the
STRUCTURE, not the execution. The frictionless gross is −₹84 — on
non-expiry days, the extra trendiness that heavy writing buys you
approximately PAYS the day's theta and no more, and no entry timing can
beat a ₹364 irreducible friction stack (adverse + spread + statutory) from
a position whose edge-over-theta is ~zero.

Two independent expressions have now shown the same two facts:
1. **The conditioning differential is real and robust** (+1,603 and +1,486,
   both CIs excluding zero) — H001r's signal prices into premium space.
2. **The all-day ATM straddle is the wrong vehicle** — its theta bill on
   non-expiry days eats the entire differential.

And both point the same direction: **expiry day**, where theta is almost
spent and gamma is extreme — +924 (H001b) and +1,328 (H002) on the same 25
days. CAUTION recorded: the two secondaries are the SAME days under two
entry rules, not independent samples; n=25 is a hypothesis generator. The
successor is H-003 (expiry-day-only long premium, own pre-registration,
family m=9, BH bar 0.0111). If H-003 dies, the H001 branch is exhausted at
the buyer-expressible level and the ledger moves to the next candidate
family. Holdout stays locked.
