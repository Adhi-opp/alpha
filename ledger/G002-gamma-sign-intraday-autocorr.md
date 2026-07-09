# G002 — Dealer-gamma sign → intraday momentum regime (imported, GammaLeak era)

- **Status:** NO-GO (primary outcome; its SECONDARY spawned [[H001]])
- **Registered:** 2026-07-04 (GammaLeak `research/study_gamma_sign_autocorr.py`,
  pre-registration in the module docstring — "A4 study", proposal P2)
- **Family index:** imported 2 of 5

## Hypothesis

More dealer-short-gamma (from the evening participant-OI file, lagged one
row for publication discipline) → more intraday momentum on day T, measured
as lag-1 autocorrelation of 5-min NIFTY returns.

## Pre-registered design (from the source docstring)

Tercile split of `dealer_short_gamma_score` → mean AC per tercile; Spearman;
month-block bootstrap CI on top-minus-bottom AC difference. GO: difference
> 0 with 90% CI excluding 0. NO-GO: CI straddles 0 or sign inverts.

## Verdict & what it bought us

**NO-GO on the primary** — GammaLeak's Phase C (intraday signed-flow
evolution) was deprioritized "per the pre-registered A4 gate" (NOTES.md:15).
But the pre-registered SECONDARY (day-T trendiness |close−open|/(high−low)
by retail-write intensity) showed the CI-solid effect that became the
confirmed edge — heavier retail writing → trendier next session
(calibrate.py:608 records it as CI-solid over 719 sessions). That finding is
imported as [[H001]] and must be re-validated here as H-001r before use.

Lesson kept: the tradeable finding came out of a rejection's secondary
outcome — pre-registering secondaries is what made it legitimate rather
than post-hoc mining.
