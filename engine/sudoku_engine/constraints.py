"""제약(Constraint) 인터페이스와 변형 스도쿠 제약 구현체들.

팀 계약(1주차 확정)
-------------------
    Constraint.scope()                 -> tuple[Cell, ...]
    Constraint.propagate(domains)      -> bool   # 도메인을 in-place 축소, 모순이면 False
    Constraint.check(assignment)       -> bool   # 부분/완전 할당의 위반 여부

원래 스케치는 propagate가 새 dict를 반환하는 형태였으나, 탐색 중 수십만 번
호출되므로 in-place 축소 + bool 반환으로 확정했다. 새 dict가 필요하면
core.copy_domains()로 복사한 뒤 넘기면 된다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from itertools import combinations
from typing import Sequence

from .core import Cell, Domains

# 조합 탐색이 폭발하지 않도록 하는 안전장치
_ENUM_BUDGET = 200_000


class Constraint(ABC):
    """모든 제약의 공통 인터페이스."""

    name: str = "constraint"

    @abstractmethod
    def scope(self) -> tuple[Cell, ...]:
        """이 제약이 관여하는 칸들."""

    @abstractmethod
    def propagate(self, domains: Domains) -> bool:
        """도메인을 in-place로 축소한다. 모순이 생기면 False."""

    @abstractmethod
    def check(self, assignment: dict[Cell, int]) -> bool:
        """부분 할당이 이 제약을 아직 위반하지 않았는지."""

    def binary_arcs(self) -> list[tuple[Cell, Cell]]:
        """AC-3용 이진 != 아크. 이진 분해가 불가능한 제약은 빈 리스트."""
        return []

    def describe(self) -> str:
        return f"{self.name}{self.scope()}"

    def __repr__(self) -> str:  # pragma: no cover - 디버그 편의
        return f"<{type(self).__name__} {self.describe()}>"


# ===================================================================== AllDiff
class AllDifferent(Constraint):
    """서로 다른 값을 가져야 하는 셀 묶음. 행/열/박스/대각선 모두 이걸로 표현."""

    name = "alldiff"

    def __init__(self, cells: Sequence[Cell], label: str = "") -> None:
        self.cells = tuple(cells)
        self.label = label

    def scope(self) -> tuple[Cell, ...]:
        return self.cells

    def propagate(self, domains: Domains) -> bool:
        cells = self.cells
        # 1) 확정값 제거
        changed = True
        while changed:
            changed = False
            for cell in cells:
                dom = domains[cell]
                if len(dom) != 1:
                    continue
                v = next(iter(dom))
                for other in cells:
                    if other is cell or other == cell:
                        continue
                    od = domains[other]
                    if v in od:
                        od.discard(v)
                        if not od:
                            return False
                        changed = True
            # 2) hidden single: 이 묶음에서 값 v가 갈 수 있는 칸이 하나뿐이면 확정
            for v in _values_in(domains, cells):
                spots = [c for c in cells if v in domains[c]]
                if not spots:
                    return False
                if len(spots) == 1 and len(domains[spots[0]]) > 1:
                    domains[spots[0]] = {v}
                    changed = True
        # 3) 비둘기집: 칸 수보다 후보 값 수가 적으면 모순
        if len(_values_in(domains, cells)) < len(cells):
            return False
        return True

    def check(self, assignment: dict[Cell, int]) -> bool:
        seen: set[int] = set()
        for cell in self.cells:
            v = assignment.get(cell)
            if v is None:
                continue
            if v in seen:
                return False
            seen.add(v)
        return True

    def binary_arcs(self) -> list[tuple[Cell, Cell]]:
        arcs: list[tuple[Cell, Cell]] = []
        for a, b in combinations(self.cells, 2):
            arcs.append((a, b))
            arcs.append((b, a))
        return arcs

    def describe(self) -> str:
        return self.label or f"alldiff x{len(self.cells)}"


def _values_in(domains: Domains, cells: Sequence[Cell]) -> set[int]:
    acc: set[int] = set()
    for c in cells:
        acc |= domains[c]
    return acc


# ================================================================= Killer Cage
class KillerCage(Constraint):
    """케이지 안의 값 합이 total. 기본적으로 케이지 내부는 서로 다른 값."""

    name = "killer"

    def __init__(self, cells: Sequence[Cell], total: int, distinct: bool = True) -> None:
        if not cells:
            raise ValueError("빈 케이지는 만들 수 없습니다")
        self.cells = tuple(cells)
        self.total = int(total)
        self.distinct = distinct

    def scope(self) -> tuple[Cell, ...]:
        return self.cells

    def propagate(self, domains: Domains) -> bool:
        cells = self.cells
        # 열거 비용 추정
        budget = 1
        for c in cells:
            budget *= max(len(domains[c]), 1)
            if budget > _ENUM_BUDGET:
                break
        if budget <= _ENUM_BUDGET and len(cells) <= 8:
            return self._propagate_exact(domains)
        return self._propagate_bounds(domains)

    def _propagate_exact(self, domains: Domains) -> bool:
        """모든 실현 가능한 조합을 열거해 지지받지 못하는 값을 제거(완전 필터)."""
        cells = self.cells
        n = len(cells)
        support: list[set[int]] = [set() for _ in range(n)]
        sorted_domains = [sorted(domains[c]) for c in cells]
        suffix_min = [0] * (n + 1)
        suffix_max = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            if not sorted_domains[i]:
                return False
            suffix_min[i] = suffix_min[i + 1] + sorted_domains[i][0]
            suffix_max[i] = suffix_max[i + 1] + sorted_domains[i][-1]

        partial: list[int] = []
        used: set[int] = set()

        def dfs(i: int, remaining: int) -> None:
            if i == n:
                if remaining == 0:
                    for k, v in enumerate(partial):
                        support[k].add(v)
                return
            for v in sorted_domains[i]:
                if self.distinct and v in used:
                    continue
                nxt = remaining - v
                if nxt < suffix_min[i + 1]:
                    break  # 오름차순이므로 이후 값은 더 크다
                if nxt > suffix_max[i + 1]:
                    continue
                partial.append(v)
                used.add(v)
                dfs(i + 1, nxt)
                partial.pop()
                used.discard(v)

        dfs(0, self.total)

        for i, cell in enumerate(cells):
            if not support[i]:
                return False
            if domains[cell] != support[i]:
                domains[cell] = support[i]
        return True

    def _propagate_bounds(self, domains: Domains) -> bool:
        """큰 케이지용 min/max 경계 가지치기."""
        cells = self.cells
        mins = {c: min(domains[c]) for c in cells}
        maxs = {c: max(domains[c]) for c in cells}
        total_min = sum(mins.values())
        total_max = sum(maxs.values())
        if total_min > self.total or total_max < self.total:
            return False
        for c in cells:
            others_min = total_min - mins[c]
            others_max = total_max - maxs[c]
            lo = self.total - others_max
            hi = self.total - others_min
            newdom = {v for v in domains[c] if lo <= v <= hi}
            if not newdom:
                return False
            domains[c] = newdom
        return True

    def check(self, assignment: dict[Cell, int]) -> bool:
        vals = [assignment[c] for c in self.cells if c in assignment]
        if self.distinct and len(set(vals)) != len(vals):
            return False
        s = sum(vals)
        if len(vals) == len(self.cells):
            return s == self.total
        return s < self.total

    def binary_arcs(self) -> list[tuple[Cell, Cell]]:
        if not self.distinct:
            return []
        arcs = []
        for a, b in combinations(self.cells, 2):
            arcs.append((a, b))
            arcs.append((b, a))
        return arcs

    def describe(self) -> str:
        return f"killer sum={self.total} x{len(self.cells)}"


# ================================================================ Thermometer
class Thermometer(Constraint):
    """전구(path[0])에서 시작해 경로를 따라 값이 순증가."""

    name = "thermo"

    def __init__(self, path: Sequence[Cell], strict: bool = True) -> None:
        if len(path) < 2:
            raise ValueError("온도계는 최소 2칸이 필요합니다")
        self.path = tuple(path)
        self.strict = strict
        self._step = 1 if strict else 0

    def scope(self) -> tuple[Cell, ...]:
        return self.path

    def propagate(self, domains: Domains) -> bool:
        path = self.path
        # 정방향: 하한 밀어올리기
        lo = None
        for cell in path:
            dom = domains[cell]
            if not dom:
                return False
            if lo is not None:
                dom = {v for v in dom if v >= lo}
                if not dom:
                    return False
                domains[cell] = dom
            lo = min(dom) + self._step
        # 역방향: 상한 끌어내리기
        hi = None
        for cell in reversed(path):
            dom = domains[cell]
            if hi is not None:
                dom = {v for v in dom if v <= hi}
                if not dom:
                    return False
                domains[cell] = dom
            hi = max(dom) - self._step
        return True

    def check(self, assignment: dict[Cell, int]) -> bool:
        prev_idx = -1
        prev_val = None
        for i, cell in enumerate(self.path):
            v = assignment.get(cell)
            if v is None:
                continue
            if prev_val is not None:
                gap = i - prev_idx
                if self.strict:
                    if v < prev_val + gap:
                        return False
                elif v < prev_val:
                    return False
            prev_idx, prev_val = i, v
        return True

    def describe(self) -> str:
        return f"thermo len={len(self.path)}"


# ======================================================================= Arrow
class Arrow(Constraint):
    """원(circle) 안의 값 = 화살표 경로 칸들의 합."""

    name = "arrow"

    def __init__(self, circle: Cell, path: Sequence[Cell]) -> None:
        if not path:
            raise ValueError("화살표 경로가 비었습니다")
        self.circle = tuple(circle)  # type: ignore[assignment]
        self.path = tuple(path)

    def scope(self) -> tuple[Cell, ...]:
        return (self.circle,) + self.path  # type: ignore[operator]

    def propagate(self, domains: Domains) -> bool:
        circ = domains[self.circle]  # type: ignore[index]
        if not circ:
            return False
        path_min = sum(min(domains[c]) for c in self.path)
        path_max = sum(max(domains[c]) for c in self.path)
        newcirc = {v for v in circ if path_min <= v <= path_max}
        if not newcirc:
            return False
        domains[self.circle] = newcirc  # type: ignore[index]
        cmin, cmax = min(newcirc), max(newcirc)
        for c in self.path:
            others_min = path_min - min(domains[c])
            others_max = path_max - max(domains[c])
            lo = cmin - others_max
            hi = cmax - others_min
            nd = {v for v in domains[c] if lo <= v <= hi}
            if not nd:
                return False
            domains[c] = nd
        return True

    def check(self, assignment: dict[Cell, int]) -> bool:
        cv = assignment.get(self.circle)  # type: ignore[arg-type]
        vals = [assignment[c] for c in self.path if c in assignment]
        if len(vals) == len(self.path):
            if cv is None:
                return True
            return sum(vals) == cv
        if cv is not None and sum(vals) >= cv and len(vals) < len(self.path):
            return False
        return True

    def describe(self) -> str:
        return f"arrow {self.circle}<-sum{len(self.path)}"


# ==================================================================== Sandwich
class Sandwich(Constraint):
    """한 줄에서 low(기본 1)와 high(기본 9) 사이에 낀 숫자들의 합이 total."""

    name = "sandwich"

    def __init__(
        self,
        line: Sequence[Cell],
        total: int,
        low: int = 1,
        high: int = 9,
    ) -> None:
        self.line = tuple(line)
        self.total = int(total)
        self.low = low
        self.high = high

    def scope(self) -> tuple[Cell, ...]:
        return self.line

    def _feasible_pairs(self, domains: Domains) -> list[tuple[int, int]]:
        n = len(self.line)
        pairs: list[tuple[int, int]] = []
        for i in range(n):
            if self.low not in domains[self.line[i]]:
                continue
            for j in range(n):
                if i == j or self.high not in domains[self.line[j]]:
                    continue
                lo_i, hi_i = (i, j) if i < j else (j, i)
                between = self.line[lo_i + 1 : hi_i]
                if not between:
                    if self.total == 0:
                        pairs.append((i, j))
                    continue
                mn = 0
                mx = 0
                ok = True
                for c in between:
                    dom = {v for v in domains[c] if v not in (self.low, self.high)}
                    if not dom:
                        ok = False
                        break
                    mn += min(dom)
                    mx += max(dom)
                if ok and mn <= self.total <= mx:
                    pairs.append((i, j))
        return pairs

    def propagate(self, domains: Domains) -> bool:
        pairs = self._feasible_pairs(domains)
        if not pairs:
            return False
        low_spots = {i for i, _ in pairs}
        high_spots = {j for _, j in pairs}
        for idx, cell in enumerate(self.line):
            if idx not in low_spots and self.low in domains[cell]:
                domains[cell].discard(self.low)
                if not domains[cell]:
                    return False
            if idx not in high_spots and self.high in domains[cell]:
                domains[cell].discard(self.high)
                if not domains[cell]:
                    return False
        # 모든 후보 배치에서 "사이"에 들어가는 칸은 low/high를 가질 수 없다
        always_between: set[int] = set(range(len(self.line)))
        for i, j in pairs:
            lo_i, hi_i = min(i, j), max(i, j)
            always_between &= set(range(lo_i + 1, hi_i))
        for idx in always_between:
            cell = self.line[idx]
            before = len(domains[cell])
            domains[cell] -= {self.low, self.high}
            if not domains[cell]:
                return False
            del before
        return True

    def check(self, assignment: dict[Cell, int]) -> bool:
        vals = [assignment.get(c) for c in self.line]
        if any(v is None for v in vals):
            return True
        i = vals.index(self.low)
        j = vals.index(self.high)
        lo, hi = min(i, j), max(i, j)
        return sum(vals[lo + 1 : hi]) == self.total  # type: ignore[arg-type]

    def describe(self) -> str:
        return f"sandwich sum={self.total}"


# ====================================================================== Parity
class Parity(Constraint):
    """지정한 칸들이 짝수(또는 홀수)만 가질 수 있다."""

    name = "parity"

    def __init__(self, cells: Sequence[Cell], even: bool) -> None:
        self.cells = tuple(cells)
        self.even = even

    def scope(self) -> tuple[Cell, ...]:
        return self.cells

    def propagate(self, domains: Domains) -> bool:
        want = 0 if self.even else 1
        for c in self.cells:
            nd = {v for v in domains[c] if v % 2 == want}
            if not nd:
                return False
            domains[c] = nd
        return True

    def check(self, assignment: dict[Cell, int]) -> bool:
        want = 0 if self.even else 1
        return all(
            assignment[c] % 2 == want for c in self.cells if c in assignment
        )

    def describe(self) -> str:
        return f"{'even' if self.even else 'odd'} x{len(self.cells)}"


# ================================================================ Inequality
class LessThan(Constraint):
    """a < b (부등호 스도쿠용)."""

    name = "lessthan"

    def __init__(self, smaller: Cell, larger: Cell) -> None:
        self.smaller = smaller
        self.larger = larger

    def scope(self) -> tuple[Cell, ...]:
        return (self.smaller, self.larger)

    def propagate(self, domains: Domains) -> bool:
        a, b = domains[self.smaller], domains[self.larger]
        if not a or not b:
            return False
        na = {v for v in a if v < max(b)}
        nb = {v for v in b if v > min(a)}
        if not na or not nb:
            return False
        domains[self.smaller], domains[self.larger] = na, nb
        return True

    def check(self, assignment: dict[Cell, int]) -> bool:
        a = assignment.get(self.smaller)
        b = assignment.get(self.larger)
        if a is None or b is None:
            return True
        return a < b

    def describe(self) -> str:
        return f"{self.smaller}<{self.larger}"


# =============================================================== 표준 제약 생성
def classic_constraints(grid) -> list[Constraint]:
    """행/열/박스 all-different."""
    out: list[Constraint] = []
    for i, unit in enumerate(grid.rows):
        out.append(AllDifferent(unit, f"row{i}"))
    for i, unit in enumerate(grid.cols):
        out.append(AllDifferent(unit, f"col{i}"))
    for i, unit in enumerate(grid.boxes):
        out.append(AllDifferent(unit, f"box{i}"))
    return out


def diagonal_constraints(grid) -> list[Constraint]:
    """대각선 스도쿠(Sudoku X)."""
    return [
        AllDifferent(grid.main_diagonal(), "diag-main"),
        AllDifferent(grid.anti_diagonal(), "diag-anti"),
    ]
