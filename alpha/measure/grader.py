"""Counterfactual grader — the capstone of the measurement layer.

Composes the three primitives into the one number every study reports:
cost-adjusted net P&L of a long-premium ticket, at tradeable fills.

  signal --FillModel--> entry fill (delay + ask)     [execution.py]
         --triple_barrier--> exit at a mid barrier    [labeler.py]
         --exit at bid, then subtract charges          [costs.py]

Two rules this enforces that the sibling project learned the hard way:

- Grade at fills, never at signals. Entry is the ask `delay_bars` after the
  signal; exit crosses the spread again to the bid; brokerage/STT/etc. come
  from the cost model fitted to a real contract note. The spread is crossed
  twice and the statutory charges are separate from it — both are real.

- Grade abstentions counterfactually. `acted=False` tickets are graded
  identically so the P&L of trades we DIDN'T take is measured. A feedback
  loop that only sees taken trades learns on survivors (censoring bias).
  `acted` is recorded; aggregation decides how to use it — the grader never
  drops an abstention.

`truncated` labels (data gap) and `no_fill` (signal too close to the close)
are marked `gradeable=False`: recorded, never scored as a flat outcome.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from alpha.measure.costs import OptionCostModel
from alpha.measure.execution import FillModel
from alpha.measure.labeler import TRUNCATED, Barriers, Label, triple_barrier

NO_FILL = "no_fill"


@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    signal_time: pd.Timestamp
    qty: int
    target_ret: float     # magnitude, fraction of entry fill price
    stop_ret: float
    max_bars: int
    acted: bool = True     # False = abstention, graded counterfactually


@dataclass(frozen=True)
class GradedTicket:
    ticket_id: str
    acted: bool
    outcome: str           # target | stop | time | truncated | no_fill
    qty: int
    entry_price: float     # ask actually paid, or nan
    exit_price: float      # bid actually received, or nan
    gross_pnl: float       # rupees, premium P&L at fills (spread included)
    costs: float           # rupees, statutory + brokerage charges
    net_pnl: float         # gross - costs
    mae: float
    mfe: float
    ambiguous: bool
    spread_estimated: bool
    gradeable: bool

    @property
    def is_win(self) -> bool:
        return self.gradeable and self.net_pnl > 0


def grade_ticket(
    ticket: Ticket,
    premium_path: pd.DataFrame,
    fill_model: FillModel,
    cost_model: OptionCostModel,
    half_spread_frac: float | None = None,
) -> GradedTicket:
    """Grade one long-premium ticket end to end.

    premium_path: the OPTION premium path from the signal bar onward
      (row 0 = signal bar), columns {timestamp, high, low, close}. Mid prices.
    """
    def _degenerate(outcome: str) -> GradedTicket:
        return GradedTicket(
            ticket_id=ticket.ticket_id, acted=ticket.acted, outcome=outcome,
            qty=ticket.qty, entry_price=float("nan"), exit_price=float("nan"),
            gross_pnl=float("nan"), costs=float("nan"), net_pnl=float("nan"),
            mae=float("nan"), mfe=float("nan"), ambiguous=False,
            spread_estimated=not fill_model.spread_is_measured, gradeable=False,
        )

    entry = fill_model.fill("B", premium_path, half_spread_frac)
    if entry is None:
        return _degenerate(NO_FILL)

    # Bars strictly after the entry fill drive the barrier search. Barriers are
    # measured from the ACTUAL entry (the ask), not the signal price.
    post = premium_path[premium_path["timestamp"] > entry.fill_time].reset_index(drop=True)
    barriers = Barriers.from_returns(
        entry=entry.fill_price, direction=1,
        target_ret=ticket.target_ret, stop_ret=ticket.stop_ret,
        max_bars=ticket.max_bars,
    )
    label: Label = triple_barrier(post, entry.fill_price, barriers, direction=1,
                                  entry_time=entry.fill_time)

    if label.outcome == TRUNCATED:
        g = _degenerate(TRUNCATED)
        return GradedTicket(**{**g.__dict__, "mae": label.mae, "mfe": label.mfe})

    # Exit: the barrier level is a mid; a seller receives the bid.
    hs = half_spread_frac if half_spread_frac is not None else fill_model.default_half_spread_frac
    exit_receive = label.exit_price * (1 - hs)

    gross = (exit_receive - entry.fill_price) * ticket.qty
    costs = cost_model.round_trip_cost(
        buy_turnover=entry.fill_price * ticket.qty,
        sell_turnover=exit_receive * ticket.qty,
    )
    return GradedTicket(
        ticket_id=ticket.ticket_id, acted=ticket.acted, outcome=label.outcome,
        qty=ticket.qty, entry_price=entry.fill_price, exit_price=exit_receive,
        gross_pnl=gross, costs=costs, net_pnl=gross - costs,
        mae=label.mae, mfe=label.mfe, ambiguous=label.ambiguous,
        spread_estimated=entry.spread_estimated, gradeable=True,
    )


def summarize(graded: list[GradedTicket]) -> dict:
    """Aggregate gradeable tickets. Abstentions and taken trades reported apart
    so censoring is visible, not hidden.
    """
    gradeable = [g for g in graded if g.gradeable]
    taken = [g for g in gradeable if g.acted]
    abstained = [g for g in gradeable if not g.acted]

    def _stats(rows: list[GradedTicket]) -> dict:
        if not rows:
            return {"n": 0}
        nets = [g.net_pnl for g in rows]
        return {
            "n": len(rows),
            "net_pnl_total": sum(nets),
            "net_pnl_mean": sum(nets) / len(nets),
            "win_rate": sum(g.is_win for g in rows) / len(rows),
            "ambiguous_frac": sum(g.ambiguous for g in rows) / len(rows),
        }

    return {
        "taken": _stats(taken),
        "abstained_counterfactual": _stats(abstained),
        "ungradeable": len(graded) - len(gradeable),
        "spread_estimated": any(g.spread_estimated for g in gradeable),
    }
