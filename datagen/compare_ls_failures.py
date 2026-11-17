"""로컬서치(min-conflicts)가 못 푼 퍼즐에서 얼마나 남기고 멈췄는지 본다.

    python datagen/compare_ls_failures.py      # 결과: results/compare/ls_failures.csv

- 퍼즐: compare_bench.py와 같은 classic(구간당 10개)·variant(변형×구간당 3개)
- 로컬서치 seed 0으로 1회, 제한 5초. steps(이동 횟수), restarts(재시작), best_violation(가장 적게 남긴 위반 합계)을 남긴다
- best_violation은 엔진 local_search.violation의 정도(graded) 합계라 변형마다 단위가 다르다(킬러는 합 차이가 더해진다)
"""
import csv
import os
import sys
from multiprocessing import Pool

from compare_bench import ROOT, tasks

from sudoku_engine.local_search import LocalSearchConfig, solve_local_search  # noqa: E402
from sudoku_engine.spec import load_spec  # noqa: E402

TL = 5.0


def work(t):
    name, pid, var, tier, spec, g = t
    model = load_spec(spec)
    r = solve_local_search(model, LocalSearchConfig(seed=0, time_limit=TL))
    s = r.stats
    return dict(set=name, id=pid, variant=var, tier=tier, givens=g, n_constraints=len(model.constraints),
                solved=int(r.solved), steps=s.steps, restarts=s.restarts, best_violation=s.best_violation)


if __name__ == "__main__":
    ts = [t for t in tasks() if t[0] in ("classic", "variant")]
    with Pool(2) as p:
        rows = p.map(work, ts)
    out = os.path.join(ROOT, "results", "compare")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "ls_failures.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("done", len(rows))
