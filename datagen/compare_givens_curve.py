"""단서 수별 성공률 곡선: 클래식 퍼즐을 단서 42/38/34/30/26개로 새로 만들어 백트래킹과 로컬서치를 비교한다.

    python datagen/compare_givens_curve.py     # 결과: results/compare/givens_curve.csv

- 단계마다 8개(seed 9000 + 단서수*100 + 번호), 백트래킹(mrv_degree/lcv/ac3) 1회, 로컬서치 seed 3회, 제한 5초
- 병렬 2개
"""
import csv
from multiprocessing import Pool

from common import ROOT  # 엔진 import 경로 설정 포함 — sudoku_engine보다 먼저
from sudoku_engine import Grid, Model, SolverConfig
from sudoku_engine.benchmark import dig_puzzle, random_complete_grid
from sudoku_engine.local_search import LocalSearchConfig, solve_local_search
from sudoku_engine.solver import solve

RESULTS_DIR = ROOT / "results" / "compare"

G = Grid()
TL, SEEDS, N = 5.0, 3, 8
LEVELS = (42, 38, 34, 30, 26)


def work(t):
    g, k = t
    seed = 9000 + g * 100 + k
    puz = dig_puzzle(random_complete_grid(G, seed=seed), G, [], target_givens=g, seed=seed)
    base = dict(target=g, actual=len(puz), idx=k)
    rows = []
    r = solve(Model(G, [], puz), SolverConfig(var_order="mrv_degree", val_order="lcv", propagation="ac3", time_limit=TL))
    rows.append({**base, "method": "bt_mrv_degree_lcv_ac3", "seed": "", "solved": int(r.solved),
                 "ms": round(r.stats.elapsed * 1000, 2)})
    for s in range(SEEDS):
        r = solve_local_search(Model(G, [], puz), LocalSearchConfig(seed=s, time_limit=TL))
        rows.append({**base, "method": "local_min_conflicts", "seed": s, "solved": int(r.solved),
                     "ms": round(r.stats.elapsed * 1000, 2)})
    return rows


if __name__ == "__main__":
    ts = [(g, k) for g in LEVELS for k in range(N)]
    rows = []
    with Pool(2) as p:
        for rs in p.imap_unordered(work, ts):
            rows += rs
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "givens_curve.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("done", len(rows))
