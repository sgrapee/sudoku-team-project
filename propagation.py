"""제약 전파: 전방 검사(FC), AC-3, hidden single, naked pair.

전파 강도를 4단계로 나눠 두었다. ④ 실험 담당이 이 축으로 노드 수 감소를
측정한다.

    "none" : 전파 없음. 할당 시 제약 위반만 검사(순수 백트래킹)
    "fc"   : 전방 검사. 방금 확정한 값을 이웃 도메인에서 1회 제거
    "ac3"  : 이진 아크 일관성 + 전역 제약 전파를 고정점까지
    "full" : ac3 + hidden single + naked pair 를 고정점까지
"""

from __future__ import annotations

from collections import deque
from itertools import combinations

from .core import Cell, Domains
from .model import Model

LEVELS = ("none", "fc", "ac3", "full")


class PropagationStats:
    """전파 호출 횟수 계측(실험용)."""

    __slots__ = ("revisions", "eliminations", "calls")

    def __init__(self) -> None:
        self.revisions = 0
        self.eliminations = 0
        self.calls = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "propagation_calls": self.calls,
            "arc_revisions": self.revisions,
            "value_eliminations": self.eliminations,
        }


# --------------------------------------------------------------- 전방 검사
def forward_check(
    model: Model, domains: Domains, cell: Cell, value: int, stats: PropagationStats
) -> bool:
    """cell=value 확정 직후, 이웃에서 value를 1회 제거하고 전역 제약을 1회 돌린다."""
    stats.calls += 1
    for nb in model.neighbors[cell]:
        dom = domains[nb]
        if value in dom:
            dom.discard(value)
            stats.eliminations += 1
            if not dom:
                return False
    for con in model.global_of.get(cell, ()):
        if not con.propagate(domains):
            return False
    return True


# ------------------------------------------------------------------- AC-3
def ac3(
    model: Model,
    domains: Domains,
    stats: PropagationStats,
    queue: deque[Cell] | None = None,
) -> bool:
    """이진 != 아크 일관성 + 전역 제약 전파를 고정점까지 반복.

    큐에는 '도메인이 변한 칸'을 넣는다. 그 칸의 이웃과, 그 칸이 속한
    전역 제약을 다시 검사한다.
    """
    stats.calls += 1
    if queue is None:
        queue = deque(model.grid.cells)
    in_queue = set(queue)

    while queue:
        cell = queue.popleft()
        in_queue.discard(cell)
        dom = domains[cell]
        if not dom:
            return False

        stats.revisions += 1

        # (1) 확정값이면 이웃에서 제거
        if len(dom) == 1:
            v = next(iter(dom))
            for nb in model.neighbors[cell]:
                nd = domains[nb]
                if v in nd:
                    nd.discard(v)
                    stats.eliminations += 1
                    if not nd:
                        return False
                    if nb not in in_queue:
                        queue.append(nb)
                        in_queue.add(nb)

        # (2) 이 칸이 속한 전역 제약 전파
        for con in model.global_of.get(cell, ()):
            before = {c: len(domains[c]) for c in con.scope()}
            if not con.propagate(domains):
                return False
            for c in con.scope():
                if len(domains[c]) != before[c]:
                    stats.eliminations += before[c] - len(domains[c])
                    if c not in in_queue:
                        queue.append(c)
                        in_queue.add(c)

        # (3) 이 칸이 속한 유닛의 hidden single
        for unit in model.units_of.get(cell, ()):
            if not _hidden_singles_unit(domains, unit, model.grid.values, queue, in_queue, stats):
                return False

    return True


def _hidden_singles_unit(
    domains: Domains,
    unit: list[Cell],
    values: tuple[int, ...],
    queue: deque[Cell],
    in_queue: set[Cell],
    stats: PropagationStats,
) -> bool:
    for v in values:
        spots = [c for c in unit if v in domains[c]]
        if not spots:
            return False
        if len(spots) == 1 and len(domains[spots[0]]) > 1:
            stats.eliminations += len(domains[spots[0]]) - 1
            domains[spots[0]] = {v}
            if spots[0] not in in_queue:
                queue.append(spots[0])
                in_queue.add(spots[0])
    return True


# ------------------------------------------------------- naked pair / subset
def naked_subsets(model: Model, domains: Domains, stats: PropagationStats, max_k: int = 2) -> bool:
    """유닛 안에서 k개 칸의 후보 합집합 크기가 k면, 그 값들을 나머지 칸에서 제거."""
    changed = False
    for unit in model.units:
        open_cells = [c for c in unit if len(domains[c]) > 1]
        for k in range(2, max_k + 1):
            if len(open_cells) <= k:
                continue
            for combo in combinations(open_cells, k):
                union: set[int] = set()
                for c in combo:
                    union |= domains[c]
                    if len(union) > k:
                        break
                if len(union) != k:
                    continue
                for other in unit:
                    if other in combo:
                        continue
                    inter = domains[other] & union
                    if inter:
                        domains[other] -= union
                        stats.eliminations += len(inter)
                        changed = True
                        if not domains[other]:
                            return False
    if changed:
        return ac3(model, domains, stats)
    return True


# ------------------------------------------------------------------ 통합 진입점
def propagate(
    model: Model,
    domains: Domains,
    level: str,
    stats: PropagationStats,
    changed_cell: Cell | None = None,
    changed_value: int | None = None,
) -> bool:
    """level에 따라 적절한 전파를 수행한다."""
    if level == "none":
        return True
    if level == "fc":
        if changed_cell is None:
            # 초기화 시점: 모든 확정 칸에 대해 1회씩
            for cell, dom in list(domains.items()):
                if len(dom) == 1:
                    if not forward_check(model, domains, cell, next(iter(dom)), stats):
                        return False
            return True
        return forward_check(model, domains, changed_cell, changed_value, stats)  # type: ignore[arg-type]

    queue: deque[Cell] | None = None
    if changed_cell is not None:
        queue = deque([changed_cell])
    if not ac3(model, domains, stats, queue):
        return False
    if level == "full":
        if not naked_subsets(model, domains, stats, max_k=3):
            return False
    return True


def initial_propagate(model: Model, domains: Domains, level: str, stats: PropagationStats) -> bool:
    """탐색 시작 전 1회 전파(단서 반영)."""
    if level == "none":
        return True
    if level == "fc":
        return propagate(model, domains, "fc", stats)
    return propagate(model, domains, level, stats)
