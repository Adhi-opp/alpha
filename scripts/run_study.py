r"""Study runner — the pre-registration gate made executable.

Freezes the study's ledger pre-registration on first run (idempotent), then
REFUSES to compute anything if the frozen section has been edited since
(prereg.assert_frozen). Results go to ledger/results/<study>_<date>.json and
stdout; the ledger's Results/Verdict sections are updated from that output,
never invented.

  d:\alpha\.venv\Scripts\python scripts\run_study.py --study h001r
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha.config import PROJECT_ROOT
from alpha.study import prereg

STUDIES = {
    "h001r": {
        "ledger": PROJECT_ROOT / "ledger" / "H001r-retail-writing-trendiness-revalidation.md",
        "run": lambda: __import__("alpha.study.h001r", fromlist=["run"]).run(),
    },
    "h001b": {
        "ledger": PROJECT_ROOT / "ledger" / "H001b-long-premium-expression.md",
        "run": lambda: __import__("alpha.study.h001b", fromlist=["run"]).run(),
    },
    "h002": {
        "ledger": PROJECT_ROOT / "ledger" / "H002-intraday-calm-entry.md",
        "run": lambda: __import__("alpha.study.h002", fromlist=["run"]).run(),
    },
    "h003": {
        "ledger": PROJECT_ROOT / "ledger" / "H003-expiry-scalp-environment.md",
        "run": lambda: __import__("alpha.study.h003", fromlist=["run"]).run(),
    },
}

_TOP_KEYS = ("study", "n_days", "sample", "gates", "verdict")


def _print_result(result: dict) -> None:
    """Study-agnostic report: header, every metric, gates, verdict."""
    print(f"study    : {result['study']}   n={result['n_days']} days "
          f"({result['sample'][0]} .. {result['sample'][1]})")
    for k, v in result.items():
        if k in _TOP_KEYS:
            continue
        print(f"{k:<24}: {json.dumps(v, default=str)}")
    print("gates    :")
    for g in result["gates"]:
        print(f"  [{'PASS' if g['passed'] else 'FAIL'}] {g['name']:<18} {g['detail']}")
    print(f"\nVERDICT  : {result['verdict']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--study", required=True, choices=sorted(STUDIES))
    args = ap.parse_args()
    spec = STUDIES[args.study]

    record = prereg.freeze(spec["ledger"])          # idempotent if unchanged
    prereg.assert_frozen(spec["ledger"])            # tamper check
    print(f"pre-registration frozen: {record['hash'][:16]}…  "
          f"({record['frozen_at_utc']})\n")

    result = spec["run"]()

    out_dir = PROJECT_ROOT / "ledger" / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{args.study}_{date.today():%Y%m%d}.json"
    out.write_text(json.dumps(result, indent=2))

    _print_result(result)
    print(f"results  -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
