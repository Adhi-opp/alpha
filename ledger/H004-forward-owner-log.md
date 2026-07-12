# H004 — Forward owner log: does the emitted verdict price the owner's REAL scalp P&L?

- **Status:** PRE-REGISTERED (accruing; single evaluation at 40 forward
  sessions — the evaluator structurally refuses to run before that)
- **Registered:** 2026-07-12 (frozen b2b93d982f858bc5, before the first
  rated forward session, Tue 2026-07-14)
- **Family index:** 10

## Hypothesis

[[H003]] validated the SIGNAL (heavy retail writing → richer hurdle-adjusted
scalp energy on NIFTY expiry days) and licensed a pre-open console verdict.
What remains untested is the only claim that matters: the JOINT system —
emitted verdict + the owner's manual discretionary scalping — makes real
money in the direction the verdict points. No backtest can test this (his
sub-minute round trips are unsimulatable; H003 design notes), so the
instrument is a forward log: every NIFTY expiry session gets a pre-open
rating, the owner trades exactly as he always does, and his realized P&L is
graded against the rating after 40 sessions. On the seeded retro sample
(n=6, contaminated, excluded below) the ratings and his P&L DISAGREE — this
registration exists so that question is settled by a frozen bar, not by
narrative.

## Pre-registration (FROZEN before any forward session is rated)

- **Sample:** every NSE NIFTY front-week expiry session (bhavcopy calendar,
  `trade_date == front-week expiry`) with trade_date ≥ **2026-07-14**, in
  sequence, until the count reaches **40**. A session enters the sample only
  if its rating was computable pre-open: most recent strictly-prior
  participant-OI file has trade_date within **4 calendar days** before the
  session (the console's stale guard) and wi history ≥ 20 files. Sessions
  unrated because the fetch was dead are excluded AND disclosed. The six
  retro-seeded sessions (2026-07-01 → 2026-07-10) are EXCLUDED from the
  primary: rated retroactively, results already seen before this freeze.
- **X (rating):** wi_pctile_252 — percentile of the most recent
  strictly-prior wi within its trailing 252 files, exactly the
  `owner_log.session_ratings` / console `scalp_environment` formula.
  CONTINUOUS. The FAVORABLE/UNFAVORABLE display tiers are presentation, not
  the test.
- **Y (outcome):** realized day net P&L (₹) of the owner's NSE NIFTY-option
  trades that session, from the Zerodha contract note, journaled under the
  existing reconciliation bands (gross − net implies charges in
  (0, ₹2,000)). A sampled session with no journal row = **abstained, Y = 0**
  — abstention is an outcome, graded, per the constitution. If a note mixes
  non-NIFTY-option NSE activity, the NIFTY-option subset gross minus
  cost-model statutory charges is used and disclosed.
- **Evidence integrity:** traded sessions must be journaled from contract
  notes with annexure timestamps (MAE is computed from our own 1-min data at
  those timestamps, never hand-entered). At evaluation the owner supplies
  the broker P&L statement covering the window; any unjournaled NIFTY-option
  activity on a sampled session **voids the log → NO-GO**.
- **Statistics:** Spearman(X, Y) over the session sequence — raw, not
  partial: this is a performance audit of the instrument as emitted, not a
  mechanism claim (H003 owns the mechanism). Moving-block bootstrap over row
  indices, **block 5** sessions (weekly-expiry sequence ⇒ ≈ 5+ weeks of
  calendar per block; block-10 sensitivity reported, not gated), **4,000
  resamples, seed 53**, 90% percentile CI, two-sided bootstrap p. Ties in Y
  (abstention zeros) take midranks.
- **Single look:** the statistic is computed exactly once, at the first date
  the sample reaches 40. `alpha/study/h004.py` refuses to run below 40
  (structural guard); interim owner-log reports show per-session rows,
  counts, MAE and discipline flags — never the association statistic.
  **Hard deadline 2027-12-31:** fewer than 40 rated sessions by then =
  NO-GO. Keeping the daily fetch alive and the journal current is part of
  the system under test.
- **PROMOTED requires ALL of:**
  1. ρ > 0 with 90% MBB CI excluding 0;
  2. two-sided bootstrap p ≤ **0.0100** (BH q=0.10, family m=10);
  3. **discipline sign-integrity:** with every discipline-flagged trade's
     gross P&L removed from its session's Y (flag = MAE ≤ −30% of entry
     premium while held, computed from our 1-min data), the recomputed ρ is
     not opposite-signed — a promotion may not be carried by undisciplined
     holds that got lucky;
  4. **risk:** no sampled session's realized day net loss exceeds **₹6,000**
     (the owner's own kill-switch). One breach = the joint system violated
     its constitution → NO-GO regardless of association;
  5. **H003 holdout replication**, run at the same evaluation date and never
     before (the evaluator sequences it after the n≥40 guard): the frozen
     H003 estimator on the locked holdout expiry sessions
     (2026-01-09 → 2026-07-06) yields a same-signed partial Spearman, AND on
     the combined dev+holdout sample the 90% MBB CI excludes 0 with
     p ≤ 0.0100.
- **NO-GO consequence:** the console verdict is retired and H003 marked
  STALE; the H001 conditioning branch is exhausted at buyer-expressible
  level → next family from docs/CANDIDATES.md.
- **What PROMOTED licenses:** the verdict graduates from licensed experiment
  to validated instrument — console keeps emitting, the owner keeps
  executing manually (automation is constitutionally excluded). It does NOT
  license sizing rules, leverage changes, or any EV forecast; capital stays
  ₹40k under the kill-switch.
- **Secondary (reported, NOT gated):** traded-only-subset Spearman;
  abstention rate above/below median rating; descriptive tier means of Y;
  discipline-flag rate by tier; block-10 CI sensitivity; distribution of
  day-loss vs the kill-switch; SENSEX/observational session summary
  alongside; the retro-seed n=6 shown separately for contrast, never pooled.
- **Data:** `participant_oi` + `fo_bhavcopy` (ratings, expiry calendar),
  `journal/*.csv` (committed evidence), `dhan_rolling_1m` (+ `_sensex`,
  observational) for MAE only. No execution simulator, no cost model in the
  primary.

## Design notes

- **Raw Spearman, not partial:** H003 needed prev-day controls to show the
  signal wasn't a volatility proxy. Here the question is operational — does
  the number the console actually shows predict the money he actually makes.
  Whatever the rating routes through is irrelevant to that audit.
- **Y in rupees, not per-lot or per-turnover:** his sizing may respond to
  the verdict. That response is part of the joint system being validated;
  normalizing it away would grade a system nobody runs.
- **Abstention at 0, all rated sessions in-sample:** including untraded
  sessions kills the selection problem (only-trades-favorable would
  otherwise restrict range); zeros from unrelated absences dilute power but
  do not bias sign.
- **Power, disclosed pre-hoc:** at n=40 with this bar (CI > 0 AND p ≤ 0.01
  two-sided), only |ρ| ≳ 0.4 passes reliably. A weak joint edge dies here
  BY DESIGN — ₹40k of capital cannot fund the deployment of a weak edge,
  and the constitution says most ideas should die.
- **The feedback loop is accepted, not controlled away:** the owner sees the
  verdict before trading. Behavior change is the product; a test that
  blinded him would validate a system nobody uses.
- **Retro-seed exclusion is mandatory, not optional:** those six sessions
  were rated after their outcomes were known and publicly discussed (the
  n=6 disagreement). Any pooling would let a seen result leak into a
  forward test.

## Results

(single evaluation at 40 sessions — nothing may appear here before then)

## Verdict & rationale

(pending)
