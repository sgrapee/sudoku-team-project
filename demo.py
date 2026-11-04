"""엔진 데모. 팀 회의에서 이 파일 하나만 실행하면 전체 기능을 볼 수 있다.

    python demo.py
"""

from __future__ import annotations

import random

from sudoku_engine import (
    Grid, KillerCage, Model, Parity, SolverConfig, Thermometer,
    count_solutions, diagonal_constraints, solve,
)
from sudoku_engine.benchmark import DEFAULT_CONFIGS, format_table, generate_puzzle, run_configs
from sudoku_engine.spec import load_spec, spec_to_model_or_reason, validate_spec
from sudoku_engine.techniques import next_hint, rate_difficulty, solve_logically

EASY = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"
HARD = "4.....8.5.3..........7......2.....6.....8.4......1.......6.3.7.5..2.....1.4......"


def line(title: str) -> None:
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


def demo_classic() -> None:
    line("1. 표준 스도쿠 풀이 + 계측")
    grid = Grid()
    model = Model(grid)
    model.load_puzzle(HARD)
    result = solve(model, SolverConfig(var_order="mrv", propagation="ac3"))
    print(grid.render(result.solution))
    print("\n계측:", result.stats.as_dict())


def demo_variants() -> None:
    line("2. 변형 제약 (킬러 + 온도계 + 짝수 + 대각선)")
    grid = Grid()
    base = Model(grid)
    base.load_puzzle(EASY)
    sol = solve(base).solution

    cons: list = []
    cage = [(0, 0), (0, 1), (1, 0)]
    cons.append(KillerCage(cage, sum(sol[c] for c in cage)))
    for r in range(9):
        for i in range(7):
            seg = [(r, i), (r, i + 1), (r, i + 2)]
            if sol[seg[0]] < sol[seg[1]] < sol[seg[2]]:
                cons.append(Thermometer(seg))
                break
    cons.append(Parity([c for c in grid.cells if sol[c] % 2 == 0][:8], even=True))

    rnd = random.Random(7)
    del rnd
    from sudoku_engine.benchmark import dig_puzzle

    givens = dig_puzzle(sol, grid, cons, target_givens=18, seed=7)
    model = Model(grid, cons, givens)
    print(model.summary())
    print("제약 예시:", ", ".join(c.describe() for c in cons[:4]))
    print(f"\n변형 제약을 반영해 단서를 {81 - len(givens)}칸 지웠고, 남은 단서는 {len(givens)}개입니다.")
    print(f"유일해 유지 확인: {count_solutions(model, limit=2) == 1}")
    result = solve(model, SolverConfig(propagation="ac3"))
    print(f"풀이 성공: {result.solved}, 원래 해 복원: {result.solution == sol}")
    print("계측:", result.stats.as_dict())

    plain = Model(grid, givens=givens)
    print(f"\n같은 단서를 변형 제약 없이 풀면 해가 "
          f"{count_solutions(plain, limit=50)}개 이상 — 변형 제약이 실제로 정보를 준다는 증거")


def demo_spec() -> None:
    line("3. JSON 명세 로더 (③ LLM 파서와의 인터페이스)")
    good = {
        "givens": EASY,
        "constraints": [
            {"type": "standard"},
            {"kind": "thermometer", "cells": ["r5c5", "r5c6", "r5c7"]},
            {"type": "even", "cells": [{"row": 3, "col": 3}]},
        ],
    }
    ok, msg = validate_spec(good)
    print(f"관용 표기 수용: {ok} — {msg}")

    print("\n잘못된 명세는 사람이 읽을 수 있는 이유와 함께 거부한다:")
    for bad in [
        {"constraints": [{"type": "killer", "cells": [[0, 0], [0, 1]], "sum": 30}]},
        {"constraints": [{"type": "unicorn"}]},
        {"constraints": [{"type": "sandwich", "line": "row", "index": 0}]},
    ]:
        _, why = validate_spec(bad)
        print(f"  · {why}")

    print("\n문법은 맞지만 해가 없는 명세도 잡아낸다:")
    cyclic = {
        "givens": "." * 81,
        "constraints": [
            {"type": "thermo", "path": [[0, 0], [0, 1], [0, 2]]},
            {"type": "thermo", "path": [[0, 2], [0, 1], [0, 0]]},
        ],
    }
    _, reason = spec_to_model_or_reason(cyclic)
    print(f"  · {reason}")


def demo_techniques() -> None:
    line("4. 인간 기법 풀이 · 난이도 판정 · 힌트 (⑤ 데모 UI용)")
    for name, puzzle in (("쉬운 판", EASY), ("어려운 판", HARD)):
        model = Model(Grid())
        model.load_puzzle(puzzle)
        rating = rate_difficulty(model)
        print(f"\n[{name}] 등급 {rating['label']}(level {rating['level']}), "
              f"점수 {rating['score']}, 스텝 {rating['steps']}")
        print("  기법 분포:", rating["techniques"])
        hint = next_hint(model)
        if hint:
            print("  다음 힌트:", hint.explanation)


def demo_generator() -> None:
    line("5. 유일해 퍼즐 생성 (④ 생성기가 쓰는 API)")
    grid = Grid()
    for target in (34, 26):
        puzzle, solution = generate_puzzle(target_givens=target, seed=1)
        model = Model(grid, givens=puzzle)
        rating = rate_difficulty(model)
        print(f"  목표 {target}단서 → 실제 {len(puzzle)}단서 | "
              f"유일해: {count_solutions(model, limit=2) == 1} | 등급: {rating['label']}")


def demo_benchmark() -> None:
    line("6. 휴리스틱 벤치마크 (④ 실험이 쓰는 하네스)")
    puzzles = [Grid().to_string(generate_puzzle(target_givens=26, seed=s)[0]) for s in range(6)]
    rows = run_configs(puzzles, DEFAULT_CONFIGS[:6], time_limit=2.0)
    print(format_table(rows))
    print("\n분기 노드 = 값을 2개 이상 시도한 실제 선택 지점.")
    print("설정마다 푼 퍼즐이 다르면 중앙값 비교가 왜곡되므로 common_* 열로 비교할 것.")


if __name__ == "__main__":
    demo_classic()
    demo_variants()
    demo_spec()
    demo_techniques()
    demo_generator()
    demo_benchmark()
    print("\n완료.")
