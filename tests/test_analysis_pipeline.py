"""End-to-end: run_bench.py output -> analyze_failures.py / plot_results.py.

Uses a few puzzles from puzzles/bench (unique, unsat, multi) so every
classification path that the real CSV can produce is exercised.
"""
from __future__ import annotations

import subprocess
import sys
from collections import Counter

import pytest

import analyze_failures as af
from conftest import ROOT, read_csv

BENCH = ROOT / "puzzles" / "bench"


@pytest.fixture(scope="module")
def raw_csv(tmp_path_factory):
    # E1 (FC for every config) so that every config solves the classic puzzles and
    # the common solved subset needed by plot_results.py is never empty.
    sources = [BENCH / "classic.jsonl", BENCH / "unsat.jsonl", BENCH / "multi.jsonl"]
    if not all(p.is_file() for p in sources):
        pytest.skip("puzzles/bench/*.jsonl not available")
    out = tmp_path_factory.mktemp("bench")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "run_bench.py"), "--experiment", "E1", "--limit", "2",
         "--time-limit", "2", "--output-dir", str(out), "--puzzles", *map(str, sources)],
        capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    return out / "E1_raw.csv"


def test_failure_analysis_on_real_run_bench_output(raw_csv, tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT / "analyze_failures.py"), str(raw_csv),
                           "--out-dir", str(tmp_path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    raw = read_csv(raw_csv)
    summary = read_csv(tmp_path / "E1_raw_failure_summary.csv")
    details = read_csv(tmp_path / "E1_raw_failure_details.csv")

    # counts add up per config, and details == every row outside OK_CATEGORIES
    per_config = Counter(r["config"] for r in raw)
    summed = Counter()
    for r in summary:
        assert int(r["total_runs"]) == per_config[r["config"]]
        summed[r["config"]] += int(r["count"])
    assert summed == per_config
    assert len(details) == sum(int(r["count"]) for r in summary
                               if r["category"] not in af.OK_CATEGORIES)

    by_id = {(r["config"], r["puzzle_id"]): r["failure_category"] for r in details}
    unsat_finished = 0
    for r in raw:
        key = (r["config"], r["puzzle_id"])
        if r["timed_out"] == "True":
            assert by_id[key] == "timeout"
        elif r["puzzle_id"].startswith("multi-"):
            assert by_id[key] == "multi_solution_case_single_solution_search"
        elif r["puzzle_id"].startswith("unsat-"):
            assert key not in by_id  # proven UNSAT is a correct result, not a failure
            unsat_finished += 1
        else:
            assert key not in by_id  # unique puzzle solved
    assert unsat_finished > 0
    assert sum(int(r["count"]) for r in summary if r["category"] == "unsat_confirmed") == unsat_finished
    assert not any(r["category"] == "missed_solution" for r in summary)


def test_plots_on_real_run_bench_output(raw_csv, tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT / "plot_results.py"), str(raw_csv),
                           "--out-dir", str(tmp_path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    pngs = sorted(p.name for p in tmp_path.glob("*.png"))
    assert pngs == ["E1_raw_01_branch_nodes.png", "E1_raw_02_elapsed_boxplot.png",
                    "E1_raw_03_difficulty_scatter.png"]
