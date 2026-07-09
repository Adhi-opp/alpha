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
1 GO — H001; 4 NO-GO), all backfilled 2026-07-09 from the GammaLeak repo
record (study docstrings, NOTES.md, calibrate.py, core/config.py):

| entry | hypothesis | verdict |
|---|---|---|
| [[H001]] | retail write intensity → next-session trendiness | GO (pending H-001r re-validation) |
| [[G002]] | dealer-gamma sign → intraday 5-min autocorrelation | NO-GO (its secondary spawned H001) |
| [[G003]] | FII futures flow → next-day drift | NO-GO (died under prior-day-return partial) |
| [[G004]] | L1 CVD flow-toxicity → confirm quality | NO-GO (terciles flat 44/43/43) |
| [[G005]] | DRIFT alignment factor | NO-GO/INVERTED (−37pp lift, zeroed) — identity as the 4th: owner to confirm |

Registered in THIS project (family continues from 6):

| entry | hypothesis | verdict |
|---|---|---|
| [[H001r]] (6) | re-validation: retail writing → next-session trendiness | **GO** 2026-07-09 (+0.116, CI [+0.067, +0.174], p=0.0005; survives partials; holdout still locked) |

## Rules

- No result may be computed before the pre-reg section is frozen.
- Data access inside studies goes through the PIT accessor only.
- Every reported effect carries a CI (block bootstrap, block ≥ label horizon).
- Confound controls are named in advance (the FII study looked highly
  significant until its pre-registered prior-day-return partial killed it).
- A GO on underlying labels is *not* a GO to trade: the instrument-P&L study
  (with full costs, at fills) is a separate registered entry.
