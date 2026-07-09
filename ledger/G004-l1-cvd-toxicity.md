# G004 — L1 CVD flow-toxicity → confirm quality (imported, GammaLeak era)

- **Status:** NO-GO
- **Registered:** GammaLeak era (proposal P1, shadow-conditioning acceptance
  test in `calibrate.py`; failure recorded NOTES.md:26)
- **Family index:** imported 4 of 5

## Hypothesis

Trailing |ΔCVD|/ΔVolume ("flow toxicity", an L1 proxy for informed flow)
conditions confirmation quality: high-toxicity moments should have a
different hit rate than low.

## Design & verdict

Tercile acceptance test on instrumented CONFIRMs, run shadow-first (never
wired to live signals). **NO-GO: terciles came back flat 44/43/43** — the L1
proxy carried no signal. The planned successor (queue imbalance / sweep
detection from real L5 depth once `.depth.csv` accumulates) is a NEW
hypothesis and must register separately if ever pursued here.

Lesson kept: cheap proxies for microstructure quantities measure nothing;
shadow-first meant this cost zero rupees to learn.
