"""지역 탐색 비교 기준선: min-conflicts.

백트래킹(완전 탐색 + 제약 전파)이 이 문제에 적합한지를 실험으로 보이기 위해,
수업에서 배운 지역 탐색(local search)을 같은 Model 위에서 돌려 비교한다.

알고리즘 (AIMA의 Min-Conflicts + 표준 보강 두 가지)
--------------------------------------------------
1. 모든 빈칸에 값을 채워 '완전한 할당'에서 시작한다. 단서 칸은 끝까지 고정한다.
2. 위반이 하나도 없으면 종료한다. 아니면 위반에 관여한 빈칸 하나를 무작위로 고른다.
3. 그 칸의 값을, 그 칸에 걸린 제약의 위반 합계가 가장 작아지는 값으로 바꾼다.
   동률이면 무작위. (현재 값을 유지하는 것도 후보다)
   - 보강 1 noise    : 확률 p로 값을 무작위로 고른다(random walk). 국소 최솟값에서 빠져나온다.
   - 보강 2 restart  : 최저 위반 합계가 patience 스텝 동안 줄지 않으면 처음부터 다시 시작한다.

위반 함수
---------
제약마다 '얼마나 어겼는가'를 정수로 돌려준다. 0이면 만족. 0/1로만 세면 이동의 방향을
알 수 없어 지역 탐색이 불리해지므로, 가능한 제약은 정도(graded)로 센다.

    AllDifferent  같은 값을 가진 쌍의 수
    KillerCage    |합 - 목표| + (distinct이면) 같은 값 쌍의 수
    Thermometer   인접 칸 쌍에서 모자란 만큼의 합
    Arrow         |화살표 합 - 동그라미 값|
    Sandwich      |샌드위치 합 - 목표| (1·9 중 하나라도 줄에 없으면 1)
    Parity        홀짝이 틀린 칸의 수
    LessThan      a < b가 아니면 (a - b + 1)
    그 밖의 제약  check()가 False면 1

모든 위반 함수는 '위반 0 <=> Constraint.check() 통과'를 만족해야 하며,
이는 tests/test_local_search.py가 무작위 할당으로 확인한다.

공정성 메모 (발표·보고서용)
--------------------------
- 이 구현은 제약 전파를 쓰지 않는다(지역 탐색의 정의). 비교 대상인 백트래킹이 전파로 얻는
  이득을 보이는 것이 목적이다.
- 해가 있어도 못 찾을 수 있다(불완전). 못 찾았다는 것이 '해 없음'을 뜻하지 않는다.
- 결과는 seed에 따라 달라진다. 비교할 때는 여러 seed로 반복해 성공률을 보고한다.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from .constraints import (
    AllDifferent,
    Arrow,
    Constraint,
    KillerCage,
    LessThan,
    Parity,
    Sandwich,
    Thermometer,
)
from .core import Cell
from .model import Model

INITS = ("random", "row")


# ----------------------------------------------------------------- 위반 함수
def _dup_pairs(values: list[int]) -> int:
    counts: dict[int, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return sum(k * (k - 1) // 2 for k in counts.values())


def violation(con: Constraint, a: dict[Cell, int]) -> int:
    """완전한 할당 a에서 제약 con을 얼마나 어겼는지. 0이면 만족."""
    if isinstance(con, AllDifferent):
        return _dup_pairs([a[c] for c in con.cells])
    if isinstance(con, KillerCage):
        vals = [a[c] for c in con.cells]
        v = abs(sum(vals) - con.total)
        if con.distinct:
            v += _dup_pairs(vals)
        return v
    if isinstance(con, Thermometer):
        step = 1 if con.strict else 0
        v = 0
        for x, y in zip(con.path, con.path[1:]):
            need = a[x] + step
            if a[y] < need:
                v += need - a[y]
        return v
    if isinstance(con, Arrow):
        return abs(sum(a[c] for c in con.path) - a[con.circle])  # type: ignore[index]
    if isinstance(con, Sandwich):
        vals = [a[c] for c in con.line]
        if con.low not in vals or con.high not in vals:
            return 1
        i, j = vals.index(con.low), vals.index(con.high)
        lo, hi = (i, j) if i < j else (j, i)
        return abs(sum(vals[lo + 1:hi]) - con.total)
    if isinstance(con, Parity):
        want = 0 if con.even else 1
        return sum(1 for c in con.cells if a[c] % 2 != want)
    if isinstance(con, LessThan):
        x, y = a[con.smaller], a[con.larger]
        return 0 if x < y else x - y + 1
    return 0 if con.check(a) else 1


# ----------------------------------------------------------------- 설정·결과
@dataclass
class LocalSearchConfig:
    """실험용 설정."""

    # 기본값은 puzzles_easy.txt의 7~12번째 퍼즐 6개에서 noise {0, .05, .15} x patience {1000, 10000}
    # x init을 훑어 고른 값이다(스텝 4만 회 제한, 최선은 row/0.05/10000). 성능 비교는 이 퍼즐을 빼고 한다.
    noise: float = 0.05          # 무작위 값을 고를 확률
    patience: int = 10000        # 최저 위반이 이 스텝 동안 줄지 않으면 재시작
    init: str = "random"         # random: 빈칸을 무작위 값으로 / row: 각 줄을 순열로 채움
    max_steps: int | None = None  # 전체 스텝 상한(재시작 포함)
    seed: int | None = None
    time_limit: float | None = None

    def __post_init__(self) -> None:
        if self.init not in INITS:
            raise ValueError(f"init은 {INITS} 중 하나여야 합니다")
        if not 0.0 <= self.noise <= 1.0:
            raise ValueError("noise는 0~1 사이여야 합니다")
        if self.patience < 1:
            raise ValueError("patience는 1 이상이어야 합니다")

    def label(self) -> str:
        return f"min-conflicts/{self.init}/noise{self.noise:g}"


@dataclass
class LocalSearchStats:
    """계측치. steps는 '값을 바꾸기로 한 결정'의 수라서 백트래킹의 노드 수와 단위가 다르다.
    설정 간 비교는 시간과 성공률로 한다."""

    steps: int = 0
    restarts: int = 0
    best_violation: int | None = None   # 도달한 최저 위반 합계(0이면 해)
    elapsed: float = 0.0
    timed_out: bool = False
    step_limit_hit: bool = False

    def as_dict(self) -> dict:
        return {
            "steps": self.steps,
            "restarts": self.restarts,
            "best_violation": self.best_violation,
            "elapsed_ms": round(self.elapsed * 1000, 3),
            "timed_out": self.timed_out,
            "step_limit_hit": self.step_limit_hit,
        }


@dataclass
class LocalSearchResult:
    solution: dict[Cell, int] | None
    stats: LocalSearchStats
    config: LocalSearchConfig

    @property
    def solved(self) -> bool:
        return self.solution is not None


# ----------------------------------------------------------------- 탐색기
class LocalSearch:
    def __init__(self, model: Model, config: LocalSearchConfig | None = None) -> None:
        self.model = model
        self.config = config or LocalSearchConfig()
        self.rng = random.Random(self.config.seed)
        self.stats = LocalSearchStats()

        grid = model.grid
        self._values = list(grid.values)
        self._cons: list[Constraint] = list(model.constraints)
        index = {id(con): i for i, con in enumerate(self._cons)}
        self._scopes: list[tuple[Cell, ...]] = [con.scope() for con in self._cons]
        self._of: dict[Cell, list[int]] = {
            cell: [index[id(con)] for con in model.constraints_of.get(cell, ())]
            for cell in grid.cells
        }
        self._free: list[Cell] = [c for c in grid.cells if c not in model.givens]
        self._free_set = set(self._free)

    # -------------------------------------------------------------- 초기 상태
    def _initial_state(self) -> dict[Cell, int]:
        state: dict[Cell, int] = dict(self.model.givens)
        if self.config.init == "random":
            for cell in self._free:
                state[cell] = self.rng.choice(self._values)
            return state
        # row: 각 줄의 단서에 없는 숫자를 섞어 빈칸에 채운다
        for row in self.model.grid.rows:
            blanks = [c for c in row if c in self._free_set]
            missing = [v for v in self._values if v not in {state[c] for c in row if c in state}]
            self.rng.shuffle(missing)
            for cell in blanks:
                state[cell] = missing.pop() if missing else self.rng.choice(self._values)
        return state

    # -------------------------------------------------------------- 탐색
    def solve(self) -> LocalSearchResult:
        cfg = self.config
        self.stats = LocalSearchStats()
        start = time.perf_counter()
        deadline = start + cfg.time_limit if cfg.time_limit is not None else None

        solution = self._run(deadline)

        self.stats.elapsed = time.perf_counter() - start
        return LocalSearchResult(solution, self.stats, cfg)

    def _run(self, deadline: float | None) -> dict[Cell, int] | None:
        cfg = self.config
        stats = self.stats
        model = self.model

        # 단서끼리 이미 모순이면 어떤 탐색으로도 풀 수 없다
        if not model.is_valid(model.givens):
            return None

        cons, scopes, of = self._cons, self._scopes, self._of
        values, rng, free_set = self._values, self.rng, self._free_set

        while True:
            state = self._initial_state()
            cv = [violation(con, state) for con in cons]
            total = sum(cv)
            bad = {i for i, v in enumerate(cv) if v}
            best = total
            since_best = 0
            stats.best_violation = total if stats.best_violation is None else min(stats.best_violation, total)

            while True:
                if total == 0:
                    if not model.is_valid(state):  # 위반 함수와 check()의 불일치는 조용히 넘기지 않는다
                        raise RuntimeError("위반 함수와 Constraint.check가 일치하지 않습니다")
                    stats.best_violation = 0
                    return dict(state)

                if cfg.max_steps is not None and stats.steps >= cfg.max_steps:
                    stats.step_limit_hit = True
                    return None
                if deadline is not None and (stats.steps & 63) == 0 and time.perf_counter() > deadline:
                    stats.timed_out = True
                    return None

                conflicted = sorted({c for i in bad for c in scopes[i] if c in free_set})
                if not conflicted:
                    return None  # 위반이 단서 칸에만 걸려 있다 = 이동으로 고칠 수 없음

                cell = rng.choice(conflicted)
                touched = of[cell]

                if rng.random() < cfg.noise:
                    new_value = rng.choice(values)
                else:
                    best_cost: int | None = None
                    choices: list[int] = []
                    old_value = state[cell]
                    for val in values:
                        state[cell] = val
                        cost = 0
                        for i in touched:
                            cost += violation(cons[i], state)
                        if best_cost is None or cost < best_cost:
                            best_cost, choices = cost, [val]
                        elif cost == best_cost:
                            choices.append(val)
                    state[cell] = old_value
                    new_value = rng.choice(choices)

                state[cell] = new_value
                for i in touched:
                    nv = violation(cons[i], state)
                    total += nv - cv[i]
                    cv[i] = nv
                    if nv:
                        bad.add(i)
                    else:
                        bad.discard(i)
                stats.steps += 1

                if total < best:
                    best = total
                    since_best = 0
                    if stats.best_violation is None or total < stats.best_violation:
                        stats.best_violation = total
                else:
                    since_best += 1
                    if since_best >= cfg.patience:
                        stats.restarts += 1
                        break


# ----------------------------------------------------------------- 헬퍼
def solve_local_search(model: Model, config: LocalSearchConfig | None = None) -> LocalSearchResult:
    return LocalSearch(model, config).solve()
