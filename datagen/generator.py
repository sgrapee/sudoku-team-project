"""④-A 퍼즐 생성기 — 클래식 (A1) + 난이도 구간 (A3) + 변형 (A2).

완성판 생성 → (변형) 정답에서 제약 역산 → 유일해를 유지하며 칸 지우기 → 난이도 판정 → jsonl 레코드.

출력: puzzles/{variant}_{tier}.jsonl, 한 줄에 퍼즐 하나
  {"id", "variant", "spec"(spec.py 스키마), "solution"(81자), "givens"(단서 수),
   "difficulty"{"tier", "tier_label", "level", "label", "score", "solvable_by_logic", "techniques"},
   "seed", "meta"{"target_givens", "symmetric", "gen_ms"}}

사용 예
-------
# seed 0~9 클래식 퍼즐 10개를 한 파일로
python datagen/generator.py --count 10 --out puzzles/classic_raw.jsonl

# 온도계 퍼즐을 난이도 구간별로 25개씩 → puzzles/thermo_{tier}.jsonl
python datagen/generator.py --variant thermo --per-tier 25 --out-dir puzzles
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from sudoku_engine import Grid, Model, Solver, SolverConfig, has_unique_solution  # noqa: E402
from sudoku_engine.core import Cell  # noqa: E402
from sudoku_engine.spec import load_spec  # noqa: E402
from sudoku_engine.techniques import TECHNIQUE_TIER, rate_difficulty  # noqa: E402

# 난이도 구간 (A3).
# rate_difficulty의 level(= 풀이에 필요한 가장 어려운 기법의 등급)을 기준으로 나눈다.
# score는 구간끼리 겹치므로 구간 안의 정렬에만 쓴다 (클래식 400개 샘플: L1 33~69, L2 52~81, L4 72~124).
# level 6(엔진 기법만으로 못 풂)은 힌트를 끝까지 줄 수 없어 expert로 따로 둔다.
# 변형은 medium·hard가 드물어(hard 0~5%) 둘을 medium 하나로 합친 3구간을 쓴다.
TIERS = ("easy", "medium", "hard", "expert")
VARIANT_TIERS = ("easy", "medium", "expert")
TIER_LABELS = {"easy": "쉬움", "medium": "보통", "hard": "어려움", "expert": "추측 필요"}
VARIANT_TIER_LABELS = {**TIER_LABELS, "medium": "보통·어려움"}

# 변형별 구성 제약과 기본 목표 단서 수
VARIANTS: dict[str, list[str]] = {
    "classic": ["classic"],
    "diagonal": ["diagonal"],
    "thermo": ["thermo"],
    "arrow": ["arrow"],
    "mixed": ["diagonal", "thermo", "arrow"],
}
DEFAULT_GIVENS = {"classic": 24, "diagonal": 22, "thermo": 20, "arrow": 20, "mixed": 16}

N_THERMOS = 4
N_ARROWS = 4
PROBE_TIME_LIMIT = 10.0  # 칸 하나 지울 때 유일해 검사 제한 시간(초)

NEIGHBORS8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def tier_level(rating: dict) -> int:
    """구간 판정용 level. 엔진은 변형 제약 전파(constraint_propagation)를 2등급으로 매겨
    변형 퍼즐은 single만으로 풀려도 level 2가 된다. 온도계·화살표 범위 좁히기는
    single 수준의 추론이므로 구간 판정에서는 1등급으로 본다. 클래식은 level과 같다."""
    if not rating["solvable_by_logic"]:
        return rating["level"]
    tiers = [TECHNIQUE_TIER.get(t, 3) for t in rating["techniques"] if t != "constraint_propagation"]
    return max(tiers, default=1)


def tier_of(level: int, merged: bool = False) -> str:
    """1 → easy, 2~3 → medium, 4~5 → hard, 6(논리 불가) → expert.
    merged=True(변형)면 2~5를 모두 medium으로 본다."""
    if level <= 1:
        return "easy"
    if level <= 3:
        return "medium"
    if level <= 5:
        return "medium" if merged else "hard"
    return "expert"


def tiers_for(variant: str) -> tuple[str, ...]:
    return TIERS if variant == "classic" else VARIANT_TIERS


# ------------------------------------------------------------ 제약 역산 (A2)
def _adjacent(cell: Cell, grid: Grid) -> list[Cell]:
    r, c = cell
    return [(r + dr, c + dc) for dr, dc in NEIGHBORS8
            if 0 <= r + dr < grid.size and 0 <= c + dc < grid.size]


def derive_thermos(solution: dict[Cell, int], grid: Grid, rnd: random.Random,
                   used: set[Cell], n: int = N_THERMOS) -> list[dict]:
    """정답에서 값이 순증가하는 인접 경로(3~6칸)를 찾아 온도계로 만든다."""
    out = []
    starts = sorted(grid.cells, key=lambda c: (solution[c], rnd.random()))
    for start in starts:
        if len(out) >= n:
            break
        if start in used or solution[start] > 4:
            continue
        want = rnd.randint(3, 6)
        path = [start]
        while len(path) < want:
            nxt = [c for c in _adjacent(path[-1], grid)
                   if c not in used and c not in path and solution[c] > solution[path[-1]]]
            if not nxt:
                break
            path.append(rnd.choice(nxt))
        if len(path) >= 3:
            used.update(path)
            out.append({"type": "thermo", "path": [list(c) for c in path]})
    return out


def derive_arrows(solution: dict[Cell, int], grid: Grid, rnd: random.Random,
                  used: set[Cell], n: int = N_ARROWS) -> list[dict]:
    """원 = 경로 합이 되는 인접 경로(2~3칸)를 찾아 화살표로 만든다."""
    out = []
    circles = [c for c in grid.cells if solution[c] >= 3]
    rnd.shuffle(circles)
    for circle in circles:
        if len(out) >= n:
            break
        if circle in used:
            continue
        path = _find_arrow_path(circle, solution, grid, rnd, used)
        if path:
            used.update([circle] + path)
            out.append({"type": "arrow", "circle": list(circle), "path": [list(c) for c in path]})
    return out


def _find_arrow_path(circle: Cell, solution: dict[Cell, int], grid: Grid,
                     rnd: random.Random, used: set[Cell]) -> list[Cell] | None:
    target = solution[circle]

    def dfs(path: list[Cell], total: int) -> list[Cell] | None:
        if total == target and len(path) >= 2:
            return path
        if total >= target or len(path) >= 3:
            return None
        nxt = [c for c in _adjacent(path[-1] if path else circle, grid)
               if c != circle and c not in used and c not in path]
        rnd.shuffle(nxt)
        for c in nxt:
            found = dfs(path + [c], total + solution[c])
            if found:
                return found
        return None

    return dfs([], 0)


# ------------------------------------------------------------------ 생성
def complete_grid(grid: Grid, base_constraints: list[dict], seed: int) -> dict[Cell, int]:
    """base 제약(대각선 등)을 만족하는 무작위 완성판. 클래식이면 benchmark.random_complete_grid와 같다."""
    model = load_spec({"constraints": base_constraints})
    cfg = SolverConfig(var_order="mrv", val_order="random", propagation="ac3", seed=seed)
    result = Solver(model, cfg).solve()
    if result.solution is None:  # pragma: no cover
        raise RuntimeError("완성 격자 생성 실패")
    return result.solution


def _is_unique(model: Model) -> bool:
    """제한 시간 안에 유일해가 확인될 때만 True. 시간 초과는 '모름'이므로 False."""
    cfg = SolverConfig(var_order="mrv_degree", val_order="asc", propagation="ac3",
                       time_limit=PROBE_TIME_LIMIT)
    solver = Solver(model, cfg)
    sols = solver.solve_all(limit=2)
    return len(sols) == 1 and not solver.stats.timed_out


def dig(spec: dict, solution: dict[Cell, int], grid: Grid, target_givens: int,
        seed: int, symmetric: bool) -> dict[Cell, int]:
    """완성 해에서 칸을 지우되, 유일해가 유지되는 동안만 지운다.

    benchmark.dig_puzzle과 같은 순서로 지우지만, 매번 spec으로 Model을 다시 만들어
    저장되는 spec과 검사한 Model이 항상 같도록 한다.
    """
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
        probe = load_spec({**spec, "givens": grid.to_string(givens)})
        if not _is_unique(probe):
            givens.update(backup)
    return givens


def generate(variant: str, seed: int, target_givens: int | None = None,
             symmetric: bool = False) -> dict:
    """seed 하나로 퍼즐 레코드 하나를 만든다. 같은 (variant, seed) → 같은 퍼즐."""
    parts = VARIANTS[variant]
    target = target_givens if target_givens is not None else DEFAULT_GIVENS[variant]
    grid = Grid()
    rnd = random.Random(seed)
    t0 = time.perf_counter()

    base = [{"type": "diagonal"}] if "diagonal" in parts else []
    solution = complete_grid(grid, base, seed)
    used: set[Cell] = set()
    derived = []
    if "thermo" in parts:
        derived += derive_thermos(solution, grid, rnd, used)
    if "arrow" in parts:
        derived += derive_arrows(solution, grid, rnd, used)

    spec = {"givens": "", "constraints": base + derived}
    givens = dig(spec, solution, grid, target, seed, symmetric)
    spec["givens"] = grid.to_string(givens)
    gen_ms = (time.perf_counter() - t0) * 1000

    return _finish_record(variant, parts, spec, grid.to_string(solution), seed, {
        "target_givens": target,
        "symmetric": symmetric,
        "gen_ms": round(gen_ms, 1),
    })


def generate_classic(seed: int, target_givens: int = 24, symmetric: bool = False) -> dict:
    return generate("classic", seed, target_givens, symmetric)


def _finish_record(variant: str, parts: list[str], spec: dict, solution: str,
                   seed: int, meta: dict) -> dict:
    """spec을 엔진으로 다시 읽어 유일해를 확인하고 난이도를 붙인다."""
    model = load_spec(spec)
    if not has_unique_solution(model):
        raise RuntimeError(f"{variant} seed={seed}: 유일해가 아닌 퍼즐이 생성됨")
    rating = rate_difficulty(model)
    merged = variant != "classic"
    tier = tier_of(tier_level(rating), merged)
    labels = VARIANT_TIER_LABELS if merged else TIER_LABELS
    return {
        "id": f"{variant}-{seed:04d}",
        "variant": parts,
        "spec": spec,
        "solution": solution,
        "givens": sum(ch != "." for ch in spec["givens"]),
        "difficulty": {
            "tier": tier,
            "tier_label": labels[tier],
            "level": rating["level"],
            "label": rating["label"],
            "score": rating["score"],
            "solvable_by_logic": rating["solvable_by_logic"],
            "techniques": rating["techniques"],
        },
        "seed": seed,
        "meta": meta,
    }


# ------------------------------------------------------------------ CLI
def _log(rec: dict) -> None:
    d = rec["difficulty"]
    print(f"{rec['id']}: givens={rec['givens']} {d['tier']} (level={d['level']} "
          f"score={d['score']}) {rec['meta']['gen_ms']:.0f}ms", file=sys.stderr)


def run_count(args: argparse.Namespace) -> None:
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
    out = args.out.open("w", encoding="utf-8") if args.out else sys.stdout
    try:
        for seed in range(args.seed_start, args.seed_start + args.count):
            rec = generate(args.variant, seed, args.target_givens, args.symmetric)
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            _log(rec)
    finally:
        if args.out:
            out.close()


def run_per_tier(args: argparse.Namespace) -> None:
    """구간별로 per_tier개가 모일 때까지 seed를 늘려가며 생성한다."""
    args.out_dir.mkdir(parents=True, exist_ok=True)
    tiers = tiers_for(args.variant)
    files = {t: (args.out_dir / f"{args.variant}_{t}.jsonl").open("w", encoding="utf-8")
             for t in tiers}
    counts = dict.fromkeys(tiers, 0)
    seed = args.seed_start
    try:
        while any(n < args.per_tier for n in counts.values()):
            if seed >= args.seed_start + args.max_seeds:
                print(f"--max-seeds {args.max_seeds} 도달, 중단", file=sys.stderr)
                break
            rec = generate(args.variant, seed, args.target_givens, args.symmetric)
            seed += 1
            tier = rec["difficulty"]["tier"]
            if counts[tier] >= args.per_tier:
                continue
            files[tier].write(json.dumps(rec, ensure_ascii=False) + "\n")
            files[tier].flush()
            counts[tier] += 1
            _log(rec)
    finally:
        for f in files.values():
            f.close()
    print(f"seed {args.seed_start}~{seed - 1} 사용, 구간별 개수: {counts}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="스도쿠 퍼즐 생성 (클래식·변형)")
    ap.add_argument("--variant", choices=sorted(VARIANTS), default="classic")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--target-givens", type=int, default=None,
                    help=f"생략 시 변형별 기본값 {DEFAULT_GIVENS}")
    ap.add_argument("--symmetric", action="store_true", help="점대칭으로 지우기 (단서가 늘어남)")
    ap.add_argument("--out", type=Path, default=None, help="생략하면 stdout")
    ap.add_argument("--per-tier", type=int, default=None, help="구간별 목표 개수 (지정 시 --out-dir 모드)")
    ap.add_argument("--out-dir", type=Path, default=Path("puzzles"))
    ap.add_argument("--max-seeds", type=int, default=2000, help="--per-tier 모드에서 시도할 최대 seed 수")
    args = ap.parse_args()

    if args.per_tier:
        run_per_tier(args)
    else:
        run_count(args)


if __name__ == "__main__":
    main()
