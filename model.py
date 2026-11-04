"""Model: 격자 + 제약 + 단서를 묶고, 탐색에 필요한 인덱스를 미리 만들어 둔다."""

from __future__ import annotations

from collections import defaultdict

from .constraints import AllDifferent, Constraint, classic_constraints
from .core import Cell, Domains, Grid, full_domains


class Model:
    """풀이 대상 문제 하나를 나타낸다."""

    def __init__(
        self,
        grid: Grid | None = None,
        constraints: list[Constraint] | None = None,
        givens: dict[Cell, int] | None = None,
        include_classic: bool = True,
    ) -> None:
        self.grid = grid or Grid()
        self.constraints: list[Constraint] = []
        if include_classic:
            self.constraints.extend(classic_constraints(self.grid))
        if constraints:
            self.constraints.extend(constraints)
        self.givens: dict[Cell, int] = dict(givens or {})
        self._build_index()

    # ------------------------------------------------------------- 인덱싱
    def _build_index(self) -> None:
        g = self.grid
        self.constraints_of: dict[Cell, list[Constraint]] = defaultdict(list)
        for con in self.constraints:
            for cell in con.scope():
                self.constraints_of[cell].append(con)

        # AC-3용 이진 아크와, 아크별 소속 제약
        self.neighbors: dict[Cell, set[Cell]] = {c: set() for c in g.cells}
        for con in self.constraints:
            for a, b in con.binary_arcs():
                self.neighbors[a].add(b)

        # 전역(비이진) 제약만 따로 — 매 전파 때 propagate()를 호출해야 하는 것들
        self.global_constraints: list[Constraint] = [
            con for con in self.constraints if not con.binary_arcs()
        ]
        self.global_of: dict[Cell, list[Constraint]] = defaultdict(list)
        for con in self.global_constraints:
            for cell in con.scope():
                self.global_of[cell].append(con)

        # 인간 기법용 유닛(=AllDifferent 묶음) 목록
        self.units: list[list[Cell]] = [
            list(con.scope()) for con in self.constraints
            if isinstance(con, AllDifferent)
        ]
        self.units_of: dict[Cell, list[list[Cell]]] = defaultdict(list)
        for unit in self.units:
            for cell in unit:
                self.units_of[cell].append(unit)

    # ------------------------------------------------------------- 편의 함수
    def initial_domains(self) -> Domains:
        return full_domains(self.grid, self.givens)

    def add(self, constraint: Constraint) -> None:
        self.constraints.append(constraint)
        self._build_index()

    def set_givens(self, givens: dict[Cell, int]) -> None:
        self.givens = dict(givens)

    def load_puzzle(self, text: str) -> None:
        self.givens = self.grid.parse(text)

    def is_valid(self, assignment: dict[Cell, int]) -> bool:
        """완전/부분 할당이 모든 제약을 만족하는지."""
        return all(con.check(assignment) for con in self.constraints)

    def is_complete_solution(self, assignment: dict[Cell, int]) -> bool:
        if len(assignment) != len(self.grid.cells):
            return False
        return self.is_valid(assignment)

    def summary(self) -> str:
        kinds: dict[str, int] = defaultdict(int)
        for con in self.constraints:
            kinds[con.name] += 1
        parts = ", ".join(f"{k}x{v}" for k, v in sorted(kinds.items()))
        return f"Model(size={self.grid.size}, givens={len(self.givens)}, {parts})"

    def __repr__(self) -> str:  # pragma: no cover
        return self.summary()
