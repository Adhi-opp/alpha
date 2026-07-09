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
