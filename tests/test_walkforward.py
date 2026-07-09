import numpy as np
import pytest

from alpha.study.walkforward import MIN_EMBARGO, PurgedWalkForward, to_session_index


def test_embargo_floor_enforced():
    with pytest.raises(ValueError, match="embargo"):
        PurgedWalkForward(n_splits=3, embargo_sessions=1)
    PurgedWalkForward(n_splits=3, embargo_sessions=MIN_EMBARGO)  # ok


def test_purge_removes_label_overlap_leak():
    # 30 overnight obs: entry=session i, exit=i+1 (label realizes next session)
    n = 30
    entry = np.arange(n)
    exit_ = entry + 1
    wf = PurgedWalkForward(n_splits=3, embargo_sessions=2)
    for fold in wf.split(entry, exit_):
        tlo, thi = fold.test_span
        for i in fold.train:
            # no training label window may touch the test span
            assert not (entry[i] <= thi and exit_[i] >= tlo), (
                f"leak: train obs {i} [{entry[i]},{exit_[i]}] overlaps test [{tlo},{thi}]"
            )


def test_embargo_buffer_applied_both_sides():
    n = 40
    entry = np.arange(n)
    exit_ = entry + 1
    emb = 2
    wf = PurgedWalkForward(n_splits=4, embargo_sessions=emb)
    folds = list(wf.split(entry, exit_, expanding=False))
    assert folds
    for fold in folds:
        tlo, thi = fold.test_span
        for i in fold.train:
            # entries within the embargo buffer on either side are excluded
            assert not ((tlo - emb) <= entry[i] <= (thi + emb))


def test_expanding_trains_only_on_past():
    n = 30
    entry = np.arange(n)
    exit_ = entry + 1
    wf = PurgedWalkForward(n_splits=3, embargo_sessions=2)
    for fold in wf.split(entry, exit_, expanding=True):
        tlo, _ = fold.test_span
        assert np.all(entry[fold.train] < tlo)


def test_to_session_index_maps_and_rejects_nontrading():
    import pandas as pd
    cal = [pd.Timestamp("2026-07-06").date(), pd.Timestamp("2026-07-07").date(),
           pd.Timestamp("2026-07-08").date()]
    idx = to_session_index(["2026-07-08", "2026-07-06"], cal)
    assert list(idx) == [2, 0]
    with pytest.raises(KeyError):
        to_session_index(["2026-07-04"], cal)   # a Saturday, not in calendar
