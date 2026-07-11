# Owner journal — the forward log's raw material

This directory is COMMITTED evidence: hand-curated from the owner's real
Zerodha contract notes. It is not refetchable from any exchange, so it
lives in git, not in the (ignored) data tree. `alpha/paper/owner_log.py`
is the only sanctioned reader; it validates every load.

## Files

- `sessions_YYYY-MM.csv` — one row per trading session with any activity:
  `session_date, exchange, note_id, day_net_pnl, n_round_trips,
  trades_transcribed`. `day_net_pnl` is the note's **net
  receivable/payable** (after ALL charges) — the number the account
  actually saw. 2026-07-07's net is derived: the note's summary gross
  (+5,784.50, post-brokerage) minus its non-brokerage charges (616.49,
  from the golden-tested charge lines) = +5,168.01.
- `trades_YYYY-MM.csv` — one row per round trip:
  `session_date, exchange, contract, expiry, qty, entry_time, exit_time,
  entry_wap, exit_wap` (times IST from the note annexure's order
  timestamps; WAPs are the note's raw weighted averages, ex-brokerage).
  2026-07-07 has no annexure in hand → session row only.

## Rules

- Rows come ONLY from contract notes (or, later, the broker's tradebook
  export). No memory, no screenshots, no "roughly".
- Multi-fill orders collapse to one row per round trip; where one contract
  was round-tripped twice (e.g. 2026-07-02 77400PE), each trip is its own
  row — the note summary's merged WAP reconciles against them.
- Validation on every load: per-session Σ(gross) − day_net must be a
  plausible positive charge total; violations refuse the load.
- MAE and the discipline flag are COMPUTED (from our own 1-min premium
  data at the note's timestamps), never hand-entered. They stay null until
  premium data covers the trade (NIFTY: Dhan pull extension past
  2026-07-06; SENSEX: BSE pull).
