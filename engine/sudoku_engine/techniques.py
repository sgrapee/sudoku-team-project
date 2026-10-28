"""사람이 쓰는 풀이 기법을 계층적으로 구현한다.

용도
----
1. 난이도 판정 — 어떤 기법까지 동원해야 풀리는지로 등급을 매긴다(④ 생성기가 사용)
2. 힌트 생성 — 다음에 적용 가능한 기법 하나와 그 근거를 자연어로 설명(⑤ 데모 UI가 사용)

백트래킹 solver와는 목적이 다르다. solver는 '푸는 것'이 목표이고,
여기는 '어떻게 풀리는지 설명하는 것'이 목표다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from .core import Cell, Domains, count_unsolved, partial_assignment, solved_assignment
from .model import Model

# 기법 난이도 등급 (숫자가 클수록 어려움)
TECHNIQUE_TIER: dict[str, int] = {
    "naked_single": 1,
    "hidden_single": 1,
    "naked_pair": 2,
    "pointing": 2,
    "claiming": 2,
    "hidden_pair": 3,
    "naked_triple": 3,
    "x_wing": 4,
    "hidden_triple": 4,
    "xy_wing": 4,
    "swordfish": 5,
    "constraint_propagation": 2,  # 변형 제약(킬러/온도계 등) 전파
}

TIER_NAMES = {
    0: "완성", 1: "쉬움", 2: "보통", 3: "어려움",
    4: "매우 어려움", 5: "최상급", 6: "논리 불가(추측 필요)",
}
UNSOLVABLE_TIER = 6


@dataclass
class Step:
    """풀이 한 단계의 기록."""

    technique: str
    cell: Cell | None = None
    value: int | None = None
    eliminated: list[tuple[Cell, int]] = field(default_factory=list)
    explanation: str = ""

    @property
    def tier(self) -> int:
        return TECHNIQUE_TIER.get(self.technique, 3)

    def __str__(self) -> str:  # pragma: no cover
        return self.explanation or f"{self.technique} {self.cell}={self.value}"


@dataclass
class LogicalResult:
    solved: bool
    steps: list[Step]
    domains: Domains
    assignment: dict[Cell, int]

    @property
    def hardest_tier(self) -> int:
        return max((s.tier for s in self.steps), default=0)

    def technique_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.steps:
            out[s.technique] = out.get(s.technique, 0) + 1
        return out


# ============================================================ 개별 기법들
def _rc(cell: Cell) -> str:
    return f"r{cell[0] + 1}c{cell[1] + 1}"


def naked_single(model: Model, domains: Domains) -> Step | None:
    """후보가 하나뿐인 칸 → 그 값으로 확정."""
    for cell in model.grid.cells:
        dom = domains[cell]
        if len(dom) == 1:
            v = next(iter(dom))
            # 이미 반영됐는지: 이웃에 v가 남아 있으면 아직 처리 전
            targets = [(nb, v) for nb in model.neighbors[cell] if v in domains[nb]]
            if targets:
                return Step(
                    "naked_single", cell, v, targets,
                    f"{_rc(cell)}의 후보가 {v} 하나뿐이므로 {v}로 확정하고, "
                    f"같은 줄·박스의 {len(targets)}칸에서 {v}를 지웁니다.",
                )
    return None


def hidden_single(model: Model, domains: Domains) -> Step | None:
    """한 유닛에서 어떤 값이 들어갈 수 있는 칸이 하나뿐 → 그 칸으로 확정."""
    for unit in model.units:
        for v in model.grid.values:
            spots = [c for c in unit if v in domains[c]]
            if len(spots) == 1 and len(domains[spots[0]]) > 1:
                cell = spots[0]
                removed = [(cell, x) for x in domains[cell] if x != v]
                return Step(
                    "hidden_single", cell, v, removed,
                    f"이 줄(또는 박스)에서 {v}가 들어갈 수 있는 칸은 {_rc(cell)}뿐이므로 "
                    f"{v}로 확정합니다.",
                )
    return None


def naked_subset(model: Model, domains: Domains, k: int) -> Step | None:
    """k개 칸의 후보 합집합이 k개 → 그 값들을 유닛의 나머지 칸에서 제거."""
    name = {2: "naked_pair", 3: "naked_triple"}[k]
    for unit in model.units:
        open_cells = [c for c in unit if len(domains[c]) > 1]
        if len(open_cells) <= k:
            continue
        for combo in combinations(open_cells, k):
            union: set[int] = set()
            for c in combo:
                union |= domains[c]
            if len(union) != k:
                continue
            removed = [
                (o, v)
                for o in unit
                if o not in combo
                for v in sorted(domains[o] & union)
            ]
            if removed:
                names = ", ".join(_rc(c) for c in combo)
                vals = ",".join(map(str, sorted(union)))
                return Step(
                    name, None, None, removed,
                    f"{names} 세 칸이 {{{vals}}}만 가질 수 있으므로, 같은 묶음의 다른 칸에서 "
                    f"이 값들을 제거합니다." if k == 3 else
                    f"{names} 두 칸이 {{{vals}}}만 가질 수 있으므로, 같은 묶음의 다른 칸에서 "
                    f"이 값들을 제거합니다.",
                )
    return None


def hidden_subset(model: Model, domains: Domains, k: int) -> Step | None:
    """k개 값이 같은 k개 칸에만 나타남 → 그 칸들을 그 값들로 제한."""
    name = {2: "hidden_pair", 3: "hidden_triple"}[k]
    for unit in model.units:
        spots = {
            v: [c for c in unit if v in domains[c]] for v in model.grid.values
        }
        cands = [v for v, s in spots.items() if 2 <= len(s) <= k]
        for combo in combinations(cands, k):
            cells: set[Cell] = set()
            for v in combo:
                cells |= set(spots[v])
            if len(cells) != k:
                continue
            keep = set(combo)
            removed = [
                (c, v) for c in cells for v in sorted(domains[c] - keep)
            ]
            if removed:
                vals = ",".join(map(str, sorted(combo)))
                names = ", ".join(_rc(c) for c in sorted(cells))
                return Step(
                    name, None, None, removed,
                    f"{{{vals}}}가 이 묶음에서 {names}에만 들어갈 수 있으므로, "
                    f"그 칸들의 다른 후보를 제거합니다.",
                )
    return None


def pointing_and_claiming(model: Model, domains: Domains) -> Step | None:
    """박스↔줄 상호작용.

    pointing : 박스 안에서 v의 후보가 한 행(열)에만 있으면, 그 행(열)의 박스 밖에서 v 제거
    claiming : 한 행(열)에서 v의 후보가 한 박스에만 있으면, 그 박스의 행(열) 밖에서 v 제거
    """
    grid = model.grid
    for v in grid.values:
        # pointing
        for box in grid.boxes:
            spots = [c for c in box if v in domains[c]]
            if len(spots) < 2:
                continue
            rows = {r for r, _ in spots}
            cols = {c for _, c in spots}
            if len(rows) == 1:
                r = next(iter(rows))
                removed = [
                    (c, v) for c in grid.rows[r] if c not in box and v in domains[c]
                ]
                if removed:
                    return Step(
                        "pointing", None, v, removed,
                        f"이 박스에서 {v}는 {r + 1}행에만 들어갈 수 있으므로, "
                        f"같은 행의 박스 바깥 칸에서 {v}를 제거합니다.",
                    )
            if len(cols) == 1:
                c0 = next(iter(cols))
                removed = [
                    (c, v) for c in grid.cols[c0] if c not in box and v in domains[c]
                ]
                if removed:
                    return Step(
                        "pointing", None, v, removed,
                        f"이 박스에서 {v}는 {c0 + 1}열에만 들어갈 수 있으므로, "
                        f"같은 열의 박스 바깥 칸에서 {v}를 제거합니다.",
                    )
        # claiming
        for line_kind, lines in (("행", grid.rows), ("열", grid.cols)):
            for idx, line in enumerate(lines):
                spots = [c for c in line if v in domains[c]]
                if len(spots) < 2:
                    continue
                boxes = {grid.box_index(c) for c in spots}
                if len(boxes) != 1:
                    continue
                box = grid.boxes[next(iter(boxes))]
                removed = [
                    (c, v) for c in box if c not in line and v in domains[c]
                ]
                if removed:
                    return Step(
                        "claiming", None, v, removed,
                        f"{idx + 1}{line_kind}에서 {v}는 한 박스 안에만 들어갈 수 있으므로, "
                        f"그 박스의 나머지 칸에서 {v}를 제거합니다.",
                    )
    return None


def x_wing(model: Model, domains: Domains) -> Step | None:
    """어떤 값이 두 행에서 정확히 같은 두 열에만 후보로 남으면,
    그 두 열의 다른 행에서 그 값을 제거한다(열 방향도 동일)."""
    grid = model.grid
    for v in grid.values:
        # 행 기반
        candidates: dict[tuple[int, int], list[int]] = {}
        for r, row in enumerate(grid.rows):
            cols = [c for (_, c) in [x for x in row if v in domains[x]]]
            if len(cols) == 2:
                candidates.setdefault((cols[0], cols[1]), []).append(r)
        for (c1, c2), rows in candidates.items():
            if len(rows) < 2:
                continue
            r1, r2 = rows[0], rows[1]
            removed = [
                ((r, c), v)
                for c in (c1, c2)
                for r in range(grid.size)
                if r not in (r1, r2) and v in domains[(r, c)]
            ]
            if removed:
                return Step(
                    "x_wing", None, v, removed,
                    f"{r1 + 1}행과 {r2 + 1}행에서 {v}가 {c1 + 1}열·{c2 + 1}열에만 "
                    f"들어갈 수 있으므로(X-Wing), 두 열의 다른 행에서 {v}를 제거합니다.",
                )
        # 열 기반
        candidates = {}
        for c, col in enumerate(grid.cols):
            rows_ = [r for (r, _) in [x for x in col if v in domains[x]]]
            if len(rows_) == 2:
                candidates.setdefault((rows_[0], rows_[1]), []).append(c)
        for (r1, r2), cols_ in candidates.items():
            if len(cols_) < 2:
                continue
            c1, c2 = cols_[0], cols_[1]
            removed = [
                ((r, c), v)
                for r in (r1, r2)
                for c in range(grid.size)
                if c not in (c1, c2) and v in domains[(r, c)]
            ]
            if removed:
                return Step(
                    "x_wing", None, v, removed,
                    f"{c1 + 1}열과 {c2 + 1}열에서 {v}가 {r1 + 1}행·{r2 + 1}행에만 "
                    f"들어갈 수 있으므로(X-Wing), 두 행의 다른 열에서 {v}를 제거합니다.",
                )
    return None


def variant_propagation(model: Model, domains: Domains) -> Step | None:
    """킬러/온도계/화살표 등 변형 제약의 전파를 한 단계로 취급한다.

    사람이 쓰는 기법 목록에는 없지만, 변형 스도쿠에서는 이것이 핵심 추론이므로
    난이도 계산과 힌트에 포함시킨다.
    """
    for con in model.global_constraints:
        snapshot = {c: set(domains[c]) for c in con.scope()}
        if not con.propagate(domains):
            # 모순 → 되돌리고 실패로 처리
            for c, d in snapshot.items():
                domains[c] = d
            return None
        removed = [
            (c, v) for c, old in snapshot.items() for v in sorted(old - domains[c])
        ]
        if removed:
            return Step(
                "constraint_propagation", None, None, removed,
                f"{con.describe()} 제약으로 후보 {len(removed)}개를 제거합니다.",
            )
    return None


def xy_wing(model: Model, domains: Domains) -> Step | None:
    """축(pivot) {X,Y}, 집게(pincer) {X,Z}와 {Y,Z}가 축을 볼 때,
    두 집게를 동시에 보는 칸에서 Z를 제거한다."""
    two = [c for c in model.grid.cells if len(domains[c]) == 2]
    two_set = set(two)
    for pivot in two:
        x, y = sorted(domains[pivot])
        seen = [c for c in model.neighbors[pivot] if c in two_set]
        for a in seen:
            da = domains[a]
            if x not in da:
                continue
            z_a = next(iter(da - {x}), None)
            if z_a is None or z_a == y:
                continue
            for b in seen:
                if b == a:
                    continue
                db = domains[b]
                if y not in db or z_a not in db:
                    continue
                if db != {y, z_a}:
                    continue
                targets = (model.neighbors[a] & model.neighbors[b]) - {pivot, a, b}
                removed = [(c, z_a) for c in sorted(targets) if z_a in domains[c]]
                if removed:
                    return Step(
                        "xy_wing", None, z_a, removed,
                        f"{_rc(pivot)}({x},{y})를 축으로 {_rc(a)}·{_rc(b)}가 집게를 이루므로"
                        f"(XY-Wing), 두 집게를 동시에 보는 칸에서 {z_a}를 제거합니다.",
                    )
    return None


def swordfish(model: Model, domains: Domains) -> Step | None:
    """X-Wing의 3줄 확장. 세 행에서 값 v의 후보 열이 같은 세 열 안에 갇히면,
    그 세 열의 다른 행에서 v를 제거한다(열 방향도 동일)."""
    grid = model.grid
    for v in grid.values:
        for axis in ("row", "col"):
            lines = grid.rows if axis == "row" else grid.cols
            spots: dict[int, set[int]] = {}
            for i, line in enumerate(lines):
                idxs = {
                    (c if axis == "row" else r)
                    for (r, c) in line
                    if v in domains[(r, c)]
                }
                if 2 <= len(idxs) <= 3:
                    spots[i] = idxs
            for trio in combinations(sorted(spots), 3):
                union: set[int] = set()
                for i in trio:
                    union |= spots[i]
                if len(union) != 3:
                    continue
                removed = []
                for j in sorted(union):
                    for i in range(grid.size):
                        if i in trio:
                            continue
                        cell = (i, j) if axis == "row" else (j, i)
                        if v in domains[cell]:
                            removed.append((cell, v))
                if removed:
                    unit = "행" if axis == "row" else "열"
                    other = "열" if axis == "row" else "행"
                    a = ", ".join(str(i + 1) for i in trio)
                    b = ", ".join(str(j + 1) for j in sorted(union))
                    return Step(
                        "swordfish", None, v, removed,
                        f"{a}{unit}에서 {v}가 {b}{other}에만 들어갈 수 있으므로(Swordfish), "
                        f"그 {other}들의 다른 {unit}에서 {v}를 제거합니다.",
                    )
    return None


# ============================================================ 기법 파이프라인
TECHNIQUE_PIPELINE = [
    ("naked_single", lambda m, d: naked_single(m, d)),
    ("hidden_single", lambda m, d: hidden_single(m, d)),
    ("constraint_propagation", lambda m, d: variant_propagation(m, d)),
    ("naked_pair", lambda m, d: naked_subset(m, d, 2)),
    ("pointing/claiming", lambda m, d: pointing_and_claiming(m, d)),
    ("hidden_pair", lambda m, d: hidden_subset(m, d, 2)),
    ("naked_triple", lambda m, d: naked_subset(m, d, 3)),
    ("x_wing", lambda m, d: x_wing(m, d)),
    ("xy_wing", lambda m, d: xy_wing(m, d)),
    ("hidden_triple", lambda m, d: hidden_subset(m, d, 3)),
    ("swordfish", lambda m, d: swordfish(m, d)),
]


def _apply(step: Step, domains: Domains) -> bool:
    """스텝의 제거/확정을 도메인에 반영. 모순이면 False."""
    if step.cell is not None and step.value is not None:
        domains[step.cell] = {step.value}
    for cell, v in step.eliminated:
        domains[cell].discard(v)
        if not domains[cell]:
            return False
    return True


def seed_domains(model: Model) -> Domains | None:
    """단서로부터의 기본 후보 제거(설정 단계).

    이 과정은 '기법'이 아니라 준비 작업이므로 난이도 집계에서 제외한다.
    이걸 빼먹으면 단서 개수가 그대로 naked_single 횟수로 잡혀 등급이 왜곡된다.
    """
    domains = model.initial_domains()
    changed = True
    while changed:
        changed = False
        for cell, v in model.givens.items():
            for nb in model.neighbors[cell]:
                if v in domains[nb]:
                    domains[nb].discard(v)
                    if not domains[nb]:
                        return None
                    changed = False  # 단서 제거는 1회면 충분
    return domains


def solve_logically(
    model: Model, max_steps: int = 500, allowed_tier: int = 5
) -> LogicalResult:
    """사람 기법만으로 최대한 풀어본다. 추측(백트래킹)은 쓰지 않는다."""
    seeded = seed_domains(model)
    if seeded is None:
        empty = model.initial_domains()
        return LogicalResult(False, [], empty, {})
    domains = seeded
    steps: list[Step] = []

    for _ in range(max_steps):
        if count_unsolved(domains) == 0:
            break
        progressed = False
        for name, fn in TECHNIQUE_PIPELINE:
            step = fn(model, domains)
            if step is None:
                continue
            if step.tier > allowed_tier:
                continue
            if not _apply(step, domains):
                return LogicalResult(False, steps, domains, partial_assignment(domains))
            steps.append(step)
            progressed = True
            break
        if not progressed:
            break

    assignment = solved_assignment(domains)
    solved = assignment is not None and model.is_valid(assignment)
    return LogicalResult(
        solved, steps, domains, assignment or partial_assignment(domains)
    )


def rate_difficulty(model: Model) -> dict:
    """난이도 등급과 근거를 돌려준다.

    반환 예:
        {"level": 2, "label": "보통", "solvable_by_logic": True,
         "techniques": {"naked_single": 30, ...}, "steps": 41, "score": 68}
    """
    result = solve_logically(model)
    counts = result.technique_counts()
    if not result.solved:
        return {
            "level": UNSOLVABLE_TIER,
            "label": TIER_NAMES[UNSOLVABLE_TIER],
            "solvable_by_logic": False,
            "techniques": counts,
            "steps": len(result.steps),
            "score": 999,
            "remaining": count_unsolved(result.domains),
        }
    level = result.hardest_tier
    score = sum(TECHNIQUE_TIER.get(t, 3) ** 2 * n for t, n in counts.items())
    return {
        "level": level,
        "label": TIER_NAMES.get(level, "보통"),
        "solvable_by_logic": True,
        "techniques": counts,
        "steps": len(result.steps),
        "score": score,
        "remaining": 0,
    }


def next_hint(model: Model, current: dict[Cell, int] | None = None) -> Step | None:
    """현재 상태에서 적용 가능한 가장 쉬운 기법 하나를 돌려준다(⑤ 데모 UI용).

    current 에는 사용자가 지금까지 채워 넣은 칸을 넘긴다.
    """
    givens = dict(model.givens)
    if current:
        givens.update(current)
    probe = Model(model.grid, [], givens, include_classic=False)
    probe.constraints = list(model.constraints)
    probe._build_index()

    domains = seed_domains(probe)
    if domains is None:
        return None
    for _name, fn in TECHNIQUE_PIPELINE:
        step = fn(probe, domains)
        if step is not None:
            return step
    return None
