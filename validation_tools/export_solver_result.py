"""엔진으로 퍼즐을 풀어 독립 검사기가 읽는 결과 JSON(sudoku-result-v1)을 만든다.

이 스크립트는 엔진을 실행하는 쪽이다. 판정은 하지 않는다.
판정은 엔진을 import하지 않는 ``independent_checker/validator.py``가 한다.

    python validation_tools/export_solver_result.py examples/01_x_sudoku.json actual_result.json
    python independent_checker/checker.py actual_result.json

입력은 다음 중 하나다.
- examples/*.json 형식: 최상위에 givens, constraints (선택: solution, title, unsupported)
- 명세를 감싼 형식: {"spec": {"givens": ..., "constraints": [...]}, ...}
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = ROOT / "engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from sudoku_engine import Solver, SolverConfig  # noqa: E402
from sudoku_engine.spec import load_spec  # noqa: E402

DEFAULT_CONFIG = {"var_order": "mrv_degree", "val_order": "lcv", "propagation": "ac3"}


def spec_of(puzzle: dict[str, Any]) -> dict[str, Any]:
    """퍼즐 기록에서 엔진 명세(givens + constraints)만 꺼낸다."""
    source = puzzle["spec"] if isinstance(puzzle.get("spec"), dict) else puzzle
    if "givens" not in source:
        raise ValueError("givens가 없습니다.")
    return {"givens": source["givens"], "constraints": source.get("constraints", [])}


def grid_string(solution: dict[tuple[int, int], int]) -> str:
    return "".join(str(solution[(r, c)]) for r in range(9) for c in range(9))


def solve_spec(spec: dict[str, Any], time_limit: float = 10.0) -> tuple[str | None, dict[str, Any]]:
    """명세를 엔진 기본 설정으로 풀어 (81자 해 또는 None, 통계)를 돌려준다."""
    model = load_spec(spec)
    solver = Solver(model, SolverConfig(**DEFAULT_CONFIG, time_limit=time_limit))
    result = solver.solve()
    stats = result.stats.as_dict()
    return (grid_string(result.solution) if result.solution else None), stats


def build_result(
    puzzle: dict[str, Any], *, source: str = "", time_limit: float = 10.0
) -> dict[str, Any]:
    spec = spec_of(puzzle)
    actual, stats = solve_spec(spec, time_limit)
    result: dict[str, Any] = {
        "format": "sudoku-result-v1",
        "source": source,
        "puzzle": puzzle.get("name") or puzzle.get("id") or Path(source).stem,
        "title": puzzle.get("title") or puzzle.get("name") or puzzle.get("id") or "",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "givens": spec["givens"],
        "constraints": spec["constraints"],
    }
    if "unsupported" in puzzle:
        result["unsupported"] = puzzle["unsupported"]
    if puzzle.get("solution"):
        result["reference_source"] = "puzzle_json.solution"
        result["expected_solution"] = puzzle["solution"]
    result["actual_solution"] = actual
    result["solver"] = {"algorithm": "backtracking", **DEFAULT_CONFIG}
    result["stats"] = stats
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="엔진 풀이 결과를 검사기용 JSON으로 저장")
    parser.add_argument("puzzle", type=Path, help="퍼즐 JSON (examples/*.json 형식)")
    parser.add_argument("output", type=Path, help="저장할 결과 JSON")
    parser.add_argument("--time-limit", type=float, default=10.0, help="풀이 제한 시간(초)")
    args = parser.parse_args(argv)

    puzzle = json.loads(args.puzzle.read_text(encoding="utf-8-sig"))
    result = build_result(puzzle, source=str(args.puzzle), time_limit=args.time_limit)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result["actual_solution"] is None:
        reason = "시간 초과" if result["stats"].get("timed_out") else "해 없음"
        print(f"엔진이 해를 내지 못했습니다({reason}). 결과 파일에는 actual_solution이 null로 저장됩니다.")
        return 1
    print(f"저장: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
