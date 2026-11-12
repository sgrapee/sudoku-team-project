"""지역 탐색(min-conflicts) 테스트.

핵심 검증은 두 가지다.
1) 위반 함수의 정의: 모든 제약에서 '위반 0 <=> Constraint.check 통과'
2) 탐색기의 계약: 단서 보존, 결과가 모든 제약을 만족, seed 재현성, 한도 준수
"""

from __future__ import annotations

import random

import pytest

from sudoku_engine import (
    AllDifferent, Arrow, Grid, KillerCage, LessThan, LocalSearchConfig, Model, Parity,
    Sandwich, SolverConfig, Thermometer, solve, solve_local_search,
)
from sudoku_engine.benchmark import run_method_comparison
from sudoku_engine.local_search import violation

G = Grid()
EASY = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"
HARD = "4.....8.5.3..........7......2.....6.....8.4......1.......6.3.7.5..2.....1.4......"


def _solution() -> dict:
    m = Model(G)
    m.load_puzzle(EASY)
    return solve(m, SolverConfig()).solution


def _easier_givens(keep: int = 55, seed: int = 1) -> dict:
    """정답에서 keep개 칸만 남긴다. 지역 탐색이 짧은 시간에 풀 수 있는 난이도."""
    sol = _solution()
    cells = random.Random(seed).sample(list(G.cells), keep)
    return {c: sol[c] for c in cells}


# --------------------------------------------------------------- 위반 함수
CONSTRAINTS = {
    "alldiff": AllDifferent([(0, 0), (0, 1), (1, 0)]),
    "killer": KillerCage([(0, 0), (0, 1)], 10),
    "killer_nodistinct": KillerCage([(0, 0), (0, 1)], 10, distinct=False),
    "thermo": Thermometer([(0, 0), (0, 1), (0, 2)]),
    "thermo_nonstrict": Thermometer([(0, 0), (0, 1), (0, 2)], strict=False),
    "arrow": Arrow((0, 0), [(0, 1), (0, 2)]),
    "sandwich": Sandwich([(0, c) for c in range(5)], 2),
    "even": Parity([(0, 0), (0, 1)], even=True),
    "odd": Parity([(0, 0), (0, 1)], even=False),
    "lessthan": LessThan((0, 0), (0, 1)),
}


@pytest.mark.parametrize("name", list(CONSTRAINTS))
def test_violation_zero_iff_check_passes(name):
    """위반 0과 check 통과는 같은 말이어야 한다(탐색기가 해를 잘못 선언하지 않도록)."""
    con = CONSTRAINTS[name]
    rnd = random.Random(7)
    zeros = nonzeros = 0
    for _ in range(1500):
        a = {c: rnd.randint(1, 9) for c in G.cells}
        v = violation(con, a)
        assert v >= 0
        if isinstance(con, Sandwich):
            vals = [a[c] for c in con.line]
            if con.low not in vals or con.high not in vals:
                assert v > 0  # check()는 이런 할당을 가정하지 않는다
                nonzeros += 1
                continue
        assert (v == 0) == con.check(a), f"{name}: violation={v}, check={con.check(a)}, a={ {c: a[c] for c in con.scope()} }"
        zeros += v == 0
        nonzeros += v != 0
    assert zeros > 0 and nonzeros > 0  # 두 경우를 모두 시험했는지


def test_solution_has_zero_violation_everywhere():
    sol = _solution()
    m = Model(G)
    assert all(violation(con, sol) == 0 for con in m.constraints)


# --------------------------------------------------------------- 탐색기 계약
def _solve_with_seeds(model: Model, init: str = "row", seeds: int = 12, max_steps: int = 30000):
    """seed 하나에 의존하지 않도록 여러 seed를 시도한다(파이썬 버전별 난수열 차이 대비)."""
    for seed in range(seeds):
        res = solve_local_search(model, LocalSearchConfig(init=init, seed=seed, max_steps=max_steps))
        if res.solved:
            return res
    return res


@pytest.mark.parametrize("init", ["random", "row"])
def test_solves_puzzle_with_many_givens(init):
    model = Model(G, givens=_easier_givens())
    res = _solve_with_seeds(model, init=init)
    assert res.solved
    assert model.is_complete_solution(res.solution)
    assert res.stats.best_violation == 0


def test_givens_are_preserved():
    givens = _easier_givens()
    model = Model(G, givens=givens)
    res = _solve_with_seeds(model)
    assert res.solved
    assert all(res.solution[c] == v for c, v in givens.items())


def test_variant_constraints_are_satisfied():
    sol = _solution()
    cons = [
        KillerCage([(0, 0), (0, 1), (1, 0)], sum(sol[c] for c in [(0, 0), (0, 1), (1, 0)])),
        Parity([c for c in G.cells if sol[c] % 2 == 0][:6], even=True),
        LessThan((4, 4), (4, 5)) if sol[(4, 4)] < sol[(4, 5)] else LessThan((4, 5), (4, 4)),
    ]
    cells = random.Random(3).sample(list(G.cells), 50)
    model = Model(G, cons, {c: sol[c] for c in cells})
    res = _solve_with_seeds(model)
    assert res.solved
    assert model.is_valid(res.solution)
    assert all(con.check(res.solution) for con in cons)


def test_same_seed_gives_same_run():
    model = Model(G)
    model.load_puzzle(HARD)
    cfg = dict(init="row", seed=5, max_steps=1500)
    a = solve_local_search(model, LocalSearchConfig(**cfg))
    b = solve_local_search(model, LocalSearchConfig(**cfg))
    assert a.stats.steps == b.stats.steps
    assert a.stats.best_violation == b.stats.best_violation
    assert a.solution == b.solution


def test_contradictory_givens_are_rejected_immediately():
    model = Model(G, givens={(0, 0): 5, (0, 1): 5})
    res = solve_local_search(model, LocalSearchConfig(seed=0, max_steps=1000))
    assert not res.solved and res.stats.steps == 0


def test_step_limit_is_respected():
    model = Model(G)
    model.load_puzzle(HARD)
    res = solve_local_search(model, LocalSearchConfig(seed=0, max_steps=50))
    assert not res.solved
    assert res.stats.step_limit_hit and res.stats.steps == 50


def test_time_limit_is_respected():
    model = Model(G)
    model.load_puzzle(HARD)
    res = solve_local_search(model, LocalSearchConfig(seed=0, time_limit=0.1))
    assert not res.solved and res.stats.timed_out
    assert res.stats.elapsed < 2.0


def test_complete_valid_givens_are_solved_without_moves():
    sol = _solution()
    model = Model(G, givens=sol)
    res = solve_local_search(model, LocalSearchConfig(seed=0, max_steps=10))
    assert res.solved and res.stats.steps == 0 and res.solution == sol


def test_unsolvable_puzzle_is_reported_as_unsolved_not_wrong():
    """해가 없는 문제에서 잘못된 해를 내놓지 않는다(못 찾았다는 것이 '해 없음'은 아니다).

    단서끼리는 모순이 없지만 (0,0)에 들어갈 수가 없다: 0행에 1~8이 있으니 9뿐인데, 0열에 이미 9가 있다.
    """
    givens = {(0, c): c for c in range(1, 9)}
    givens[(1, 0)] = 9
    model = Model(G, givens=givens)
    assert model.is_valid(givens)  # 단서 자체는 일관적
    assert not solve(model, SolverConfig()).solved  # 백트래킹은 해 없음을 증명한다
    res = solve_local_search(model, LocalSearchConfig(seed=0, max_steps=3000))
    assert not res.solved
    assert res.stats.best_violation > 0


@pytest.mark.parametrize("bad", [{"noise": -0.1}, {"noise": 1.5}, {"patience": 0}, {"init": "magic"}])
def test_invalid_config_is_rejected(bad):
    with pytest.raises(ValueError):
        LocalSearchConfig(**bad)


# --------------------------------------------------------------- 벤치마크 연동
def test_method_comparison_table_shape():
    rows = run_method_comparison(
        [_easier_givens()], time_limit=2.0,
        bt_configs=[SolverConfig(var_order="mrv_degree", val_order="lcv", propagation="ac3")],
        ls_configs=[LocalSearchConfig(init="row")],
        trials=2,
    )
    assert [r["kind"] for r in rows] == ["backtracking", "local_search"]
    assert rows[0]["solved"] == "1/1" and rows[0]["solve_rate"] == "100%"
    assert rows[1]["solved"].endswith("/2")  # 지역 탐색은 퍼즐당 trials회
    assert set(rows[0]) >= {"method", "solved", "solve_rate", "median_ms_solved", "avg_ms_fail_as_limit"}


def test_method_comparison_accepts_prebuilt_models():
    sol = _solution()
    evens = [c for c in G.cells if sol[c] % 2 == 0][:3]  # 정답과 모순되지 않는 제약만 건다
    model = Model(G, [Parity(evens, even=True)], _easier_givens())
    rows = run_method_comparison(
        [model], time_limit=2.0,
        bt_configs=[SolverConfig(var_order="mrv_degree", val_order="lcv", propagation="ac3")],
        ls_configs=[LocalSearchConfig(init="row")],
    )
    assert rows[0]["solved"] == "1/1"
