# Hypothesis ledger

Every idea gets a file here — `H###-short-slug.md` (live-feasible) or
`S###-short-slug.md` (shadow book) — created from `TEMPLATE.md` **before any
result is seen**. Dead ideas are never deleted: they are paid-for knowledge
and they raise the multiple-testing bar honestly.

## Lifecycle

`DRAFT` → `PRE-REGISTERED` (pre-reg section complete and frozen; the study
runner hashes it) → `RUNNING` → verdict:

- `GO` — passed its own pre-registered criteria AND survives
  Benjamini–Hochberg across the whole ledger family AND replicates on the
  locked holdout. Eligible for the paper track.
- `NO-GO` — failed. Record what killed it (often more valuable than a GO).
- `INVERTED` — effect real but opposite-signed; a new pre-registration is
  required to pursue the inversion (no silent sign-flips).
- `STALE` — was GO, later failed live/paper monitoring or decayed.

## Family accounting

The multiple-testing family = every entry ever registered here, including
imported history. Current family count: **5 imported** (GammaLeak era:
1 GO — H-001; 4 NO-GO) + entries in this directory. The 4 imported
rejections need backfilling from the original GammaLeak study docs — one is
FII flow → next-day drift (`d:\GammaLeak\research\study_fii_flow_drift.py`);
the other three: **TODO(owner): list them so the family count is exact.**

## Rules

- No result may be computed before the pre-reg section is frozen.
- Data access inside studies goes through the PIT accessor only.
- Every reported effect carries a CI (block bootstrap, block ≥ label horizon).
- Confound controls are named in advance (the FII study looked highly
  significant until its pre-registered prior-day-return partial killed it).
- A GO on underlying labels is *not* a GO to trade: the instrument-P&L study
  (with full costs, at fills) is a separate registered entry.
