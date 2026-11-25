"""엔진 해를 독립 검사기로 대량 교차검증한다. 결과는 results/independent_validation_batch.json.

역할 분리
---------
- 이 하네스는 엔진을 실행해 해를 만든다(엔진 import).
- 판정은 엔진을 import하지 않는 ``independent_checker.validator``가 한다.

검사 대상
---------
1. 평가 퍼즐 50개: LLM(gemini-3.5-flash)이 만든 명세를 엔진으로 풀고 검사한다.
   정답 격자가 저장돼 있으면 엔진 해와 같은지도 함께 센다.
2. bench 세트 전체(classic, variant, multi, unsat): 저장된 명세를 엔진으로 풀고 검사한다.
   해가 없는 퍼즐(unsat)은 완성 격자가 없어 검사기 범위 밖이므로 "엔진이 해 없음을 냈는지"만 따로 센다.
3. 음성 대조군: 엔진 해의 숫자를 무작위로 바꿔 끼운 격자(행·열·박스는 그대로 만족)를
   검사기와 엔진 제약 검사에 함께 넣어 판정이 같은지 본다. 검사기가 아무거나 "정답"이라 하지
   않는지, 변형 제약 위반을 실제로 잡는지 확인하는 용도다.

    python validation_tools/batch_validate.py
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "engine", Path(__file__).resolve().parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from export_solver_result import solve_spec, spec_of  # noqa: E402
from independent_checker.validator import STATUS_CORRECT, validate_payload  # noqa: E402
from sudoku_engine.spec import load_spec  # noqa: E402

LLM_SPECS = ROOT / "parser" / "results" / "solver_specs_gemini-3.5-flash_20261112-160348.jsonl"
BENCH_DIR = ROOT / "puzzles" / "bench"
OUTPUT = ROOT / "results" / "independent_validation_batch.json"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def gold_solutions() -> dict[str, str]:
    """평가 퍼즐 id → 저장된 정답 격자."""
    by_puzzle: dict[str, str] = {}
    for path in (ROOT / "puzzles").glob("*.jsonl"):
        for rec in read_jsonl(path):
            if rec.get("solution") and rec.get("id"):
                by_puzzle[rec["id"]] = rec["solution"]
    gold: dict[str, str] = {}
    for rec in read_jsonl(ROOT / "puzzles" / "nl_prompts.jsonl"):
        if rec.get("puzzle_id") in by_puzzle:
            gold[rec["id"]] = by_puzzle[rec["puzzle_id"]]
    for path in (ROOT / "examples").glob("*.json"):
        ex = json.loads(path.read_text(encoding="utf-8-sig"))
        if ex.get("solution"):
            gold[ex.get("name", path.stem)] = ex["solution"]
    return gold


def check(spec: dict[str, Any], solution: str, unsupported: Any = None) -> dict[str, Any]:
    payload = {"givens": spec["givens"], "constraints": spec["constraints"], "actual_solution": solution}
    if unsupported is not None:
        payload["unsupported"] = unsupported
    return validate_payload(payload)


def engine_accepts(spec: dict[str, Any], solution: str) -> bool:
    """대조군 판정용: 엔진 자신의 제약 검사(단서 포함)."""
    model = load_spec(spec)
    assignment = {(i // 9, i % 9): int(solution[i]) for i in range(81)}
    givens = getattr(model, "givens", {}) or {}
    return model.is_valid(assignment) and all(assignment[c] == v for c, v in givens.items())


def relabel(solution: str, rng: random.Random) -> str:
    digits = list("123456789")
    while True:
        rng.shuffle(digits)
        if digits != list("123456789"):
            return "".join(digits[int(ch) - 1] for ch in solution)


def run(time_limit: float, controls: int, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    solved_items: list[tuple[str, dict[str, Any], str]] = []

    # 1) 평가 퍼즐 50개 (LLM 명세)
    gold = gold_solutions()
    for rec in read_jsonl(LLM_SPECS):
        spec = spec_of(rec)
        actual, stats = solve_spec(spec, time_limit)
        row = {"set": "eval50", "id": rec["id"], "engine": "solved" if actual else
               ("timeout" if stats.get("timed_out") else "no_solution")}
        if actual:
            report = check(spec, actual, rec.get("unsupported"))
            row["checker"] = report["status"]
            row["matches_gold"] = (actual == gold[rec["id"]]) if rec["id"] in gold else None
            if report["status"] != STATUS_CORRECT:
                row["detail"] = (report["violations"] or report["unverifiable_reasons"])[:3]
            solved_items.append((rec["id"], spec, actual))
        rows.append(row)

    # 2) bench 세트 전체
    for path in sorted(BENCH_DIR.glob("*.jsonl")):
        for rec in read_jsonl(path):
            spec = spec_of(rec)
            expected = (rec.get("expected") or {}).get("num_solutions")
            actual, stats = solve_spec(spec, time_limit)
            row = {"set": f"bench/{path.stem}", "id": rec["id"], "expected_solutions": expected,
                   "engine": "solved" if actual else ("timeout" if stats.get("timed_out") else "no_solution")}
            if actual:
                report = check(spec, actual)
                row["checker"] = report["status"]
                if report["status"] != STATUS_CORRECT:
                    row["detail"] = (report["violations"] or report["unverifiable_reasons"])[:3]
                solved_items.append((rec["id"], spec, actual))
            rows.append(row)

    # 3) 음성 대조군: 숫자 바꿔 끼우기 (단서는 비워서 단서 검사로 잡히는 것을 막는다)
    control_counts: Counter[tuple[bool, str]] = Counter()
    disagreements: list[dict[str, Any]] = []
    for puzzle_id, spec, actual in solved_items:
        blank = {"givens": "." * 81, "constraints": spec["constraints"]}
        for _ in range(controls):
            grid = relabel(actual, rng)
            engine_ok = engine_accepts(blank, grid)
            status = check(blank, grid)["status"]
            control_counts[(engine_ok, status)] += 1
            if engine_ok != (status == STATUS_CORRECT):
                disagreements.append({"id": puzzle_id, "grid": grid, "engine_ok": engine_ok, "checker": status})

    summary: dict[str, Any] = {}
    for row in rows:
        s = summary.setdefault(row["set"], Counter())
        s["puzzles"] += 1
        s[f"engine_{row['engine']}"] += 1
        if "checker" in row:
            s[f"checker_{row['checker']}"] += 1
        if row.get("matches_gold") is True:
            s["matches_gold"] += 1
        if row["engine"] == "no_solution" and row.get("expected_solutions") == 0:
            s["unsat_confirmed"] += 1

    return {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "time_limit_s": time_limit,
        "engine_config": "mrv_degree/lcv/ac3",
        "llm_specs": str(LLM_SPECS.relative_to(ROOT)).replace("\\", "/"),
        "summary": {k: dict(v) for k, v in summary.items()},
        "negative_controls": {
            "per_solved_puzzle": controls,
            "seed": seed,
            "total": sum(control_counts.values()),
            "by_engine_ok_and_checker": {f"engine_ok={k[0]}, checker={k[1]}": v
                                         for k, v in sorted(control_counts.items(), key=str)},
            "disagreements": len(disagreements),
            "disagreement_examples": disagreements[:10],
        },
        "rows": rows,
    }


def print_summary(result: dict[str, Any]) -> None:
    print(f"{'세트':<16}{'퍼즐':>6}{'엔진 해':>8}{'검사 정답':>10}{'위반':>6}{'판정불가':>9}{'정답격자 일치':>14}{'해 없음 확인':>13}")
    for name, s in result["summary"].items():
        print(f"{name:<16}{s.get('puzzles', 0):>6}{s.get('engine_solved', 0):>8}"
              f"{s.get('checker_correct', 0):>10}{s.get('checker_violation', 0):>6}"
              f"{s.get('checker_unverifiable', 0):>9}{s.get('matches_gold', '-'):>14}{s.get('unsat_confirmed', '-'):>13}")
    print("(정답 격자 비교는 평가 50개만, 해 없음 확인은 unsat 세트만 해당)")
    nc = result["negative_controls"]
    print(f"\n음성 대조군 {nc['total']}개: 엔진 제약 검사와 판정 불일치 {nc['disagreements']}개")
    for key, value in nc["by_engine_ok_and_checker"].items():
        print(f"  {key}: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="엔진 해 대량 독립 교차검증")
    parser.add_argument("--time-limit", type=float, default=10.0)
    parser.add_argument("--controls", type=int, default=5, help="해 하나당 음성 대조군 격자 수")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)

    result = run(args.time_limit, args.controls, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_summary(result)
    print(f"\n저장: {args.output}")
    bad = [r for r in result["rows"] if r.get("checker") not in (None, STATUS_CORRECT)]
    return 1 if bad or result["negative_controls"]["disagreements"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
