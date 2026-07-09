# Data census — free layer (Phase 0 closeout)

Run after the 2023–2026 backfill, 2026-07-08. Reproduce any time with the
snippet in NEXT_STEPS.md §1. This is the "quantify gaps before trusting the
data" gate — it passed.

## Coverage

| dataset        | days | span                    | rows       |
|----------------|------|-------------------------|------------|
| fo_bhavcopy    | 740  | 2023-07-03 .. 2026-07-06 | 30,747,891 |
| participant_oi | 740  | 2023-07-03 .. 2026-07-06 | 3,700      |

**Participant-OI gaps vs bhavcopy trading days: 0.** Both datasets align on
all 740 sessions — clean T−1 conditioning is available for the whole period.
(`not-published` file-attempts during backfill were NSE holidays, correctly
skipped, not gaps.)

## NIFTY weekly-expiry weekday — the anti-lore check

Derived from expiries actually traded in the bhavcopy, never a weekday rule.
The dominant weekday **changed mid-sample**:

- 2023-Q3 → 2025-Q2: **Thursday** (11–13 expiries/quarter).
- 2025-Q3: transition quarter (Thursday and Tuesday both present).
- 2025-Q4 onward: **Tuesday** dominant.
- Scattered Monday/Wednesday expiries are holiday shifts (expiry pulled a day
  when the normal day is an NSE holiday).
- Far-future rows (2027+) are thinly-traded monthly/quarterly long-dated
  contracts, not weeklies.

This is the exact failure the sibling project hit: a hardcoded Thursday would
mislabel every trade after ~Sep 2025; a hardcoded Tuesday would mislabel
everything before. `alpha/data/calendars.py` reads the expiry from the data,
so studies spanning the switch stay correct. Any code that assumes an expiry
weekday must first call `expiry_weekday_counts()` and see this mix.

## Measured facts logged en route

- NIFTY lot size read from the file (currently 65), never assumed constant.
- NSE's participant-OI TOTAL row is internally off by ±1 on some columns;
  the integrity guard tolerates |diff| ≤ 2 as a known exchange quirk and
  flags anything larger as ERROR.

---

# Data census — Dhan rolling 1-min options (2026-07-09)

The H001b pre-registration requires this census green before the study runs.
Pull: 1,554 rollingoption calls, **zero empty responses**; tidy re-key by
(ts, strike, side) → `derived/dhan_rolling_1m/`, **11,704,398 rows**,
2023-07-01 .. 2026-07-06. Reproduce: `scripts/census_rolling.py`.

**Verdict: GREEN for premium paths + spot (what studies consume). Candle OI
is AMBER — certified for nothing, see below.**

| check | result | detail |
|---|---|---|
| A sessions | PASS | all 740 bhavcopy sessions present; 6 tidy-only days are NSE **special sessions** our bhavcopy layer deliberately skips (Muhurat 2023-11-12/2024-11-01, Budget Saturday 2025-02-01, DR-drill Saturdays) — they carry no T−1 conditioning and are never decision days |
| B bars/session | PASS | median 375 (09:15–15:29), P1 = 375; min 60 = Muhurat evening session 2024-11-01 |
| C strike grid | PASS | modal step 50, 175 strikes, 8,950–26,850 |
| D exit coverage | PASS | ATM-at-open strike has both legs in the 15:21–15:29 window on 99.60% of sessions; the 3 gaps include **2024-06-04 (election)** — spot moved >10 strikes so the morning ATM left the ±10 fan: exactly the truncation case the study must disclose, not silently fill |
| E close | PASS | Dhan last-30-min volume-weighted close vs bhav close: **98.10% within max(3%, ₹1), median rel diff 0.33%** over 32,320 series-days |
| E OI | AMBER | intraday 15:29 snapshot vs post-clearing EOD: median rel 2.4%, 27% of rows >5% off, **97% one-directional (Dhan > bhav)**, worst on expiry day (unwind). Not a corruption — a definitional gap with no like-for-like transform. **Any future study consuming candle OI must add its own OI gate first.** |
| F iv | INFO | 1.0M rows with iv=0 (half on expiry sessions — the dying contract's final candles; the rest largely deep wings). Studies must treat iv=0 as missing, never as a real 0% vol |

### The close-definition lesson (recorded so it is never re-learned)

The first census run compared Dhan's 15:29 **LTP** to bhavcopy close and
failed spectacularly (median 4.3%, P95 67%). Diagnosis: NSE's official option
close is the **last-half-hour weighted-average premium** (also the daily
settlement basis), not the final trade. Verified on the worst case
(2025-06-05 expiry-pin ATM PE: LTP 0.05 vs bhav 7.60 — Dhan's own 30-min
volume-weighted mean = 7.95). The corrected, like-for-like comparison passes
at 98.1%. Implication for consumers: **bhavcopy option closes are smoothed;
intraday fill simulation must use the candle series** (which is LTP-native),
and anything reconciling to bhavcopy must reconcile to the half-hour average.
