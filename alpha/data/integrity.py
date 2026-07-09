"""Integrity guards. Red integrity blocks downstream use of the day.

Checks are pure functions DataFrame -> list[Issue]; scripts wire them and
decide exit codes. Severity: ERROR blocks (the grader flags the day), WARN
is logged and reviewed weekly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


@dataclass
class Issue:
    dataset: str
    ref: str  # usually the trade date
    severity: str  # "ERROR" | "WARN"
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.dataset} {self.ref}: {self.message}"


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "ERROR"]


def check_participant_oi_day(df: pd.DataFrame) -> list[Issue]:
    """One trade date of participant OI: category completeness + sum checks."""
    issues: list[Issue] = []
    ref = str(pd.to_datetime(df["trade_date"].iloc[0]).date())
    ds = "participant_oi"

    present = set(df["client_type"])
    for who in ("Client", "DII", "FII", "Pro"):
        if who not in present:
            issues.append(Issue(ds, ref, "ERROR", f"missing category {who}"))
    if "TOTAL" not in present:
        issues.append(Issue(ds, ref, "WARN", "missing TOTAL row, sum check skipped"))
        return issues

    numeric = df.select_dtypes("number").columns
    cats = df[df["client_type"] != "TOTAL"]
    total = df[df["client_type"] == "TOTAL"].iloc[0]
    for col in numeric:
        if (df[col] < 0).any():
            issues.append(Issue(ds, ref, "ERROR", f"negative values in {col}"))
        diff = int(cats[col].sum()) - int(total[col])
        # NSE's own TOTAL row is off by +-1 on some columns (observed on the
        # real 2026-07-06 file: opt_idx_put_long sum 5,647,549 vs TOTAL
        # 5,647,550). Tolerate the exchange's quirk narrowly; flag anything
        # bigger as a real inconsistency.
        if abs(diff) > 2:
            issues.append(Issue(
                ds, ref, "ERROR",
                f"category sum != TOTAL for {col} (off by {diff})",
            ))
        elif diff != 0:
            issues.append(Issue(
                ds, ref, "WARN",
                f"category sum vs TOTAL off by {diff} in {col} (known NSE quirk)",
            ))
    return issues


def check_bhavcopy_day(df: pd.DataFrame) -> list[Issue]:
    """One trade date of FO bhavcopy: shape, key contracts, duplicates."""
    issues: list[Issue] = []
    ref = str(pd.to_datetime(df["trade_date"].iloc[0]).date())
    ds = "fo_bhavcopy"

    n = len(df)
    if n < 1_000:
        issues.append(Issue(ds, ref, "ERROR", f"only {n} rows — truncated file?"))
    elif n < 10_000:
        issues.append(Issue(ds, ref, "WARN", f"only {n} rows — unusually small"))

    nifty_opts = df[(df["symbol"] == "NIFTY") & (df["instrument"] == "IDO")]
    if nifty_opts.empty:
        issues.append(Issue(ds, ref, "ERROR", "no NIFTY index options present"))

    keys = ["trade_date", "symbol", "instrument", "expiry", "strike", "option_type"]
    dups = df.duplicated(subset=keys).sum()
    if dups:
        issues.append(Issue(ds, ref, "ERROR", f"{dups} duplicate contract rows"))

    traded = df[df["volume"] > 0]
    bad_close = traded[~(traded["close"] > 0)]
    if len(bad_close):
        issues.append(Issue(
            ds, ref, "WARN",
            f"{len(bad_close)} traded rows with non-positive close",
        ))
    return issues


def gap_report(
    dataset: str, present: list[date], reference: list[date]
) -> list[Issue]:
    """Dates in `reference` (e.g. bhavcopy trading days) missing from `present`.

    Quantify gaps BEFORE trusting a dataset — this is the check that made
    self-collected tick logs inadmissible in the sibling project.
    """
    missing = sorted(set(reference) - set(present))
    return [Issue(dataset, str(d), "WARN", "missing on a trading day")
            for d in missing]


def staleness(dataset: str, present: list[date], max_age_days: int = 4) -> list[Issue]:
    """WARN if the newest row is older than max_age_days calendar days."""
    if not present:
        return [Issue(dataset, "-", "ERROR", "dataset empty")]
    age = (date.today() - max(present)).days
    if age > max_age_days:
        return [Issue(dataset, str(max(present)), "WARN",
                      f"newest row is {age} days old")]
    return []
