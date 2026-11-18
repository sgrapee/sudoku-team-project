"""변형 퍼즐 단서 수별 성공률: engine/compare_methods.py의 변형 실험을 실행 단위 CSV로 남긴다.

    python datagen/compare_variant_curve.py     # 결과: results/compare/variant_curve.csv

compare_methods.py --suite variant --time-limit 10 과 같은 퍼즐·같은 seed를 쓴다.
- 퍼즐: compare_methods.variant_constraints(킬러 5 + 온도계 + 짝수 칸 8), 정답 seed 500~503,
  단서 45/35/28/22/18개 목표로 dig_puzzle (단계마다 4개)
- 백트래킹 2설정(mrv_degree/lcv/ac3, static/asc/none) 1회씩,
  min-conflicts 2설정(init random/row) 퍼즐당 seed 3회 (seed = 1000*번호 + 회차, run_method_comparison과 같음)
- 제한 10초, 병렬 2개. 로컬서치 성공률은 컴퓨터 부하에 민감하므로 다른 무거운 작업과 같이 돌리지 않는다
"""
import csv
import random
from multiprocessing import Pool

from common import ROOT  # 엔진 import 경로 설정 포함 — sudoku_engine보다 먼저
from compare_methods import variant_constraints  # engine/compare_methods.py
from sudoku_engine import Grid, Model, SolverConfig
from sudoku_engine.benchmark import dig_puzzle, random_complete_grid
from sudoku_engine.local_search import LocalSearchConfig, solve_local_search
from sudoku_engine.solver import solve

RESULTS_DIR = ROOT / "results" / "compare"

G = Grid()
TL, TRIALS, N, BASE_SEED = 10.0, 3, 4, 500
LEVELS = (45, 35, 28, 22, 18)
BT = (("bt_mrv_degree_lcv_ac3", "mrv_degree", "lcv", "ac3"),
      ("bt_static_asc_none", "static", "asc", "none"))
LS_INITS = ("random", "row")


def make_model(givens: int, k: int) -> Model:
    """compare_methods.variant_models(N, givens, BASE_SEED)의 k번째 퍼즐과 같다."""
    seed = BASE_SEED + k
    sol = random_complete_grid(G, seed=seed)
    cons = variant_constraints(sol, random.Random(seed))
    puz = dig_puzzle(sol, G, cons, target_givens=givens, seed=seed)
    return Model(G, cons, puz)


def work(t):
    g, k = t
    model = make_model(g, k)
    base = dict(target=g, actual=len(model.givens), idx=k)
    rows = []
    for label, v, o, p in BT:
        r = solve(model, SolverConfig(var_order=v, val_order=o, propagation=p, time_limit=TL))
        rows.append({**base, "method": label, "seed": "", "solved": int(r.solved),
                     "ms": round(r.stats.elapsed * 1000, 2)})
    for init in LS_INITS:
        for trial in range(TRIALS):
            seed = 1000 * k + trial
            r = solve_local_search(model, LocalSearchConfig(init=init, seed=seed, time_limit=TL))
            rows.append({**base, "method": f"ls_min_conflicts_{init}", "seed": seed, "solved": int(r.solved),
                         "ms": round(r.stats.elapsed * 1000, 2)})
    return rows


if __name__ == "__main__":
    ts = [(g, k) for g in LEVELS for k in range(N)]
    rows = []
    with Pool(2) as p:
        for rs in p.imap_unordered(work, ts):
            rows += rs
            print(f"{len(rows)} rows", flush=True)
    rows.sort(key=lambda r: (-r["target"], r["idx"], r["method"], str(r["seed"])))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "variant_curve.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("done", len(rows))
