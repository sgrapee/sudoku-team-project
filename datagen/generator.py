"""④-A 퍼즐 생성기 — 클래식 (A1) + 난이도 구간 (A3).

완성판 생성 → 유일해를 유지하며 칸 지우기 → 난이도 판정 → jsonl 레코드.
출력: puzzles/{variant}_{tier}.jsonl, 한 줄에 퍼즐 하나
  {"id", "variant", "spec"(spec.py 스키마), "solution"(81자), "givens"(단서 수),
   "difficulty"{"tier", "tier_label", "level", "label", "score", "solvable_by_logic", "techniques"},
   "seed", "meta"{"target_givens", "symmetric", "gen_ms"}}

사용 예
-------
# seed 0~9 퍼즐 10개를 한 파일로
python datagen/generator.py --count 10 --out puzzles/classic_raw.jsonl

# 난이도 구간별로 25개씩 모일 때까지 생성 → puzzles/classic_{tier}.jsonl
python datagen/generator.py --per-tier 25 --out-dir puzzles
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from sudoku_engine import Grid, has_unique_solution  # noqa: E402
from sudoku_engine.benchmark import dig_puzzle, random_complete_grid  # noqa: E402
from sudoku_engine.spec import load_spec  # noqa: E402
from sudoku_engine.techniques import rate_difficulty  # noqa: E402

# 난이도 구간 (A3).
# rate_difficulty의 level(= 풀이에 필요한 가장 어려운 기법의 등급)을 기준으로 나눈다.
# score는 구간끼리 겹치므로 구간 안의 정렬에만 쓴다 (클래식 400개 샘플: L1 33~69, L2 52~81, L4 72~124).
# level 6(엔진 기법만으로 못 풂)은 힌트를 끝까지 줄 수 없어 expert로 따로 둔다.
TIERS = ("easy", "medium", "hard", "expert")
TIER_LABELS = {"easy": "쉬움", "medium": "보통", "hard": "어려움", "expert": "추측 필요"}


def tier_of(level: int) -> str:
    """1 → easy, 2~3 → medium, 4~5 → hard, 6(논리 불가) → expert."""
    if level <= 1:
        return "easy"
    if level <= 3:
        return "medium"
    if level <= 5:
        return "hard"
    return "expert"


def generate_classic(seed: int, target_givens: int = 24, symmetric: bool = False) -> dict:
    """seed 하나로 클래식 퍼즐 레코드 하나를 만든다. 같은 seed → 같은 퍼즐."""
    grid = Grid()
    t0 = time.perf_counter()
    solution = random_complete_grid(grid, seed=seed)
    givens = dig_puzzle(solution, grid, None, target_givens, seed=seed, symmetric=symmetric)
    gen_ms = (time.perf_counter() - t0) * 1000

    spec = {"givens": grid.to_string(givens), "constraints": []}
    return _finish_record(["classic"], spec, grid.to_string(solution), seed, {
        "target_givens": target_givens,
        "symmetric": symmetric,
        "gen_ms": round(gen_ms, 1),
    })


def _finish_record(variant: list[str], spec: dict, solution: str, seed: int, meta: dict) -> dict:
    """spec을 엔진으로 다시 읽어 유일해를 확인하고 난이도를 붙인다."""
    model = load_spec(spec)
    if not has_unique_solution(model):
        raise RuntimeError(f"seed={seed}: 유일해가 아닌 퍼즐이 생성됨")
    rating = rate_difficulty(model)
    tier = tier_of(rating["level"])
    return {
        "id": f"{'+'.join(variant)}-{seed:04d}",
        "variant": variant,
        "spec": spec,
        "solution": solution,
        "givens": sum(ch != "." for ch in spec["givens"]),
        "difficulty": {
            "tier": tier,
            "tier_label": TIER_LABELS[tier],
            "level": rating["level"],
            "label": rating["label"],
            "score": rating["score"],
            "solvable_by_logic": rating["solvable_by_logic"],
            "techniques": rating["techniques"],
        },
        "seed": seed,
        "meta": meta,
    }


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
            rec = generate_classic(seed, args.target_givens, args.symmetric)
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            _log(rec)
    finally:
        if args.out:
            out.close()


def run_per_tier(args: argparse.Namespace) -> None:
    """구간별로 per_tier개가 모일 때까지 seed를 늘려가며 생성한다."""
    args.out_dir.mkdir(parents=True, exist_ok=True)
    files = {t: (args.out_dir / f"classic_{t}.jsonl").open("w", encoding="utf-8") for t in TIERS}
    counts = dict.fromkeys(TIERS, 0)
    seed = args.seed_start
    try:
        while any(n < args.per_tier for n in counts.values()):
            if seed >= args.seed_start + args.max_seeds:
                print(f"--max-seeds {args.max_seeds} 도달, 중단", file=sys.stderr)
                break
            rec = generate_classic(seed, args.target_givens, args.symmetric)
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
    ap = argparse.ArgumentParser(description="클래식 스도쿠 퍼즐 생성")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--target-givens", type=int, default=24)
    ap.add_argument("--symmetric", action="store_true", help="점대칭으로 지우기 (단서가 26~30개로 늘어남)")
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
