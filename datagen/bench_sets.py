"""로컬서치 vs 백트래킹 비교용 퍼즐 세트.

puzzles/*.jsonl에서 비교에 쓸 퍼즐을 골라 puzzles/bench/에 모으고,
"해 없음"과 "해가 여러 개"인 퍼즐을 새로 만든 뒤 검증한다.

  classic.jsonl  클래식 4구간 × 25 = 100개 (원본 레코드 그대로)
  variant.jsonl  diagonal·thermo·arrow·killer·mixed × 3구간 × 앞 10개 = 150개 (원본 그대로)
  unsat.jsonl    해 없음 12개 (클래식 구간마다 3개)
                 빈칸 하나에 정답이 아닌 값을 단서로 넣는다. 그 값은 같은 행·열·박스의 단서와
                 겹치지 않아서 겉보기에는 정상 퍼즐이다. 원본이 유일해이므로 해가 0개가 된다.
  multi.jsonl    해 여러 개 12개 (클래식 구간마다 3개)
                 단서를 무작위 순서로 하나씩 지우다가 해가 2개 이상이 되면 멈춘다.

백트래킹은 해가 없음을 증명하고 해의 개수를 셀 수 있다. 로컬서치는 해가 없으면 끝나지 않고,
해가 여러 개여도 하나만 찾는다. unsat·multi는 이 차이를 보이는 용도다.

사용 예
-------
python datagen/bench_sets.py                       # puzzles/bench/에 만들고 검증
python datagen/bench_sets.py --check               # 만들지 않고 검증만
python datagen/bench_sets.py --out-dir /tmp/bench  # 다른 곳에 만들기 (재현 확인용)
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from sudoku_engine import Solver, SolverConfig  # noqa: E402
from sudoku_engine.spec import SpecError, load_spec, validate_spec  # noqa: E402

PUZZLES = ROOT / "puzzles"
CLASSIC_TIERS = ("easy", "medium", "hard", "expert")
VARIANTS = ("diagonal", "thermo", "arrow", "killer", "mixed")
VARIANT_TIERS = ("easy", "medium", "expert")
VARIANT_PER_TIER = 10
SPECIAL_PER_TIER = 3   # unsat·multi 각각, 클래식 구간마다
COUNT_LIMIT = 20       # multi의 해를 이 개수까지 센다
TIME_LIMIT = 30.0      # 풀이 한 번의 제한 시간(초)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                    encoding="utf-8")


def rc(i: int) -> list[int]:
    """81자 문자열의 위치 → spec과 같은 0부터 센 [행, 열]."""
    return [i // 9, i % 9]


def solve_all(spec: dict, limit: int) -> tuple[list[dict], Solver]:
    solver = Solver(load_spec(spec), SolverConfig(time_limit=TIME_LIMIT))
    return solver.solve_all(limit=limit), solver


# ------------------------------------------------------------------ 만들기

def make_unsat(rec: dict) -> dict:
    """빈칸 하나에 정답과 다르고 단서끼리 겹치지 않는 값을 넣는다."""
    rng = random.Random(rec["seed"])
    givens, answer = rec["spec"]["givens"], rec["solution"]
    empties = [i for i, ch in enumerate(givens) if ch == "."]
    rng.shuffle(empties)
    for i in empties:
        values = [d for d in "123456789" if d != answer[i]]
        rng.shuffle(values)
        for v in values:
            text = givens[:i] + v + givens[i + 1:]
            try:  # 단서끼리 겹치면 load_spec이 SpecError를 낸다
                load_spec({**rec["spec"], "givens": text})
            except SpecError:
                continue
            return {
                "id": f"unsat-{rec['id']}", "variant": rec["variant"],
                "spec": {**rec["spec"], "givens": text},
                "solution": None, "givens": rec["givens"] + 1,
                "expected": {"num_solutions": 0},
                "source": {"id": rec["id"], "tier": rec["difficulty"]["tier"],
                           "change": {"op": "add", "cell": rc(i), "value": int(v),
                                      "true_value": int(answer[i])}},
                "seed": rec["seed"],
            }
    raise RuntimeError(f"{rec['id']}: 넣을 수 있는 값이 없음")


def make_multi(rec: dict) -> dict:
    """단서를 무작위 순서로 지우다가 해가 2개 이상이 되면 멈춘다."""
    rng = random.Random(rec["seed"])
    text = rec["spec"]["givens"]
    filled = [i for i, ch in enumerate(text) if ch != "."]
    rng.shuffle(filled)
    removed: list[int] = []
    for i in filled:
        removed.append(i)
        text = text[:i] + "." + text[i + 1:]
        sols, solver = solve_all({**rec["spec"], "givens": text}, 2)
        if solver.stats.timed_out:
            raise RuntimeError(f"{rec['id']}: 해 세기 시간 초과")
        if len(sols) >= 2:
            break
    sols, solver = solve_all({**rec["spec"], "givens": text}, COUNT_LIMIT)
    if solver.stats.timed_out:
        raise RuntimeError(f"{rec['id']}: 해 세기 시간 초과")
    return {
        "id": f"multi-{rec['id']}", "variant": rec["variant"],
        "spec": {**rec["spec"], "givens": text},
        "solution": None, "givens": rec["givens"] - len(removed),
        "expected": {"num_solutions": len(sols), "count_limit": COUNT_LIMIT},
        "source": {"id": rec["id"], "tier": rec["difficulty"]["tier"],
                   "change": {"op": "remove", "cells": [rc(i) for i in removed],
                              "values": [int(rec["spec"]["givens"][i]) for i in removed]}},
        "seed": rec["seed"],
    }


def build(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    classic = {t: read_jsonl(PUZZLES / f"classic_{t}.jsonl") for t in CLASSIC_TIERS}
    write_jsonl(out_dir / "classic.jsonl", [r for t in CLASSIC_TIERS for r in classic[t]])
    write_jsonl(out_dir / "variant.jsonl", [
        r for v in VARIANTS for t in VARIANT_TIERS
        for r in read_jsonl(PUZZLES / f"{v}_{t}.jsonl")[:VARIANT_PER_TIER]])
    # 구간마다 앞 3개는 unsat, 그다음 3개는 multi의 원본으로 쓴다 (원본이 겹치지 않게)
    n = SPECIAL_PER_TIER
    write_jsonl(out_dir / "unsat.jsonl",
                [make_unsat(r) for t in CLASSIC_TIERS for r in classic[t][:n]])
    write_jsonl(out_dir / "multi.jsonl",
                [make_multi(r) for t in CLASSIC_TIERS for r in classic[t][n:2 * n]])


# ------------------------------------------------------------------ 검증

def check(out_dir: Path) -> int:
    sources = {r["id"]: r for p in PUZZLES.glob("*_*.jsonl") if p.stem != "nl_prompts"
               for r in read_jsonl(p)}
    files = {name: read_jsonl(out_dir / f"{name}.jsonl")
             for name in ("classic", "variant", "unsat", "multi")}
    errors: list[str] = []
    expect_n = {"classic": 25 * len(CLASSIC_TIERS),
                "variant": VARIANT_PER_TIER * len(VARIANTS) * len(VARIANT_TIERS),
                "unsat": SPECIAL_PER_TIER * len(CLASSIC_TIERS),
                "multi": SPECIAL_PER_TIER * len(CLASSIC_TIERS)}
    ids = [r["id"] for recs in files.values() for r in recs]
    if len(ids) != len(set(ids)):
        errors.append("id 중복")
    for name, recs in files.items():
        if len(recs) != expect_n[name]:
            errors.append(f"{name}: {len(recs)}개 (기대 {expect_n[name]}개)")

    for rec in files["classic"] + files["variant"]:
        if sources.get(rec["id"]) != rec:
            errors.append(f"{rec['id']}: 원본 레코드와 다름")

    proof_ms, proof_nodes = [], []
    for rec in files["unsat"]:
        src = sources[rec["source"]["id"]]
        ok, msg = validate_spec(rec["spec"])
        model = load_spec(rec["spec"])
        diff = [i for i, (a, b) in enumerate(zip(src["spec"]["givens"], rec["spec"]["givens"]))
                if a != b]
        ch = rec["source"]["change"]
        if not ok:
            errors.append(f"{rec['id']}: validate_spec 실패 ({msg})")
        if not model.is_valid(model.givens):
            errors.append(f"{rec['id']}: 단서끼리 겹침")
        if (len(diff) != 1 or rc(diff[0]) != ch["cell"]
                or src["spec"]["givens"][diff[0]] != "."
                or int(rec["spec"]["givens"][diff[0]]) == int(src["solution"][diff[0]])):
            errors.append(f"{rec['id']}: 원본과의 차이가 '빈칸 하나에 오답 추가'가 아님")
        sols, solver = solve_all(rec["spec"], 1)
        if sols or solver.stats.timed_out:
            errors.append(f"{rec['id']}: 해 없음이 증명되지 않음")
        proof_ms.append(solver.stats.elapsed * 1000)
        proof_nodes.append(solver.stats.nodes)

    counts = []
    for rec in files["multi"]:
        src = sources[rec["source"]["id"]]
        ok, msg = validate_spec(rec["spec"])
        model = load_spec(rec["spec"])
        if not ok:
            errors.append(f"{rec['id']}: validate_spec 실패 ({msg})")
        if any(b != "." and a != b for a, b in zip(src["spec"]["givens"], rec["spec"]["givens"])):
            errors.append(f"{rec['id']}: 원본에 없던 단서가 있음")
        sols, solver = solve_all(rec["spec"], COUNT_LIMIT)
        if (solver.stats.timed_out or len(sols) < 2
                or len(sols) != rec["expected"]["num_solutions"]
                or not all(model.is_complete_solution(s) for s in sols)
                or len({tuple(sorted(s.items())) for s in sols}) != len(sols)):
            errors.append(f"{rec['id']}: 해 개수·해 검사 실패")
        counts.append(len(sols))

    for name, recs in files.items():
        print(f"{name + '.jsonl':15s} {len(recs):4d}개")
    print(f"unsat 해 없음 증명({SolverConfig().label()}): "
          f"시간 중앙값 {statistics.median(proof_ms):.1f}ms (최대 {max(proof_ms):.1f}ms), "
          f"노드 중앙값 {statistics.median(proof_nodes):g} (최대 {max(proof_nodes)})")
    print(f"multi 해 개수(최대 {COUNT_LIMIT}까지 셈): {sorted(counts)}")
    for e in errors:
        print("  [실패]", e)
    print(f"실패 {len(errors)}개")
    return 1 if errors else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="로컬서치 vs 백트래킹 비교용 퍼즐 세트")
    ap.add_argument("--out-dir", type=Path, default=PUZZLES / "bench")
    ap.add_argument("--check", action="store_true", help="만들지 않고 검증만")
    args = ap.parse_args()
    if not args.check:
        build(args.out_dir)
    return check(args.out_dir)


if __name__ == "__main__":
    sys.exit(main())
