"""백트래킹 vs 지역 탐색(min-conflicts) 비교 실험. README_engine.md §4-2의 표를 다시 만든다.

    python compare_methods.py                    # 표준 + 변형, 기본 설정(약 8~10분)
    python compare_methods.py --suite standard   # 표준 퍼즐만
    python compare_methods.py --suite variant --givens 45,35,28,22,18 --time-limit 3 --trials 2

주의
- 시간 제한 안에 못 푼 시도는 실패로 센다. 제한을 늘리면 지역 탐색의 성공률은 오를 수 있다.
- 지역 탐색은 무작위라 결과가 seed에 따라 달라진다. 성공률(solve_rate)로 비교하고, 시간은 보조로 본다.
- 컴퓨터마다 시간(ms)은 다르다. 방법 간 상대 비교와 성공률만 의미가 있다.
"""

from __future__ import annotations

import argparse
import random
import time

from sudoku_engine import Grid, KillerCage, Model, Parity, Thermometer
from sudoku_engine.benchmark import dig_puzzle, format_table, random_complete_grid, run_method_comparison

G = Grid()


def _puzzles(path: str, start: int, count: int) -> list[str]:
    with open(path, encoding="utf-8") as f:
        rows = [ln.split()[0] for ln in f if ln.strip() and not ln.startswith("#")]
    return rows[start:start + count]


def variant_constraints(sol: dict, rnd: random.Random) -> list:
    """정답과 모순되지 않는 변형 제약: 킬러 5개 + 온도계(가능한 만큼) + 짝수 칸 8개."""
    cons: list = []
    rows = list(range(9))
    rnd.shuffle(rows)
    for r in rows[:5]:
        c0 = rnd.randrange(0, 7)
        cage = [(r, c0), (r, c0 + 1), (r, c0 + 2)]
        cons.append(KillerCage(cage, sum(sol[c] for c in cage)))
    for r in rows[5:]:
        for i in range(7):
            seg = [(r, i), (r, i + 1), (r, i + 2)]
            if sol[seg[0]] < sol[seg[1]] < sol[seg[2]]:
                cons.append(Thermometer(seg))
                break
    evens = [c for c in G.cells if sol[c] % 2 == 0]
    rnd.shuffle(evens)
    cons.append(Parity(evens[:8], even=True))
    return cons


def variant_models(count: int, givens: int, base_seed: int) -> list[Model]:
    models = []
    for k in range(count):
        seed = base_seed + k
        sol = random_complete_grid(G, seed=seed)
        cons = variant_constraints(sol, random.Random(seed))
        puz = dig_puzzle(sol, G, cons, target_givens=givens, seed=seed)  # 유일해가 유지되는 동안만 지운다
        models.append(Model(G, cons, puz))
    return models


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", choices=["standard", "variant", "all"], default="all")
    ap.add_argument("--time-limit", type=float, default=5.0, help="퍼즐 하나당 제한(초)")
    ap.add_argument("--trials", type=int, default=3, help="지역 탐색의 퍼즐당 반복 횟수(seed를 바꿔)")
    ap.add_argument("--puzzles", type=int, default=6, help="표준 퍼즐 개수(쉬움·어려움 각각)")
    ap.add_argument("--variant-count", type=int, default=4, help="단서 수 구간마다 만들 변형 퍼즐 수")
    ap.add_argument("--givens", default="45,35,28,22,18", help="변형 퍼즐의 목표 단서 수(쉼표 구분)")
    ap.add_argument("--seed", type=int, default=500, help="변형 퍼즐 생성 seed 시작값")
    args = ap.parse_args()

    if args.suite in ("standard", "all"):
        # puzzles_easy.txt의 7~12번째는 지역 탐색의 기본 파라미터를 고르는 데 썼으므로 제외한다
        for name, path in (("쉬운 표준 퍼즐", "puzzles_easy.txt"), ("어려운 표준 퍼즐", "puzzles_hard.txt")):
            ps = _puzzles(path, 0, args.puzzles)
            t = time.time()
            rows = run_method_comparison(ps, time_limit=args.time_limit, trials=args.trials)
            print(f"\n## {name} {len(ps)}개 (제한 {args.time_limit}s, 지역 탐색 퍼즐당 {args.trials}회) [{time.time() - t:.0f}s]")
            print(format_table(rows), flush=True)

    if args.suite in ("variant", "all"):
        for g in (int(x) for x in args.givens.split(",")):
            models = variant_models(args.variant_count, g, args.seed)
            t = time.time()
            rows = run_method_comparison(models, time_limit=args.time_limit, trials=args.trials)
            actual = [len(m.givens) for m in models]
            print(f"\n## 변형 퍼즐(킬러+온도계+짝수) 단서 {g}개 목표, 실제 {actual} "
                  f"(제한 {args.time_limit}s, 지역 탐색 퍼즐당 {args.trials}회) [{time.time() - t:.0f}s]")
            print(format_table(rows), flush=True)


if __name__ == "__main__":
    main()
