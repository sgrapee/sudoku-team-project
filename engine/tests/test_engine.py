"""엔진 테스트 스위트.

    pytest -q tests/

가장 중요한 것은 test_propagation_soundness — 전파가 정답 값을 실수로
제거하면 solver는 조용히 틀린 답이나 '해 없음'을 내놓는다. 이 버그는
겉으로 드러나지 않으므로 무작위 대량 테스트로만 잡을 수 있다.
"""

from __future__ import annotations

import random

import pytest

from sudoku_engine import (
    AllDifferent,
    Arrow,
    Grid,
    KillerCage,
    Model,
    Parity,
    Sandwich,
    SolverConfig,
    Thermometer,
    count_solutions,
    diagonal_constraints,
    has_unique_solution,
    solve,
)
from sudoku_engine.benchmark import generate_puzzle
from sudoku_engine.propagation import PropagationStats, propagate
from sudoku_engine.solver import VAL_ORDERS, VAR_ORDERS
from sudoku_engine.spec import SpecError, load_spec, spec_to_model_or_reason, validate_spec
from sudoku_engine.techniques import rate_difficulty, next_hint, solve_logically

EASY = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"
HARD = "4.....8.5.3..........7......2.....6.....8.4......1.......6.3.7.5..2.....1.4......"


@pytest.fixture(scope="module")
def grid() -> Grid:
    return Grid()


@pytest.fixture(scope="module")
def easy_solution(grid: Grid) -> dict:
    model = Model(grid)
    model.load_puzzle(EASY)
    result = solve(model)
    assert result.solved
    return result.solution


# ------------------------------------------------------------------ 기본 동작
def test_grid_geometry(grid: Grid) -> None:
    assert len(grid.cells) == 81
    assert len(grid.units) == 27
    assert len(grid.peers[(0, 0)]) == 20
    assert grid.box_index((4, 4)) == 4
    assert len(set(grid.main_diagonal())) == 9


def test_parse_roundtrip(grid: Grid) -> None:
    givens = grid.parse(EASY)
    assert len(givens) == 30
    assert grid.to_string(givens) == EASY
    with pytest.raises(ValueError):
        grid.parse("123")


def test_solve_classic(grid: Grid, easy_solution: dict) -> None:
    assert len(easy_solution) == 81
    model = Model(grid, givens=easy_solution)
    assert model.is_complete_solution(easy_solution)


@pytest.mark.parametrize("var_order", VAR_ORDERS)
@pytest.mark.parametrize("val_order", VAL_ORDERS)
@pytest.mark.parametrize("propagation", ["fc", "ac3", "full"])
def test_all_configs_agree(
    grid: Grid, easy_solution: dict, var_order: str, val_order: str, propagation: str
) -> None:
    """휴리스틱 조합이 달라도 유일해는 하나여야 한다."""
    model = Model(grid)
    model.load_puzzle(EASY)
    cfg = SolverConfig(
        var_order=var_order, val_order=val_order,
        propagation=propagation, seed=0, time_limit=60,
    )
    result = solve(model, cfg)
    assert result.solved
    assert result.solution == easy_solution


def test_uniqueness_api(grid: Grid) -> None:
    model = Model(grid)
    model.load_puzzle(EASY)
    assert has_unique_solution(model)
    empty = Model(grid)
    assert count_solutions(empty, limit=3) == 3


def test_unsolvable_detected(grid: Grid) -> None:
    """같은 행에 5가 두 번 있는 판은 해가 없어야 한다."""
    model = Model(grid)
    model.set_givens({(0, 0): 5, (0, 1): 5})
    assert count_solutions(model, limit=1) == 0


# --------------------------------------------------------------- 변형 제약
def _derived_variants(sol: dict, grid: Grid):
    """정답에서 역산해 반드시 성립하는 변형 제약을 만든다."""
    cons = []
    cage = [(0, 0), (0, 1), (1, 0)]
    if len({sol[c] for c in cage}) == 3:
        cons.append(KillerCage(cage, sum(sol[c] for c in cage)))
    for r in range(9):
        for i in range(7):
            seg = [(r, i), (r, i + 1), (r, i + 2)]
            if sol[seg[0]] < sol[seg[1]] < sol[seg[2]]:
                cons.append(Thermometer(seg))
                break
    for r in range(9):
        vals = [sol[(r, c)] for c in range(9)]
        i, j = vals.index(1), vals.index(9)
        lo, hi = min(i, j), max(i, j)
        cons.append(Sandwich(grid.rows[r], sum(vals[lo + 1 : hi])))
    evens = [c for c in grid.cells if sol[c] % 2 == 0][:6]
    cons.append(Parity(evens, even=True))
    return cons


def test_variant_constraints_accept_truth(grid: Grid, easy_solution: dict) -> None:
    for con in _derived_variants(easy_solution, grid):
        assert con.check(easy_solution), con.describe()


def test_variant_puzzle_solvable(grid: Grid, easy_solution: dict) -> None:
    cons = _derived_variants(easy_solution, grid)
    rnd = random.Random(3)
    keep = rnd.sample(list(grid.cells), 22)
    model = Model(grid, cons, {c: easy_solution[c] for c in keep})
    result = solve(model, SolverConfig(propagation="ac3", time_limit=30))
    assert result.solved
    assert result.solution == easy_solution


def test_arrow_and_diagonal(grid: Grid) -> None:
    model = Model(grid, diagonal_constraints(grid))
    model.load_puzzle("." * 81)
    result = solve(model, SolverConfig(time_limit=30))
    assert result.solved
    for diag in (grid.main_diagonal(), grid.anti_diagonal()):
        assert len({result.solution[c] for c in diag}) == 9

    sol = result.solution
    placed = False
    for r in range(9):
        for c in range(7):
            if sol[(r, c)] == sol[(r, c + 1)] + sol[(r, c + 2)]:
                assert Arrow((r, c), [(r, c + 1), (r, c + 2)]).check(sol)
                placed = True
                break
        if placed:
            break
    assert placed


@pytest.mark.parametrize("seed", range(12))
def test_propagation_soundness(grid: Grid, easy_solution: dict, seed: int) -> None:
    """전파는 정답에 속한 값을 절대 제거하면 안 된다."""
    cons = _derived_variants(easy_solution, grid)
    rnd = random.Random(seed)
    keep = rnd.sample(list(grid.cells), 25)
    model = Model(grid, cons, {c: easy_solution[c] for c in keep})
    domains = model.initial_domains()
    stats = PropagationStats()
    assert propagate(model, domains, "full", stats)
    for cell in grid.cells:
        assert easy_solution[cell] in domains[cell], f"{cell}에서 정답 값이 제거됨"


# ------------------------------------------------------------------ 인간 기법
def test_logical_solver_matches_truth(grid: Grid, easy_solution: dict) -> None:
    model = Model(grid)
    model.load_puzzle(EASY)
    result = solve_logically(model)
    assert result.solved
    assert result.assignment == easy_solution


def test_difficulty_excludes_setup(grid: Grid) -> None:
    """단서 반영이 기법으로 집계되면 안 된다."""
    model = Model(grid)
    model.load_puzzle(EASY)
    rating = rate_difficulty(model)
    assert rating["solvable_by_logic"]
    assert rating["steps"] < 81 - len(model.givens) + 1
    assert rating["level"] >= 1


def test_hint_is_actionable(grid: Grid) -> None:
    model = Model(grid)
    model.load_puzzle(EASY)
    hint = next_hint(model)
    assert hint is not None
    assert hint.explanation
    assert hint.cell is not None or hint.eliminated


def test_hard_puzzle_rated_higher(grid: Grid) -> None:
    easy_model = Model(grid)
    easy_model.load_puzzle(EASY)
    hard_model = Model(grid)
    hard_model.load_puzzle(HARD)
    assert rate_difficulty(hard_model)["score"] > rate_difficulty(easy_model)["score"]


# ------------------------------------------------------------------ 생성기
@pytest.mark.parametrize("seed", range(4))
def test_generator_produces_unique(seed: int) -> None:
    puzzle, solution = generate_puzzle(target_givens=28, seed=seed)
    model = Model(Grid(), givens=puzzle)
    assert count_solutions(model, limit=2) == 1
    assert solve(model).solution == solution


# ------------------------------------------------------------- JSON 스펙
def test_spec_accepts_loose_notation() -> None:
    spec = {
        "givens": EASY,
        "constraints": [
            {"type": "standard"},
            {"kind": "thermometer", "cells": ["r5c5", "r5c6", "r5c7"]},
            {"type": "even", "cells": [{"row": 3, "col": 3}]},
        ],
    }
    ok, _ = validate_spec(spec)
    assert ok


@pytest.mark.parametrize(
    "spec",
    [
        {"constraints": [{"type": "killer", "cells": [[0, 0], [0, 1]], "sum": 30}]},
        {"constraints": [{"type": "killer", "cells": [[0, 0], [9, 9]], "sum": 10}]},
        {"constraints": [{"type": "unicorn"}]},
        {"constraints": [{"type": "sandwich", "line": "row", "index": 0}]},
        {"constraints": [{"type": "alldiff", "cells": [[0, 0], [0, 0]]}]},
        {"givens": "11" + "." * 79},
        "{ not json ]",
    ],
)
def test_spec_rejects_invalid(spec) -> None:
    ok, msg = validate_spec(spec)
    assert not ok
    assert msg


def test_spec_detects_unsatisfiable() -> None:
    spec = {
        "givens": "." * 81,
        "constraints": [
            {"type": "thermo", "path": [[0, 0], [0, 1], [0, 2]]},
            {"type": "thermo", "path": [[0, 2], [0, 1], [0, 0]]},
        ],
    }
    model, reason = spec_to_model_or_reason(spec)
    assert model is None
    assert "해가 존재하지" in reason


def test_spec_warns_on_multiple_solutions() -> None:
    model, reason = spec_to_model_or_reason({"givens": "." * 81})
    assert model is not None
    assert "둘 이상" in reason


def test_spec_error_message_is_readable() -> None:
    with pytest.raises(SpecError) as exc:
        load_spec({"constraints": [{"type": "killer", "cells": [[0, 0]], "sum": 99}]})
    assert "killer" in str(exc.value)


# ------------------------------------------------------------------ 계측
def test_stats_are_recorded(grid: Grid) -> None:
    model = Model(grid)
    model.load_puzzle(HARD)
    result = solve(model, SolverConfig(propagation="ac3", time_limit=30))
    stats = result.stats.as_dict()
    assert stats["nodes"] >= 1
    assert stats["elapsed_ms"] > 0
    assert "arc_revisions" in stats
    assert stats["branch_nodes"] <= stats["nodes"]


def test_propagation_strength_is_monotone(grid: Grid) -> None:
    """전파가 강할수록 분기 노드가 늘어나서는 안 된다."""
    counts = {}
    for level in ("fc", "ac3", "full"):
        model = Model(grid)
        model.load_puzzle(HARD)
        cfg = SolverConfig(var_order="mrv", val_order="asc", propagation=level, time_limit=60)
        result = solve(model, cfg)
        assert result.solved
        counts[level] = result.stats.branch_nodes
    assert counts["ac3"] <= counts["fc"]
    assert counts["full"] <= counts["ac3"]
