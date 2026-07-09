# G005 — DRIFT alignment factor (imported, GammaLeak era)

- **Status:** NO-GO — **INVERTED, in fact** (identity as the 4th rejection:
  best-supported reconstruction; owner to confirm — see note)
- **Registered:** GammaLeak era (conviction factor graded by the calibration
  loop; verdict recorded `core/config.py:553` and NOTES.md:36 "DRIFT zeroed")
- **Family index:** imported 5 of 5

## Hypothesis

Short-horizon (5-min) price drift aligned with a fade setup improves the
setup's hit rate ("DRIFT" conviction factor).

## Verdict & what it bought us

**Measured −37pp lift: 7% hit when the factor was present vs 44% absent
(n=14/122). Weight zeroed.** Not merely useless — anti-predictive as
specified, i.e. effectively INVERTED: drift pointing "the fade's way" marked
moments where fades failed. A textbook case of a hand-crafted factor that
sounded causal and graded terribly.

## Note on identity (owner, one glance)

The kickoff counted "5 studies: 1 confirmed, 4 rejected." Three rejections
are unambiguous in the record ([[G002]] gamma-sign primary, [[G003]] FII
flow, [[G004]] toxicity). DRIFT is the best-supported fourth from the repo
record (only graded-and-killed hypothesis with a recorded magnitude). If the
actual fourth pre-registered study was something else, correct THIS file and
the family count stays 5 either way — the Benjamini–Hochberg denominator is
unaffected.
