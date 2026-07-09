# G003 — FII futures flow → next-day NIFTY drift (imported, GammaLeak era)

- **Status:** NO-GO
- **Registered:** 2026-07-05 (GammaLeak `research/study_fii_flow_drift.py`,
  pre-registration in the module docstring — proposal P9)
- **Family index:** imported 3 of 5

## Hypothesis

FII index-futures positioning flow (published evening T−1, honest lag) →
day-T open→close drift.

## Pre-registered design (from the source docstring)

Primary conditioning `fii_flow = fii_fut_net(T−1) − fii_fut_net(T−2)`;
primary outcome open→close log return. Tercile spread with 90% month-block
bootstrap CI, sign-agreement hit rate, Spearman, **momentum-confound
control: partial Spearman given prior-day close→close return**, split-half
stability. GO required surviving the partial.

## Verdict & what it bought us

**NO-GO — the flagship kill.** The raw effect looked highly significant and
died under the pre-registered prior-day-return partial: FII flow was mostly
a re-description of yesterday's move. This is the canonical example of why
confound controls are named BEFORE results are seen. FII flow stayed a
dashboard context number; no prior was wired. Any future FII-flow idea here
must beat this precedent (e.g. via interaction with participant OI), not
re-run it.
