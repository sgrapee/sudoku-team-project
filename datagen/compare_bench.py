"""bench 세트(puzzles/bench/*.jsonl)에서 백트래킹과 로컬서치(min-conflicts)를 비교한다.

    python datagen/compare_bench.py            # 결과: results/compare/runs.csv

- 세트: classic(구간당 10개), variant(변형×구간당 3개), unsat 12개, multi 12개
- 백트래킹 2설정(mrv_degree/lcv/ac3, static/asc/none)은 퍼즐당 1회, 로컬서치는 seed 3회
- 퍼즐당 제한 5초. 시간 제한 안에 못 풀면 실패로 센다. unsat은 solved=0, timed_out=0이면 "해 없음 증명"
- 병렬 2개로 돌린다(팬 소음 때문). 병렬이라 ms는 단독 실행보다 약간 느릴 수 있다
- 다시 돌리면 퍼즐·노드 수는 같고 ms만 달라진다. 단, 제한 5초 근처에서 끝나는 단순 백트래킹(static/asc/none) 실행은
  컴퓨터 상태에 따라 풀림/시간 초과가 바뀔 수 있다(545행 중 2행이 바뀐 적 있음)
- unsat·multi의 tier 열은 원본 퍼즐의 구간(source.tier)이다
"""
import collections
import csv
from multiprocessing import Pool

from common import PUZZLES_DIR, ROOT, read_jsonl  # 엔진 import 경로 설정 포함 — sudoku_engine보다 먼저
from sudoku_engine import SolverConfig
from sudoku_engine.local_search import LocalSearchConfig, solve_local_search
from sudoku_engine.solver import solve
from sudoku_engine.spec import load_spec

RESULTS_DIR = ROOT / "results" / "compare"
TL, SEEDS = 5.0, 3
BT = {"bt_mrv_degree_lcv_ac3": ("mrv_degree", "lcv", "ac3"), "bt_static_asc_none": ("static", "asc", "none")}


def tasks():
    out = []
    sets = (
        ("classic", 10, lambda r: r["difficulty"]["tier"]),
        ("variant", 3, lambda r: ("+".join(r["variant"]), r["difficulty"]["tier"])),
        ("unsat", 99, lambda r: "-"),
        ("multi", 99, lambda r: "-"),
    )
    for name, per, key in sets:
        cnt = collections.Counter()
        for r in read_jsonl(PUZZLES_DIR / "bench" / f"{name}.jsonl"):
            k = key(r) if "difficulty" in r else "-"
            if cnt[k] >= per:
                continue
            cnt[k] += 1
            tier = r.get("difficulty", {}).get("tier") or r.get("source", {}).get("tier", "-")
            out.append((name, r["id"], "+".join(r["variant"]), tier, r["spec"], r.get("givens")))
    return out


def work(t):
    name, pid, var, tier, spec, g = t
    base = dict(set=name, id=pid, variant=var, tier=tier, givens=g)
    rows = []
    for m, (v, o, p) in BT.items():
        cfg = SolverConfig(var_order=v, val_order=o, propagation=p, time_limit=TL)
        r = solve(load_spec(spec), cfg)
        rows.append({**base, "method": m, "seed": "", "solved": int(r.solved), "timed_out": int(r.stats.timed_out),
                     "ms": round(r.stats.elapsed * 1000, 2), "branch_nodes": r.stats.branch_nodes})
    for s in range(SEEDS):
        r = solve_local_search(load_spec(spec), LocalSearchConfig(seed=s, time_limit=TL))
        rows.append({**base, "method": "local_min_conflicts", "seed": s, "solved": int(r.solved),
                     "timed_out": int(not r.solved), "ms": round(r.stats.elapsed * 1000, 2), "branch_nodes": ""})
    return rows


if __name__ == "__main__":
    ts = tasks()
    print(len(ts), "puzzles", flush=True)
    rows = []
    with Pool(2) as p:
        for rs in p.imap_unordered(work, ts):
            rows += rs
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "runs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("done", len(rows))
