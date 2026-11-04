"""벤치마크 하네스 + 자체 검증용 퍼즐 생성기.

생성기 본체는 ④ 담당이 만들지만, 엔진을 혼자 검증하려면 퍼즐이 필요하므로
최소 기능(유일해 보장 dig)만 여기에 둔다. ④는 has_unique_solution()만
가져다 쓰면 되고, 이 파일의 생성기를 대체해도 무방하다.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import asdict

from .constraints import Constraint
from .core import Cell, Grid
from .model import Model
from .solver import Solver, SolverConfig, count_solutions, solve


# ------------------------------------------------------------------ 생성기
def random_complete_grid(grid: Grid | None = None, seed: int | None = None) -> dict[Cell, int]:
    """무작위 완성 격자 하나를 만든다."""
    grid = grid or Grid()
    model = Model(grid)
    cfg = SolverConfig(var_order="mrv", val_order="random", propagation="ac3", seed=seed)
    result = Solver(model, cfg).solve()
    if result.solution is None:  # pragma: no cover
        raise RuntimeError("완성 격자 생성 실패")
    return result.solution


def dig_puzzle(
    solution: dict[Cell, int],
    grid: Grid | None = None,
    constraints: list[Constraint] | None = None,
    target_givens: int = 26,
    seed: int | None = None,
    symmetric: bool = False,
) -> dict[Cell, int]:
    """완성 해에서 칸을 지우되, 유일해가 유지되는 동안만 지운다."""
    grid = grid or Grid()
    rnd = random.Random(seed)
    givens = dict(solution)
    order = list(grid.cells)
    rnd.shuffle(order)

    for cell in order:
        if len(givens) <= target_givens:
            break
        if cell not in givens:
            continue
        pair = (grid.size - 1 - cell[0], grid.size - 1 - cell[1])
        removed = [cell] + ([pair] if symmetric and pair in givens and pair != cell else [])
        backup = {c: givens[c] for c in removed}
        for c in removed:
            givens.pop(c, None)
        probe = Model(grid, constraints, givens)
        if count_solutions(probe, limit=2) != 1:
            givens.update(backup)
    return givens


def generate_puzzle(
    target_givens: int = 26,
    constraints: list[Constraint] | None = None,
    seed: int | None = None,
    symmetric: bool = False,
) -> tuple[dict[Cell, int], dict[Cell, int]]:
    """(퍼즐 단서, 정답) 쌍을 만든다."""
    grid = Grid()
    sol = random_complete_grid(grid, seed=seed)
    puz = dig_puzzle(sol, grid, constraints, target_givens, seed=seed, symmetric=symmetric)
    return puz, sol


# ---------------------------------------------------------------- 벤치마크
def run_configs(
    puzzles: list[str | dict[Cell, int]],
    configs: list[SolverConfig],
    constraints: list[Constraint] | None = None,
    time_limit: float = 10.0,
) -> list[dict]:
    """설정별로 퍼즐 묶음을 풀고 집계 통계를 돌려준다.

    주의: 설정마다 푼 퍼즐 집합이 다르면 median 비교가 생존 편향에 걸린다.
    common_* 열은 '모든 설정이 푼 퍼즐'만 대상으로 다시 집계한 값이므로,
    설정 간 비교는 반드시 이 열로 해야 한다.
    """
    grid = Grid()
    raw: dict[str, dict[int, tuple[int, float]]] = {}
    meta: list[dict] = []

    for cfg in configs:
        cfg.time_limit = time_limit
        per_puzzle: dict[int, tuple[int, float]] = {}
        timeouts = 0
        for i, p in enumerate(puzzles):
            model = Model(grid, constraints)
            if isinstance(p, str):
                model.load_puzzle(p)
            else:
                model.set_givens(p)
            res = solve(model, cfg)
            if res.solved:
                per_puzzle[i] = (res.stats.branch_nodes, res.stats.elapsed)
            if res.stats.timed_out:
                timeouts += 1
        raw[cfg.label()] = per_puzzle
        meta.append({"config": cfg.label(), "timeouts": timeouts})

    common = set(range(len(puzzles)))
    for per_puzzle in raw.values():
        common &= set(per_puzzle)

    rows: list[dict] = []
    for info in meta:
        label = info["config"]
        per_puzzle = raw[label]
        all_nodes = [n for n, _ in per_puzzle.values()]
        all_times = [t for _, t in per_puzzle.values()]
        c_nodes = [per_puzzle[i][0] for i in sorted(common)]
        c_times = [per_puzzle[i][1] for i in sorted(common)]
        rows.append(
            {
                "config": label,
                "solved": f"{len(per_puzzle)}/{len(puzzles)}",
                "timeouts": info["timeouts"],
                "common_median_branch": int(statistics.median(c_nodes)) if c_nodes else None,
                "common_mean_branch": round(statistics.mean(c_nodes), 1) if c_nodes else None,
                "common_median_ms": round(statistics.median(c_times) * 1000, 2) if c_times else None,
                "all_median_branch": int(statistics.median(all_nodes)) if all_nodes else None,
                "all_max_branch": max(all_nodes) if all_nodes else None,
            }
        )
    rows.append({"config": f"(공통 퍼즐 {len(common)}개 기준)"})
    return rows


def format_table(rows: list[dict]) -> str:
    """마크다운 표로 출력(보고서에 그대로 붙일 수 있게)."""
    if not rows:
        return "(결과 없음)"
    headers = list(rows[0].keys())
    widths = [
        max(len(h), max(len(str(r.get(h, ""))) for r in rows)) for h in headers
    ]
    line = "| " + " | ".join(h.ljust(w) for h, w in zip(headers, widths)) + " |"
    sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    body = [
        "| " + " | ".join(str(r.get(h, "")).ljust(w) for h, w in zip(headers, widths)) + " |"
        for r in rows
    ]
    return "\n".join([line, sep] + body)


DEFAULT_CONFIGS = [
    SolverConfig(var_order="static", val_order="asc", propagation="none"),
    SolverConfig(var_order="static", val_order="asc", propagation="fc"),
    SolverConfig(var_order="mrv", val_order="asc", propagation="fc"),
    SolverConfig(var_order="mrv_degree", val_order="asc", propagation="fc"),
    SolverConfig(var_order="mrv_degree", val_order="lcv", propagation="fc"),
    SolverConfig(var_order="static", val_order="asc", propagation="ac3"),
    SolverConfig(var_order="mrv", val_order="asc", propagation="ac3"),
    SolverConfig(var_order="mrv_degree", val_order="lcv", propagation="ac3"),
    SolverConfig(var_order="mrv_degree", val_order="lcv", propagation="full"),
]
