"""④-A 데이터셋 검증 (A5).

puzzles/*.jsonl의 모든 퍼즐에 대해 확인한다.
  - 레코드 형식, 파일 이름({variant}_{tier})과 id·tier 일치, id 중복
  - spec이 validate_spec을 통과하고, 정답이 모든 제약을 만족하며, 단서가 정답과 일치
  - 유일해
  - 난이도(level, score, tier)를 다시 계산해도 같은지
  - (--regen) 같은 seed로 다시 생성하면 같은 퍼즐이 나오는지

사용 예
-------
python datagen/validate_dataset.py                 # puzzles/ 전체
python datagen/validate_dataset.py puzzles/thermo_*.jsonl --regen
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generator import VARIANTS, generate, tier_level, tier_of, tiers_for  # noqa: E402
from sudoku_engine import Grid, has_unique_solution  # noqa: E402
from sudoku_engine.spec import load_spec, validate_spec  # noqa: E402
from sudoku_engine.techniques import rate_difficulty  # noqa: E402

REQUIRED = {"id": str, "variant": list, "spec": dict, "solution": str, "givens": int,
            "difficulty": dict, "seed": int, "meta": dict}


def check_record(rec: dict, variant: str, tier: str, grid: Grid, regen: bool) -> list[str]:
    errs = []
    for key, typ in REQUIRED.items():
        if not isinstance(rec.get(key), typ):
            return [f"필드 {key}가 없거나 형식이 {typ.__name__}가 아님"]
    if rec["id"] != f"{variant}-{rec['seed']:04d}":
        errs.append(f"id가 파일의 변형·seed와 다름 ({variant}, seed={rec['seed']})")
    if rec["variant"] != VARIANTS[variant]:
        errs.append(f"variant {rec['variant']} ≠ {VARIANTS[variant]}")
    if rec["difficulty"].get("tier") != tier:
        errs.append(f"tier {rec['difficulty'].get('tier')}가 파일 이름의 {tier}와 다름")

    spec = rec["spec"]
    ok, msg = validate_spec(spec)
    if not ok:
        return errs + [f"validate_spec 실패: {msg}"]
    model = load_spec(spec)
    sol = grid.parse(rec["solution"])
    if len(sol) != grid.size ** 2 or not model.is_valid(sol):
        errs.append("정답이 81칸이 아니거나 제약을 위반함")
    givens = spec["givens"]
    if any(ch != "." and ch != rec["solution"][i] for i, ch in enumerate(givens)):
        errs.append("단서가 정답과 다름")
    if sum(ch != "." for ch in givens) != rec["givens"]:
        errs.append("givens 개수 불일치")
    if not has_unique_solution(model):
        errs.append("유일해가 아님")

    rating = rate_difficulty(model)
    d = rec["difficulty"]
    if (rating["level"], rating["score"]) != (d.get("level"), d.get("score")):
        errs.append(f"난이도 재계산 불일치 level/score {rating['level']}/{rating['score']} "
                    f"≠ {d.get('level')}/{d.get('score')}")
    if tier_of(tier_level(rating), variant != "classic") != tier:
        errs.append("tier 재계산 불일치")

    if regen:
        again = generate(variant, rec["seed"], rec["meta"].get("target_givens"),
                         rec["meta"].get("symmetric", False))
        if again["spec"] != spec or again["solution"] != rec["solution"]:
            errs.append("같은 seed로 다시 생성한 퍼즐이 다름")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="퍼즐 데이터셋 검증")
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--regen", action="store_true", help="seed로 다시 생성해 비교 (느림)")
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = args.files or sorted((root / "puzzles").glob("*.jsonl"))

    grid = Grid()
    seen: set[str] = set()
    total = total_err = 0
    summary = []
    for path in files:
        variant, _, tier = path.stem.rpartition("_")
        if variant not in VARIANTS or tier not in tiers_for(variant):
            print(f"[건너뜀] {path.name}: 파일 이름이 {{variant}}_{{tier}}.jsonl 형식이 아님")
            continue
        n = bad = 0
        givens = Counter()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            n += 1
            try:
                rec = json.loads(line)
                errs = check_record(rec, variant, tier, grid, args.regen)
                if rec.get("id") in seen:
                    errs.append("id 중복")
                seen.add(rec.get("id"))
                givens[rec.get("givens")] += 1
            except Exception as exc:  # noqa: BLE001 — 한 줄의 오류가 전체 검증을 멈추지 않게
                errs = [f"예외: {exc!r}"]
            if errs:
                bad += 1
                for e in errs:
                    print(f"[실패] {path.name}:{lineno} {e}")
        total += n
        total_err += bad
        g = sorted(givens)
        summary.append(f"{path.name:28s} {n:3d}개  실패 {bad}  단서 {g[0] if g else '-'}~{g[-1] if g else '-'}")

    print("\n".join(summary))
    print(f"총 {total}개, 실패 {total_err}개")
    return 1 if total_err else 0


if __name__ == "__main__":
    sys.exit(main())
