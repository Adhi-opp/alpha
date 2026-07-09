import pytest

from alpha.study import prereg

LEDGER = """# H999 — test hypothesis

- **Status:** DRAFT

## Hypothesis

Something falsifiable.

## Pre-registration

- **Primary outcome:** tercile difference in trendiness.
- **GO criteria:** effect < -0.05 with 90% CI excluding 0.

## Results

(filled later)
"""


def _write(tmp_path, text=LEDGER):
    p = tmp_path / "H999-test.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_assert_frozen_refuses_before_freeze(tmp_path):
    p = _write(tmp_path)
    with pytest.raises(prereg.PreRegError, match="not pre-registered"):
        prereg.assert_frozen(p)


def test_freeze_then_assert_passes(tmp_path):
    p = _write(tmp_path)
    prereg.freeze(p)
    prereg.assert_frozen(p)   # no raise


def test_editing_criteria_after_freeze_is_caught(tmp_path):
    p = _write(tmp_path)
    prereg.freeze(p)
    tampered = LEDGER.replace("effect < -0.05", "effect < -0.01")  # move the goalposts
    p.write_text(tampered, encoding="utf-8")
    with pytest.raises(prereg.PreRegError, match="changed after freeze"):
        prereg.assert_frozen(p)


def test_editing_outside_the_section_is_allowed(tmp_path):
    p = _write(tmp_path)
    prereg.freeze(p)
    # editing Results / Status must NOT invalidate the freeze
    p.write_text(LEDGER.replace("(filled later)", "primary effect -0.073"), encoding="utf-8")
    prereg.assert_frozen(p)


def test_refreeze_with_changed_section_forbidden(tmp_path):
    p = _write(tmp_path)
    prereg.freeze(p)
    p.write_text(LEDGER.replace("-0.05", "-0.01"), encoding="utf-8")
    with pytest.raises(prereg.PreRegError, match="already frozen"):
        prereg.freeze(p)


def test_missing_section_raises(tmp_path):
    p = _write(tmp_path, "# H1\n\n## Hypothesis\n\nno prereg here\n")
    with pytest.raises(prereg.PreRegError, match="no .* section"):
        prereg.freeze(p)
