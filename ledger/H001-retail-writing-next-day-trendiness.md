# H001 — Retail index-option writing intensity → next-session trendiness

- **Status:** GO (imported, external) — **pending re-validation as H-001r
  under this project's grader before anything is built on it**
- **Registered:** GammaLeak era (pre-registered there; import date 2026-07-05)
- **Family index:** 1 of 5 imported (1 GO, 4 NO-GO)

## Hypothesis

Sessions following days of heavier-than-usual retail ("Client") index-option
writing are trendier, because unhedged retail writers capitulate into
adverse moves, feeding the move. (Structural fact, verified against data,
not lore: Indian retail is net SHORT index options ~95% of days — the SPX
"retail buys options" intuition is inverted here.)

## Imported result

- Conditioning: NSE participant-wise OI file (published every evening →
  honest T−1 conditioning), 3-year daily dataset, 738 days (owned).
- Primary outcome: tercile difference in next-session trendiness =
  **−0.073**, 90% block-bootstrap CI **[−0.113, −0.032]**.
- Confound controls: robust to realized-vol partial; stable across halves.
- Reference code/data: `d:\GammaLeak\positioning\participant.py` (+
  `backfill.py`) for the dataset; original study code to be located and
  cited exactly during import (READ-ONLY — copy, never modify).

## Successor studies (to be registered as separate entries when Phase 2 is ready)

- **H-001r** — re-validation: same hypothesis, re-run end-to-end under this
  project's data layer, PIT accessor, and labeler, extended with data since
  the original study. Guards against pipeline-specific artifacts.
- **H-001b** — the tradeable question: does a long-premium expression
  (ATM straddle or triggered directional, entry near open, exit by close)
  survive theta, spreads, STT, and manual-execution delay at simulated
  fills? A GO here, not H-001r, is what earns a paper-track slot.
- **H-002** — pre-registered fallback if H-001b dies on theta: intraday
  trigger entry on the same conditioning (declared now, so it is not a
  post-hoc pivot).

## Verdict & rationale

Imported GO. The underlying effect is our best-evidenced asset; the
tradeable expression is unproven. Nothing trades until H-001b earns it.
