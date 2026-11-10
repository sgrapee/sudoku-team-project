"""③ 파서 연동 중 발견한 엔진 결함 회귀 테스트."""

import pytest

from sudoku_engine import AllDifferent, Grid, KillerCage, Model, SolverConfig, solve
from sudoku_engine.spec import spec_to_model_or_reason

G = Grid()


@pytest.mark.parametrize("prop", ["fc", "ac3", "full"])
def test_partial_alldiff_is_solvable(prop):
    """9칸 미만 alldiff에 hidden single을 적용하면 해가 있는데도 '해 없음'이 된다."""
    m = Model(G, [AllDifferent([(0, 0), (1, 1), (2, 2), (3, 4)])])
    r = solve(m, SolverConfig(propagation=prop, time_limit=5))
    assert r.solved and m.is_valid(r.solution)


@pytest.mark.parametrize("prop", ["ac3", "full"])
def test_killer_sum_is_propagated(prop):
    """킬러가 이진 아크를 가진다는 이유로 합 전파가 호출되지 않으면 빈 격자에서 시간 초과."""
    m = Model(G, [KillerCage([(7, 7), (7, 8), (8, 7), (8, 8)], 30)])
    r = solve(m, SolverConfig(propagation=prop, time_limit=5))
    assert r.solved and m.is_valid(r.solution)
    assert r.stats.elapsed < 2.0


def test_killer_domains_are_filtered_after_initial_propagation():
    from sudoku_engine.propagation import initial_propagate, PropagationStats

    m = Model(G, [KillerCage([(0, 0), (0, 1)], 3)])
    doms = m.initial_domains()
    assert initial_propagate(m, doms, "ac3", PropagationStats())
    assert doms[(0, 0)] == {1, 2} and doms[(0, 1)] == {1, 2}


def test_timeout_is_not_reported_as_no_solution(monkeypatch):
    """시간 초과로 해를 못 찾은 것을 '해가 존재하지 않습니다'로 보고하면 안 된다."""
    import sudoku_engine.solver as solver_mod

    original = solver_mod.SolverConfig

    def tiny(*args, **kwargs):
        kwargs["time_limit"] = 0.0
        return original(*args, **kwargs)

    monkeypatch.setattr(solver_mod, "SolverConfig", tiny)
    model, reason = spec_to_model_or_reason({"givens": "." * 81, "constraints": []})
    assert "해가 존재하지 않습니다" not in reason


# --- 크래시 입력은 ValueError가 아니라 SpecError(검증 실패)여야 한다 -----------------

CRASH_SPECS = {
    "r1-c1 표기": {"constraints": [{"type": "even", "cells": ["R1-C1"]}]},
    "합이 숫자가 아님": {"constraints": [{"type": "killer", "cells": [[0, 0], [0, 1]], "sum": "열둘"}]},
    "1칸 온도계": {"constraints": [{"type": "thermo", "path": [[0, 0]]}]},
    "80자 givens": {"givens": "." * 80},
    "잘못된 샌드위치 방향": {"constraints": [{"type": "sandwich", "line": "diag", "index": 0, "sum": 10}]},
    "숫자가 아닌 index": {"constraints": [{"type": "sandwich", "line": "row", "index": "a", "sum": 10}]},
    "2행짜리 givens": {"givens": [[5, 3, 0], [6, 0, 0]]},
    "size가 문자열": {"size": "아홉"},
}


@pytest.mark.parametrize("name", list(CRASH_SPECS))
def test_bad_spec_is_rejected_not_crashed(name):
    from sudoku_engine.spec import validate_spec

    ok, msg = validate_spec(CRASH_SPECS[name])
    assert ok is False and msg
