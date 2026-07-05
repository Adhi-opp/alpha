# Candidate inefficiency menu — ranked

Ranked for **our** situation: ₹40k, options buyer, overnight/intraday
horizons, free data, manual execution. Each is audited on five axes:
**Data** (available to us specifically), **Cost** (does the plausible edge
exceed round-trip costs at our size?), **Capacity** (fine for all of these at
retail size — noted only where it isn't), **Decay** (how fast it erodes if
real), **Testability** (sample size, confound risk).

A structural note that shapes the whole menu: long premium is negative-EV on
the average day. For a buyer, *knowing when not to buy* is worth as much as
knowing when to buy — several entries below are no-trade filters, and that is
not a consolation prize.

## Live-feasible book (long premium / defined-risk)

**1. H-001 — Retail-writing-heavy days → trendier next session (owned, confirmed)**
Seed edge from the GammaLeak-era pre-registered study: heavier retail index-
option writing in the evening participant-wise OI file → measurably trendier
next session (tercile trendiness diff −0.073, 90% block-bootstrap CI
[−0.113, −0.032], robust to realized-vol partial, stable across halves,
738 days). Mechanism: unhedged retail writers capitulate into moves.
Trendier sessions are exactly when long premium outperforms — the edge is
buyer-shaped. Data: owned, updates nightly, honest T−1 conditioning.
Cost: **unproven** — the study measured the underlying, not option P&L; theta
+ spreads + STT may eat it. First studies: H-001r (re-validate under our
grader), H-001b (option-premium expression: ATM straddle or triggered
directional, overnight→next close). Decay: slow (structural retail
behavior). Testability: high.

**2. H-002 — Intraday trend entry gated by H-001's condition**
Same conditioning, expressed the way you already trade: on retail-heavy-
writing days only, buy premium on an intraday trend trigger (e.g. opening-
range break) instead of at the open. Fewer theta hours, entry confirmation,
matches manual execution. Data: 1-min candles from Upstox + participant OI.
Cost: tighter (intraday round trip) but shorter holding. Testability: high,
but trigger parameters must be pre-registered to avoid mining. Decay: slow.

**3. H-003 — "Premium too cheap" timing filter (buyer-side IV−RV)**
Classic IV−RV harvesting is a seller's edge (shadow book). The buyer-side
inversion: identify regimes where IV underprices forthcoming RV (compression
before regime breaks, post-crush underpricing after events) and only then
allow premium buys. Likely lands as a gate on H-001/H-002 rather than a
standalone strategy. Data: IV from option-chain closes / Upstox greeks, RV
from candles; India VIX as cross-check. Testability: medium (regime
definitions invite mining — pre-register hard). Decay: medium.

**4. H-004 — Expiry-day (Tuesday) pinning: primarily a no-trade filter**
If pinning is real, expiry-day directional premium buys are structurally
poisoned (max gamma against you, premium evaporating). Study A: quantify
pin behavior → no-buy rule on expiry days. Study B (secondary): late-day
cheap gamma when a pin *breaks*. Data: bhavcopy + 1-min candles; expiry
dates derived from data. Cost: expiry-day premiums are tiny so costs are
proportionally huge — B may not survive. Testability: high (weekly samples).

**5. H-005 — Post-event continuation (RBI, CPI, budget, overnight Fed)**
Pre-event buying is usually negative-EV (IV already bid). The testable buyer
edge is post-event: after the binary resolves and IV crushes, does the
first-move direction continue enough to pay for now-cheaper premium?
Data: hand event calendar + candles. Testability: **low-medium — few events,
wide CIs**; needs years of history and modest claims. Decay: medium.

**6. H-006 — Overnight global handoff → open conditioning**
US close, USDINR, Brent, Asia session → gap direction/size and first-hour
behavior. GIFT NIFTY itself is hard to source freely (verify before
promising it as an input); proxies above are yfinance-easy. Buyer
expression: at-open directional premium on strong-handoff days, possibly
interacting with H-001. Testability: high. Decay: medium-fast (crowded
family — expect NO-GO and let the ledger say so).

**7. H-007 — Futures basis impulse**
Sharp swings in NIFTY futures premium/discount as a positioning-pressure
signal for next-session direction. Data: futures + index closes from
bhavcopy (basis needs no paid feed). Expression via options. Testability:
high. Prior related evidence weak — FII-flow drift died to a prior-day-return
partial in the GammaLeak era; pre-register the same confound control.

**8. H-008 — Weekend/expiry-cycle theta seasonality**
With Tuesday expiry, the weekend sits mid-cycle: is weekend risk correctly
priced into Friday premiums? Also day-of-week gamma-payoff patterns
(realized move vs decay paid, per weekday). Data: easy. Testability: high
sample but **severe multiple-testing risk** (day-of-week mining) — one
pre-registered contrast only, not a scan. Likely outcome: a hold/avoid rule.

**9. H-009 — India VIX regime transitions**
Low-VIX complacency breaks / VIX term shifts as a gate for when long gamma
gets paid. Overlaps H-003; run only if H-003 leaves unexplained variance.
Data: NSE VIX history. Testability: medium (regimes are few and long).

**10. H-010 — USDINR / crude shock propagation**
Large FX/crude moves → next-day index vol and direction. Data: yfinance.
Testability: high. Prior: the GammaLeak-era macro-regime work was
suggestive, never pre-registered — treat as fresh. Decay: medium.

**11. H-011 — Post-earnings drift on index heavyweights (cash/ETF expression)**
Drift after heavyweight earnings, expressed in tiny cash size (stock options
spreads are brutal at our size). Slow, cheap to hold, diversifying horizon —
but conflicts with the never-held->1-session comfort, so it earns live
capital only if the owner decides to extend horizon. Park until Phase 4+.

## Shadow book (margin-infeasible at ₹40k — studied and paper-traded only)

**S-001 — Short premium on light-retail-writing days** (inverse of H-001:
quiet, range-bound sessions favor sellers). **S-002 — Systematic IV−RV
harvesting with defined-risk wings.** **S-003 — Expiry-day premium selling.**
These are the highest-prior edges in the Indian market and the reason the
"prove it first" capital plan matters: a proven paper track here is the
argument for more capital later. They go through the identical ledger
process; they just can't touch money yet.

## Already-dead (imported into the ledger as NO-GO — raises the family bar)

FII net flow → next-day drift (killed by prior-day-return partial
correlation, GammaLeak era) plus three other GammaLeak-era rejections to be
backfilled into `ledger/` from the original study docs. Dead ideas are
paid-for knowledge; they stay visible.

## Sequencing

Phase 3 runs H-001r → H-001b. H-002 follows only if H-001b survives costs
(they share a conditioning variable; if the overnight expression dies on
theta, the intraday expression is the pre-registered fallback, stated now so
it isn't a post-hoc pivot). One, at most two, studies in flight at a time.
