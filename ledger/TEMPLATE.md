# H### — <short name>

- **Status:** DRAFT | PRE-REGISTERED | RUNNING | GO | NO-GO | INVERTED | STALE
- **Registered:** <date>  **Verdict date:** <date>
- **Family index:** <nth hypothesis ever registered, incl. imported>

## Hypothesis

One falsifiable sentence, with the proposed *mechanism* (why should this
exist, who is on the losing side, why don't they stop?).

## Pre-registration (FROZEN before any result is seen — hash: <filled by runner>)

- **Universe & period:** instruments, date range. Locked holdout excluded.
- **Conditioning variables:** exact definitions incl. `available_at` logic
  (what is knowable before the decision moment?).
- **Primary outcome:** one number (e.g. tercile difference in X; cost-adjusted
  ₹/ticket at simulated fills), with the label definition (barriers, horizon).
- **Secondary outcomes:** listed now; anything not listed is exploratory and
  says so in the results.
- **Confound controls:** named partials/regressions run regardless of how
  good the raw effect looks (default set: prior-day return, realized vol,
  trend state, VIX level — extend per hypothesis).
- **GO criteria:** thresholds on the primary outcome + CI, BH-adjusted, plus
  stability check (effect same sign and overlapping CI in both sample halves).
- **NO-GO criteria:** explicit (not just "fails GO").
- **Costs:** which cost model version; cost hurdle in ₹ per round trip.
- **CV / resampling:** purged-embargoed walk-forward params; bootstrap block
  length.

## Data used

Datasets + pipeline versions + integrity report status for the period.

## Results

Filled only after pre-reg freeze. Primary first, with CI. Then secondaries,
then (clearly marked) exploratory observations → which become NEW ledger
entries, never conclusions of this one.

## Verdict & rationale

GO / NO-GO / INVERTED, what specifically decided it, and what was learned
either way. If NO-GO: what would have to be different for a successor
hypothesis to be worth registering.
