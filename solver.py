"""백트래킹 탐색기: 변수 순서 휴리스틱(MRV/Degree), 값 순서 휴리스틱(LCV),
전파 강도 선택, 노드 수 계측.

④ 실험 담당이 쓰는 주요 API
---------------------------
    solve(model, config)              -> SolverResult
    count_solutions(model, limit=2)   -> int
    has_unique_solution(model)        -> bool     # 퍼즐 생성기의 유일해 검증
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from .core import Cell, Domains, copy_domains, solved_assignment
from .model import Model
from .propagation import LEVELS, PropagationStats, initial_propagate, propagate

VAR_ORDERS = ("static", "mrv", "mrv_degree", "random")
VAL_ORDERS = ("asc", "lcv", "random")


@dataclass
class SolverConfig:
    """실험용 설정. 이 조합을 바꿔가며 노드 수를 비교한다."""

    var_order: str = "mrv_degree"
    val_order: str = "lcv"
    propagation: str = "ac3"
    seed: int | None = None
    max_nodes: int | None = None
    time_limit: float | None = None

    def __post_init__(self) -> None:
        if self.var_order not in VAR_ORDERS:
            raise ValueError(f"var_order는 {VAR_ORDERS} 중 하나여야 합니다")
        if self.val_order not in VAL_ORDERS:
            raise ValueError(f"val_order는 {VAL_ORDERS} 중 하나여야 합니다")
        if self.propagation not in LEVELS:
            raise ValueError(f"propagation은 {LEVELS} 중 하나여야 합니다")

    def label(self) -> str:
        return f"{self.var_order}/{self.val_order}/{self.propagation}"


@dataclass
class SolverStats:
    """탐색 계측치. 발표의 '기존 방법 개선' 근거 자료가 되는 숫자들."""

    nodes: int = 0
    branch_nodes: int = 0
    backtracks: int = 0
    assignments: int = 0
    elapsed: float = 0.0
    solutions_found: int = 0
    timed_out: bool = False
    propagation: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {
            "nodes": self.nodes,
            "branch_nodes": self.branch_nodes,
            "backtracks": self.backtracks,
            "assignments": self.assignments,
            "elapsed_ms": round(self.elapsed * 1000, 3),
            "solutions_found": self.solutions_found,
            "timed_out": self.timed_out,
        }
        d.update(self.propagation)
        return d


@dataclass
class SolverResult:
    solution: dict[Cell, int] | None
    stats: SolverStats
    config: SolverConfig

    @property
    def solved(self) -> bool:
        return self.solution is not None


class _Timeout(Exception):
    pass


class Solver:
    """CSP 백트래킹 탐색기."""

    def __init__(self, model: Model, config: SolverConfig | None = None) -> None:
        self.model = model
        self.config = config or SolverConfig()
        self.rng = random.Random(self.config.seed)
        self.stats = SolverStats()
        self._pstats = PropagationStats()
        self._deadline: float | None = None

    # ------------------------------------------------------------ 공개 API
    def solve(self) -> SolverResult:
        sols = self._run(limit=1)
        sol = sols[0] if sols else None
        return SolverResult(sol, self.stats, self.config)

    def solve_all(self, limit: int = 2) -> list[dict[Cell, int]]:
        return self._run(limit=limit)

    # ------------------------------------------------------------ 내부 구현
    def _run(self, limit: int) -> list[dict[Cell, int]]:
        self.stats = SolverStats()
        self._pstats = PropagationStats()
        start = time.perf_counter()
        if self.config.time_limit is not None:
            self._deadline = start + self.config.time_limit

        domains = self.model.initial_domains()
        results: list[dict[Cell, int]] = []

        # 단서가 서로 모순인지 먼저 확인
        givens_ok = self.model.is_valid(self.model.givens)
        if givens_ok:
            ok = initial_propagate(self.model, domains, self.config.propagation, self._pstats)
            if ok:
                try:
                    self._search(domains, set(), results, limit)
                except _Timeout:
                    self.stats.timed_out = True

        self.stats.elapsed = time.perf_counter() - start
        self.stats.solutions_found = len(results)
        self.stats.propagation = self._pstats.as_dict()
        return results

    def _search(
        self, domains: Domains, assigned: set[Cell], results: list, limit: int
    ) -> bool:
        """찾은 해가 limit에 도달하면 True를 돌려 위로 전파한다.

        AIMA 정의대로 '할당된 변수 집합'을 명시적으로 들고 다닌다.
        도메인이 1개로 줄었다는 것과 그 변수가 할당되었다는 것은 다른 사건이며,
        이를 혼동하면 전방 검사가 확정값을 이웃에 전파하지 못해 실제보다
        약하게 측정된다.
        """
        self.stats.nodes += 1
        if self._deadline is not None and time.perf_counter() > self._deadline:
            raise _Timeout
        if self.config.max_nodes is not None and self.stats.nodes > self.config.max_nodes:
            raise _Timeout

        cell = self._select_variable(domains, assigned)
        if cell is None:
            assignment = solved_assignment(domains)
            if assignment is not None and self.model.is_valid(assignment):
                results.append(assignment)
                return len(results) >= limit
            return False

        values = self._order_values(domains, cell)
        if len(values) > 1:
            self.stats.branch_nodes += 1

        for value in values:
            self.stats.assignments += 1
            trial = copy_domains(domains)
            trial[cell] = {value}

            if self.config.propagation == "none":
                partial = {c: next(iter(trial[c])) for c in assigned}
                partial[cell] = value
                partial.update(self.model.givens)
                ok = self.model.is_valid(partial)
            else:
                ok = propagate(
                    self.model, trial, self.config.propagation,
                    self._pstats, changed_cell=cell, changed_value=value,
                )

            if ok:
                if self._search(trial, assigned | {cell}, results, limit):
                    return True
            self.stats.backtracks += 1

        return False

    # -------------------------------------------------------- 변수 순서 휴리스틱
    def _select_variable(self, domains: Domains, assigned: set[Cell]) -> Cell | None:
        unassigned = [
            c for c in self.model.grid.cells
            if c not in assigned and c not in self.model.givens
        ]
        if not unassigned:
            return None

        order = self.config.var_order
        if order == "static":
            return unassigned[0]
        if order == "random":
            return self.rng.choice(unassigned)
        if order == "mrv":
            return min(unassigned, key=lambda c: len(domains[c]))
        # mrv_degree: 남은 후보 수 최소, 동률이면 미확정 이웃이 많은 칸
        return min(
            unassigned,
            key=lambda c: (
                len(domains[c]),
                -sum(1 for nb in self.model.neighbors[c] if len(domains[nb]) > 1),
            ),
        )

    # -------------------------------------------------------- 값 순서 휴리스틱
    def _order_values(self, domains: Domains, cell: Cell) -> list[int]:
        vals = sorted(domains[cell])
        order = self.config.val_order
        if order == "asc":
            return vals
        if order == "random":
            self.rng.shuffle(vals)
            return vals
        # LCV: 이웃 도메인을 가장 적게 깎는 값부터
        def cost(v: int) -> int:
            return sum(1 for nb in self.model.neighbors[cell] if v in domains[nb])

        return sorted(vals, key=cost)


# ------------------------------------------------------------------ 헬퍼 함수
def solve(model: Model, config: SolverConfig | None = None) -> SolverResult:
    return Solver(model, config).solve()


def count_solutions(model: Model, limit: int = 2, config: SolverConfig | None = None) -> int:
    """해의 개수를 최대 limit까지 센다. 생성기(④)의 유일해 검증용."""
    cfg = config or SolverConfig(var_order="mrv_degree", val_order="asc", propagation="ac3")
    return len(Solver(model, cfg).solve_all(limit=limit))


def has_unique_solution(model: Model, config: SolverConfig | None = None) -> bool:
    return count_solutions(model, limit=2, config=config) == 1
