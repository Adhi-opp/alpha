# H001b — The tradeable question: long premium on heavy-writing days, at full cost

- **Status:** INVERTED (primary significantly negative; conditioning gate passed)
- **Registered:** 2026-07-09 (frozen 4fbaac5dae6b0456)  **Verdict date:** 2026-07-09
- **Family index:** 7

## Hypothesis

On days conditioned trendier by heavy retail option-writing ([[H001r]] GO,
+0.116 tercile diff), buying the front-week ATM straddle at the open and
selling it before the close earns positive net expected value AFTER theta,
bid-ask spread, adverse fills, statutory costs, and the owner's real manual
latency. This — not H001r — is the claim that could ever justify a ticket.

## Pre-registration (FROZEN before any result is seen)

- **Universe & period:** NIFTY front-week options (Dhan rolling ec=1 tidy
  dataset, census-checked), decision days 2024-07-09 → 2026-01-08.
  Holdout 2026-01-09 → 2026-07-06 stays locked.
- **Conditioning:** wi(T−1) exactly as [[H001r]] (available_at-aligned).
  **Trade rule:** ticket on days where wi(T−1) ≥ trailing-252-session 66.7th
  percentile (PIT-safe rolling cut — full-sample terciles would leak the
  cut itself). Counterfactual book: identical simulation on days BELOW the
  trailing 33.3rd percentile (the abstention side, graded per constitution).
- **Structure:** long 1 lot ATM straddle (CE + PE at the strike nearest spot
  at the ENTRY ARRIVAL minute, from the ±10 fan). Lot size per date from
  bhavcopy `lot`. No intraday stop (defined-risk premium); this isolates
  the trendiness-pays-gamma thesis from stop-path modeling.
- **Entry:** signal exists from the prior evening → order intent at the
  09:15 bar. Entry time = 09:15 + latency draw. **Latency: LogNormal
  (μ=4.55, σ=0.90) s, censored NO-FILL past 900 s — fitted to the owner's
  own report ("30 s to 5 min, max stretch 15 min"). The optimistic desk
  profile (μ=3.4, σ=0.5) is a reported sensitivity, never the baseline.**
- **Exit:** order intent at the 15:20 bar, same latency model (independent
  draw), fills capped at 15:29. Both legs.
- **Fills:** AdverseFillModel — volatile arrival bar (range > trailing-30-bar
  75th pct) ⇒ buys at bar HIGH / sells at bar LOW; else close. Half-spread
  on top: **0.25% baseline (ESTIMATED — no depth data yet), 0.50% stress**.
- **Costs:** ZERODHA_NSE_OPTIONS_2026_07, 4 orders/ticket (2 legs × 2 sides).
- **Monte Carlo:** 400 latency draws per ticket-day (seed 11); day-level EV =
  mean net ₹ across draws. Day-level EVs then feed MBB (block 10 sessions,
  4,000 resamples, seed 44) for CIs; two-sided bootstrap p.
- **Primary outcome:** mean net ₹/ticket across qualifying (top-cut) days at
  half-spread 0.25% under the owner latency model.
- **GO criteria (ALL):**
  1. Primary mean net EV > 0 with 90% MBB CI excluding 0;
  2. Point EV still > 0 at the 0.50% half-spread stress;
  3. Conditioning differential: top-cut mean EV − bottom-cut mean EV > 0
     with 90% MBB CI excluding 0 (the edge must come from the conditioning,
     not from "straddles always print");
  4. Bootstrap p ≤ 0.0143 (BH q=0.10, family m=7);
  5. Split-half: primary EV same sign in both chronological halves.
- **NO-GO:** any gate fails → record which component ate the edge (theta /
  spread / adverse fill / statutory / latency), because that attribution is
  the pre-registered fallback's design input ([[H002]] intraday trigger).
- **Secondary (reported, NOT gated):** expiry-day (0-DTE) vs non-expiry-day
  sub-split; FOCUSED_DESK latency sensitivity; per-leg attribution;
  fill/no-fill rates.
- **Data:** `dhan_rolling_1m` tidy parquet (census vs bhavcopy required
  green before the run), `participant_oi`, `fo_bhavcopy`; cost model as of
  commit d1eb447.

## Data used

- `dhan_rolling_1m` tidy parquet, 11,704,398 rows, 2023-07-01 → 2026-07-06;
  census GREEN 2026-07-09 (docs/DATA_CENSUS.md): premium levels reconcile to
  bhavcopy's official close at 98.10% within max(3%, ₹1), median 0.33%.
  Candle OI is AMBER in that census and is NOT consumed here.
- `participant_oi` via `alpha.study.h001r.client_write_intensity` (PIT,
  merge_asof on available_at, same-day trap armed and silent).
- `fo_bhavcopy` for per-date lot + front-week expiry.
- Cost model `ZERODHA_NSE_OPTIONS_2026_07`; latency `OWNER_2026_07`
  LogNormal(μ=4.55, σ=0.90)s, NO-FILL >900 s.
- Results JSON: ledger/results/h001b_20260709.json.

## Results

n = 248 gradeable ticket-days (2024-07-12 → 2026-01-07); books 173 top / 75
bottom — asymmetric because wi TRENDED UP across the sample, so the trailing
cut was persistently exceeded; that is what a PIT-honest rolling cut does
with a trending signal (a balanced-looking full-sample tercile would have
leaked). Dropped: 2024-11-01 (Muhurat evening session — all draws truncated,
disclosed). Fill rate 99.4%, no-fill 0.6% (latency censoring), truncated
draws 0.03%.

| gate | result | detail |
|---|---|---|
| 1 primary EV CI | **FAIL** | mean net **−₹804**/ticket, 90% MBB CI [−1349, −395] |
| 2 stress 0.50% | **FAIL** | −₹879 |
| 3 conditioning diff | **PASS** | top − bottom **+₹1,603**, CI [+805, +2270] |
| 4 BH p | PASS | p=0.00050 ≤ 0.01429 |
| 5 split-half sign | PASS | −403 / −1200 (both negative) |

Attribution (₹/ticket, identity exact per filled draw):
gross move ex-friction **−47** (trendiness nearly pays the theta),
latency **+4** (irrelevant near the open), adverse fills **−560** (the
killer — every 09:16–09:30 entry pays the arrival bar's HIGH by the frozen
insufficient-history rule, and mornings genuinely are the wide regime),
half-spread **−75**, statutory **−130**.

Secondary (reported, NOT gated): expiry-day tickets **+₹924** (n=25) vs
non-expiry **−₹1,096**; FOCUSED_DESK sensitivity −₹894 (faster hands do not
save it); per-leg CE −118 / PE −560; bottom book **−₹2,407**.

## Verdict & rationale

**INVERTED.** The claim "long the front-week ATM straddle at the open on
heavy-writing days earns positive net EV" is rejected with confidence — the
effect is significantly the OPPOSITE sign. But this is the most informative
kill possible: **the conditioning gate passed** (+₹1,603 differential,
CI excludes zero). H001r's signal is real and visible in premium space —
heavy-writing days lose ₹1,600 LESS than light-writing days. The EXPRESSION
is what dies: an open-to-15:20 ATM straddle carries a ~₹2,400 baseline tax
(bottom book) that conditioning only halves.

What ate the edge, per the pre-registered attribution: **adverse fills
(−560)** dominate — the volatile-open entry rule — then statutory (−130),
spread (−75), theta-net-of-trendiness (−47). Latency was NOT the problem
(+4): the owner's 30 s–15 min hands are fine when the intent is at a fixed
bar.

Per the pre-reg NO-GO clause, this attribution is the design input for the
successor. Two pre-registerable directions it points at (each needs its own
entry — no silent sign-flips, no post-hoc expiry cherry-pick):
1. **H-002 intraday trigger**: enter after bar 30 in a CALM bar (the
   adverse-fill rule then prices fills at the close, killing the −560), on
   the same conditioning.
2. **Expiry-day-only expression**: the +₹924 × 25-day secondary is a
   hypothesis GENERATOR (n too thin to be evidence), consistent with
   0-DTE gamma paying trendiness fastest.
Holdout 2026-01-09 → 2026-07-06 remains locked and untouched.
