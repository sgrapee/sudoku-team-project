"""min-conflicts에 시간을 길게(기본 60초) 줘도 평가 퍼즐을 못 푸는지 본다.

    python datagen/compare_ls_long.py                 # 결과: results/compare/ls_long.csv
    python datagen/compare_ls_long.py --time-limit 60 --workers 8

- 퍼즐: 보고서의 평가 퍼즐 50개(nl_prompts 40 + examples 10). LLM이 만든 명세 파일을 그대로 쓴다
  (정답 명세와 50/50 일치하므로 정답 명세로 돌린 것과 같다).
- 설정: min-conflicts init random, noise 0.05, seed 0, 제한 --time-limit초. 스텝 상한 없음.
- 기록: 풀었는지, 이동 횟수(steps), 재시작 횟수, 가장 적게 남긴 위반 합계(best_violation).
- 프로세스 --workers개를 동시에 돌리므로 이동 횟수는 컴퓨터 부하에 따라 달라진다.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from sudoku_engine.local_search import LocalSearchConfig, solve_local_search  # noqa: E402
from sudoku_engine.spec import load_spec  # noqa: E402

SPECS = ROOT / "parser" / "results" / "solver_specs_gemini-3.5-flash_20261112-160348.jsonl"
OUT = ROOT / "results" / "compare" / "ls_long.csv"


def work(task: tuple[str, dict, float]) -> dict:
    pid, spec, limit = task
    model = load_spec(spec)
    givens = sum(1 for ch in spec["givens"] if ch not in ".0")
    r = solve_local_search(model, LocalSearchConfig(seed=0, init="random", noise=0.05, time_limit=limit))
    s = r.stats
    return dict(id=pid, givens=givens, n_constraints=len(model.constraints), time_limit=limit,
                solved=int(r.solved), steps=s.steps, restarts=s.restarts,
                best_violation=s.best_violation, elapsed_s=round(s.elapsed, 2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    with open(SPECS, encoding="utf-8") as f:
        tasks = [(r["id"], r["spec"], args.time_limit) for r in map(json.loads, f)]
    with Pool(args.workers) as p:
        rows = p.map(work, tasks)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    solved = sum(r["solved"] for r in rows)
    steps = sorted(r["steps"] for r in rows)
    restarts = sorted(r["restarts"] for r in rows)
    viol = sorted(r["best_violation"] for r in rows if r["best_violation"] is not None)
    print(f"solved {solved}/{len(rows)} · steps {steps[0]}~{steps[-1]} (median {steps[len(steps) // 2]})"
          f" · restarts {restarts[0]}~{restarts[-1]} · best_violation {viol[0]}~{viol[-1]}")


if __name__ == "__main__":
    main()
