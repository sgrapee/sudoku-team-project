"""전파 단계 "ac3_pure"(순수 AC-3, hidden single 없음) 테스트.

"ac3"는 hidden single을 포함한 채로 그대로 두고, 순수 AC-3를 따로 잴 수 있게
"ac3_pure"를 더했다. 여기서는 (1) hidden single을 정말 건너뛰는지, (2) 전파가
정답 값을 지우지 않는지, (3) 답·해 개수·해 없음 판정이 ac3와 같은지,
(4) 강도 순서 fc ≥ ac3_pure ≥ ac3 (분기 노드)를 확인한다.
"""

from __future__ import annotations

import random

import pytest

from sudoku_engine import Grid, KillerCage, Model, SolverConfig, count_solutions, solve
from sudoku_engine.propagation import LEVELS, PropagationStats, propagate

EASY = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"
HARD = "4.....8.5.3..........7......2.....6.....8.4......1.......6.3.7.5..2.....1.4......"


@pytest.fixture(scope="module")
def grid() -> Grid:
    return Grid()


@pytest.fixture(scope="module")
def easy_solution(grid: Grid) -> dict:
    model = Model(grid)
    model.load_puzzle(EASY)
    result = solve(model, SolverConfig(time_limit=30))
    assert result.solved
    return result.solution


def _solve(grid: Grid, puzzle: str, level: str):
    model = Model(grid)
    model.load_puzzle(puzzle)
    return solve(model, SolverConfig(var_order="mrv", val_order="asc", propagation=level, time_limit=60))


def test_level_is_registered_between_fc_and_ac3() -> None:
    assert LEVELS == ("none", "fc", "ac3_pure", "ac3", "full")
    assert SolverConfig(propagation="ac3_pure").propagation == "ac3_pure"


def test_default_propagation_is_still_ac3() -> None:
    assert SolverConfig().propagation == "ac3"


def test_ac3_pure_skips_hidden_single(grid: Grid) -> None:
    """0행에서 1이 들어갈 칸이 (0,0)뿐이고 확정 칸은 없다 → hidden single만 1을 놓을 수 있다."""
    model = Model(grid)
    base = model.initial_domains()
    base[(0, 0)] = {1, 2}
    for c in range(1, 9):
        base[(0, c)].discard(1)

    pure = {cell: set(dom) for cell, dom in base.items()}
    assert propagate(model, pure, "ac3_pure", PropagationStats())
    assert pure == base  # 확정 칸이 없으니 순수 AC-3는 아무것도 지우지 못한다

    with_hs = {cell: set(dom) for cell, dom in base.items()}
    assert propagate(model, with_hs, "ac3", PropagationStats())
    assert with_hs[(0, 0)] == {1}
    assert 1 not in with_hs[(1, 0)]  # 확정된 1이 같은 열·박스로 전파됨


@pytest.mark.parametrize("seed", range(8))
def test_ac3_pure_never_removes_the_true_value(grid: Grid, easy_solution: dict, seed: int) -> None:
    rnd = random.Random(seed)
    keep = rnd.sample(list(grid.cells), 24)
    cages = [KillerCage([(r, 0), (r, 1)], easy_solution[(r, 0)] + easy_solution[(r, 1)]) for r in range(0, 9, 2)]
    model = Model(grid, cages, {c: easy_solution[c] for c in keep})
    domains = model.initial_domains()
    assert propagate(model, domains, "ac3_pure", PropagationStats())
    for cell in grid.cells:
        assert easy_solution[cell] in domains[cell], f"{cell}에서 정답 값이 제거됨"


@pytest.mark.parametrize("puzzle", [EASY, HARD])
def test_ac3_pure_finds_the_same_solution(grid: Grid, puzzle: str) -> None:
    pure, with_hs = _solve(grid, puzzle, "ac3_pure"), _solve(grid, puzzle, "ac3")
    assert pure.solved and with_hs.solved
    assert pure.solution == with_hs.solution


def test_strength_order_fc_ac3_pure_ac3(grid: Grid) -> None:
    """분기 노드: fc ≥ ac3_pure ≥ ac3 (HARD, mrv/asc)."""
    nodes = {level: _solve(grid, HARD, level).stats.branch_nodes for level in ("fc", "ac3_pure", "ac3")}
    assert nodes["fc"] >= nodes["ac3_pure"] >= nodes["ac3"]


def test_ac3_pure_counts_solutions_like_ac3(grid: Grid, easy_solution: dict) -> None:
    rnd = random.Random(7)
    keep = rnd.sample(list(grid.cells), 20)  # 단서가 적어 해가 여러 개
    counts = {}
    for level in ("ac3_pure", "ac3"):
        model = Model(grid, [], {c: easy_solution[c] for c in keep})
        counts[level] = count_solutions(model, limit=15, config=SolverConfig(propagation=level, time_limit=30))
    assert counts["ac3_pure"] == counts["ac3"] > 1


def test_ac3_pure_proves_unsat(grid: Grid, easy_solution: dict) -> None:
    """유일해 퍼즐에 정답과 다른 단서를 하나 더하면 해가 없다. 시간 초과 없이 증명해야 한다."""
    model = Model(grid)
    model.load_puzzle(EASY)
    givens = dict(model.givens)
    for cell in grid.cells:
        if cell in givens:
            continue
        peers = [givens[p] for p in model.neighbors[cell] if p in givens]
        wrong = [v for v in range(1, 10) if v != easy_solution[cell] and v not in peers]
        if wrong:
            givens[cell] = wrong[0]
            break
    unsat = Model(grid, [], givens)
    result = solve(unsat, SolverConfig(propagation="ac3_pure", time_limit=30))
    assert not result.solved
    assert not result.stats.timed_out
