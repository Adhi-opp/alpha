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
| [[H001b]] (7) | long front-week ATM straddle on heavy-writing days, full cost | **INVERTED** 2026-07-09 (EV −₹804/ticket, CI [−1349, −395] — yet conditioning differential +₹1,603 CI [+805, +2270] PASSED: the signal is real, the expression loses; adverse fills ate −₹560. Expiry-day secondary +₹924 (n=25) = H-002 design input) |
| [[H002]] (8) | same conditioning, calm-bar intraday entry (adverse-fill fix) | **INVERTED** 2026-07-11 (redesign worked: adverse hit-rate 100%→28.6%, drag −560→−164, loss halved to −₹382 CI [−769, −25]; differential +₹1,486 PASSED again. Structure is the problem: all-day straddle theta ≈ eats the whole edge on non-expiry days. Expiry-day secondary now +₹1,328 — both expressions point at H-003) |
| [[H003]] (9) | heavy writing → richer hurdle-adjusted scalp energy on expiry days | **GO** 2026-07-11 (partial Spearman +0.287, 90% CI [+0.118, +0.501], p=0.0085, halves +0.26/+0.35, n=78; non-expiry contrast −0.14 = expiry-SPECIFIC; expiry energy 2.6× non-expiry. Association only — licenses the day-rating verdict; promotion needs holdout + ≥40-session forward owner log) |
| [[H004]] (10) | forward owner log: emitted verdict prices the owner's REAL scalp P&L (joint system) | **PRE-REGISTERED** 2026-07-12, frozen b2b93d98 BEFORE the first rated session (2026-07-14). Single evaluation at 40 forward NIFTY-expiry sessions (evaluator refuses earlier); Spearman(rating, day net P&L), abstention = 0; gates: CI>0, p ≤ 0.0100 (m=10), discipline sign-integrity, zero ₹6k kill-switch breaches, H003 holdout replication. Deadline 2027-12-31 or NO-GO; NO-GO retires the verdict (H003 → STALE) |

## Rules

- No result may be computed before the pre-reg section is frozen.
- Data access inside studies goes through the PIT accessor only.
- Every reported effect carries a CI (block bootstrap, block ≥ label horizon).
- Confound controls are named in advance (the FII study looked highly
  significant until its pre-registered prior-day-return partial killed it).
- A GO on underlying labels is *not* a GO to trade: the instrument-P&L study
  (with full costs, at fills) is a separate registered entry.
