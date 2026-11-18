"""Tests for analyze_failures.py (failure / edge-case classification of run_bench raw CSV)."""
from __future__ import annotations

import subprocess
import sys

import pytest

import analyze_failures as af
from conftest import ROOT

SCRIPT = ROOT / "analyze_failures.py"


# --------------------------------------------------------------------- truth()
@pytest.mark.parametrize("value", ["True", "true", " TRUE ", "1", "yes", "Y"])
def test_truth_accepts_truthy_strings(value):
    assert af.truth(value) is True


@pytest.mark.parametrize("value", ["False", "false", "0", "", "no", "N", "2"])
def test_truth_rejects_other_strings(value):
    assert af.truth(value) is False


# ------------------------------------------------------------------ classify()
@pytest.mark.parametrize("kwargs, expected", [
    # timeout wins over everything else, even a (contradictory) solved=True
    (dict(solved=True, timed_out=True), "timeout"),
    (dict(solved=False, timed_out=True, expected_solutions=1), "timeout"),
    # unsolved without timeout = search exhausted -> judged against expected_solutions
    (dict(solved=False, timed_out=False, expected_solutions=0), "unsat_confirmed"),
    (dict(solved=False, timed_out=False, expected_solutions="0.0"), "unsat_confirmed"),
    (dict(solved=False, timed_out=False, expected_solutions=1), "missed_solution"),
    (dict(solved=False, timed_out=False, expected_solutions=20), "missed_solution"),
    (dict(solved=False, timed_out=False, expected_solutions=""), "not_solved_no_timeout"),
    (dict(solved=False, timed_out=False, expected_solutions="n/a"), "not_solved_no_timeout"),
    (dict(solved=False, timed_out=True, expected_solutions=0), "timeout"),
    (dict(solved=True, expected_solutions=1, solutions_found=1), "solved"),
    # .txt inputs: run_bench writes expected_solutions = ""
    (dict(solved=True, expected_solutions="", solutions_found=1), "solved"),
    (dict(solved=True, expected_solutions="1.0", solutions_found="1"), "solved"),
    (dict(solved=True, expected_solutions=0, solutions_found=1), "unexpected_solution_for_unsat_case"),
    (dict(solved=True, expected_solutions=1, solutions_found=2), "unexpected_solution_count"),
    (dict(solved=True, expected_solutions=1, solutions_found=0), "unexpected_solution_count"),
    (dict(solved=True, expected_solutions=20, solutions_found=1), "multi_solution_case_single_solution_search"),
    (dict(solved=True, expected_solutions="n/a", solutions_found=1), "solved_count_not_comparable"),
])
def test_classify(raw_row, kwargs, expected):
    assert af.classify(raw_row(**kwargs)) == expected


def test_classify_tolerates_missing_optional_columns():
    # Only solved/timed_out present (e.g. hand-made CSV without expected_* columns).
    assert af.classify({"solved": "True", "timed_out": "False"}) == "solved"
    assert af.classify({"solved": "False", "timed_out": "False"}) == "not_solved_no_timeout"


def test_classify_separates_correct_unsat_from_solver_failure(raw_row):
    # Solver sets timed_out for both time_limit and max_nodes, so solved=False and
    # timed_out=False means the search finished: correct for UNSAT, a bug otherwise.
    unsat_ok = af.classify(raw_row(solved=False, timed_out=False, expected_solutions=0))
    unique_missed = af.classify(raw_row(solved=False, timed_out=False, expected_solutions=1))
    assert unsat_ok == "unsat_confirmed" and unsat_ok in af.OK_CATEGORIES
    assert unique_missed == "missed_solution" and unique_missed not in af.OK_CATEGORIES


# ------------------------------------------------------------------- analyze()
def test_analyze_hand_computed_example(raw_row, make_raw_csv, read_out_csv, tmp_path, capsys):
    rows = [
        raw_row("A", "p1"),                                        # solved
        raw_row("A", "p2", solved=False, timed_out=True),          # timeout
        raw_row("A", "p3", solved=False, timed_out=True),          # timeout
        raw_row("B", "p1"),                                        # solved
        raw_row("B", "p2", solved=False, timed_out=False),         # missed_solution
        raw_row("B", "p3", expected_solutions=3),                  # multi
        raw_row("B", "p4", solved=False, expected_solutions=0),    # unsat_confirmed (OK)
    ]
    csv_path = make_raw_csv(rows)
    detail_path, summary_path = af.analyze(csv_path, tmp_path / "out" / "nested")

    assert detail_path.name == "E2_raw_failure_details.csv"
    assert summary_path.name == "E2_raw_failure_summary.csv"

    summary = [(r["config"], r["total_runs"], r["category"], r["count"]) for r in read_out_csv(summary_path)]
    assert summary == [
        ("A", "3", "solved", "1"),
        ("A", "3", "timeout", "2"),
        ("B", "4", "missed_solution", "1"),
        ("B", "4", "multi_solution_case_single_solution_search", "1"),
        ("B", "4", "solved", "1"),
        ("B", "4", "unsat_confirmed", "1"),
    ]

    # correct outcomes (solved, unsat_confirmed) are not in the details file
    details = read_out_csv(detail_path)
    assert [(r["config"], r["puzzle_id"], r["failure_category"]) for r in details] == [
        ("A", "p2", "timeout"),
        ("A", "p3", "timeout"),
        ("B", "p2", "missed_solution"),
        ("B", "p3", "multi_solution_case_single_solution_search"),
    ]
    # original columns are kept, in order, with the category appended
    assert list(details[0].keys()) == list(rows[0].keys()) + ["failure_category"]
    assert details[0]["branch_nodes"] == rows[1]["branch_nodes"]

    out = capsys.readouterr().out
    assert "Input rows: 7" in out
    assert "Non-standard/unsuccessful rows: 4" in out
    assert "Correctly proven UNSAT (unsat_confirmed, not listed in details): 1" in out


def test_analyze_only_unsat_rows_lists_no_failures(raw_row, make_raw_csv, read_out_csv, tmp_path, capsys):
    rows = [raw_row("A", f"u{i}", solved=False, expected_solutions=0) for i in range(3)]
    detail_path, summary_path = af.analyze(make_raw_csv(rows), tmp_path / "out")
    assert read_out_csv(detail_path) == []
    assert [(r["category"], r["count"]) for r in read_out_csv(summary_path)] == [("unsat_confirmed", "3")]
    assert "No timeout or unsuccessful rows found" in capsys.readouterr().out


def test_analyze_header_only_raises(make_raw_csv, tmp_path):
    csv_path = make_raw_csv([])
    with pytest.raises(ValueError, match="데이터 행이 없습니다"):
        af.analyze(csv_path, tmp_path / "out")


def test_analyze_zero_byte_file_raises(tmp_path):
    csv_path = tmp_path / "empty.csv"
    csv_path.write_bytes(b"")
    with pytest.raises(ValueError, match="데이터 행이 없습니다"):
        af.analyze(csv_path, tmp_path / "out")


def test_analyze_single_solved_row(raw_row, make_raw_csv, read_out_csv, tmp_path, capsys):
    detail_path, summary_path = af.analyze(make_raw_csv([raw_row("A", "p1")]), tmp_path / "out")
    assert read_out_csv(detail_path) == []
    assert detail_path.read_text(encoding="utf-8-sig").startswith("experiment,puzzle_id,config")
    assert [(r["config"], r["category"], r["count"]) for r in read_out_csv(summary_path)] == [
        ("A", "solved", "1")]
    assert "No timeout or unsuccessful rows found" in capsys.readouterr().out


def test_analyze_single_config_all_timeouts(raw_row, make_raw_csv, read_out_csv, tmp_path):
    rows = [raw_row("only", f"p{i}", solved=False, timed_out=True) for i in range(5)]
    detail_path, summary_path = af.analyze(make_raw_csv(rows), tmp_path / "out")
    assert len(read_out_csv(detail_path)) == 5
    assert [(r["config"], r["total_runs"], r["category"], r["count"])
            for r in read_out_csv(summary_path)] == [("only", "5", "timeout", "5")]


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-8"])
def test_analyze_reads_with_and_without_bom(raw_row, make_raw_csv, read_out_csv, tmp_path, encoding):
    csv_path = make_raw_csv([raw_row("A", "p1"), raw_row("A", "p2", solved=False, timed_out=True)],
                            encoding=encoding)
    _, summary_path = af.analyze(csv_path, tmp_path / "out")
    configs = {r["config"] for r in read_out_csv(summary_path)}
    assert configs == {"A"}  # a BOM left on the header would turn this into "unknown"


def test_analyze_large_input_counts(raw_row, make_raw_csv, read_out_csv, tmp_path):
    n = 5000
    configs = ["mrv_asc_none", "mrv_asc_fc", "mrv_asc_ac3", "mrv_asc_full"]
    rows = []
    for c_idx, config in enumerate(configs):
        for i in range(n):
            timed_out = (i % (c_idx + 2) == 0)  # every 2nd / 3rd / 4th / 5th puzzle
            rows.append(raw_row(config, f"p{i:05d}", solved=not timed_out, timed_out=timed_out))
    detail_path, summary_path = af.analyze(make_raw_csv(rows), tmp_path / "out")

    expected_timeouts = {c: len(range(0, n, idx + 2)) for idx, c in enumerate(configs)}
    summary = {(r["config"], r["category"]): int(r["count"]) for r in read_out_csv(summary_path)}
    for config in configs:
        assert summary[(config, "timeout")] == expected_timeouts[config]
        assert summary[(config, "solved")] == n - expected_timeouts[config]
    assert len(read_out_csv(detail_path)) == sum(expected_timeouts.values())


def test_analyze_rejects_csv_without_required_columns(make_raw_csv, tmp_path):
    # Same header shape as analyze.py output: 'solved' is a count, 'timed_out' is absent.
    # The old code silently classified every row as not_solved_no_timeout.
    fields = ["config", "runs", "solved", "timeouts", "median_branch_nodes"]
    csv_path = make_raw_csv(
        [{"config": "mrv_asc_fc", "runs": "100", "solved": "100", "timeouts": "0",
          "median_branch_nodes": "14"}],
        name="E2_summary.csv", fields=fields)
    with pytest.raises(ValueError, match="raw CSV가 아닙니다. 필수 열이 없습니다: puzzle_id, timed_out"):
        af.analyze(csv_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()  # nothing written for a rejected input


def test_analyze_short_row_reports_line_number(raw_row, make_raw_csv, tmp_path):
    csv_path = make_raw_csv([raw_row("A", "p1")])
    with csv_path.open("a", encoding="utf-8") as f:
        f.write("E2,p2,A,mrv,asc,fc\n")  # truncated line (line 3)
    with pytest.raises(ValueError, match=r"E2_raw\.csv:3: 열 개수가 헤더\(19개\)와 다릅니다"):
        af.analyze(csv_path, tmp_path / "out")


def test_analyze_extra_column_reports_line_number(raw_row, make_raw_csv, tmp_path):
    csv_path = make_raw_csv([raw_row("A", "p1")])
    with csv_path.open("a", encoding="utf-8") as f:
        f.write(",".join(raw_row("A", "p2", solved=False, timed_out=True).values()) + ",EXTRA\n")
    with pytest.raises(ValueError, match=r":3: 열 개수가 헤더"):
        af.analyze(csv_path, tmp_path / "out")


# ------------------------------------------------------------------------ CLI
def _run_cli(*args, cwd):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd)


def test_cli_with_out_dir(raw_row, make_raw_csv, tmp_path):
    csv_path = make_raw_csv([raw_row("A", "p1"), raw_row("A", "p2", solved=False, timed_out=True)])
    out_dir = tmp_path / "custom"
    proc = _run_cli(csv_path, "--out-dir", out_dir, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert (out_dir / "E2_raw_failure_details.csv").is_file()
    assert (out_dir / "E2_raw_failure_summary.csv").is_file()
    assert "A: timeout = 1" in proc.stdout


def test_cli_default_out_dir_is_next_to_csv(raw_row, make_raw_csv, tmp_path):
    csv_path = make_raw_csv([raw_row("A", "p1")])
    proc = _run_cli(csv_path, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert (csv_path.parent / "failure_analysis" / "E2_raw_failure_summary.csv").is_file()


@pytest.mark.parametrize("target", ["missing", "directory"])
def test_cli_bad_path_gives_usage_error_without_traceback(tmp_path, target):
    path = tmp_path / "nope" / "E9_raw.csv" if target == "missing" else tmp_path
    proc = _run_cli(path, cwd=tmp_path)
    assert proc.returncode == 2
    assert "CSV 파일을 찾을 수 없습니다" in proc.stderr and str(path) in proc.stderr
    assert "Traceback" not in proc.stderr


def test_cli_bad_data_gives_error_without_traceback(make_raw_csv, tmp_path):
    csv_path = make_raw_csv([{"config": "A"}], fields=["config"])
    proc = _run_cli(csv_path, cwd=tmp_path)
    assert proc.returncode == 1
    assert proc.stderr.startswith("오류: ") and "필수 열이 없습니다" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_cli_without_arguments_shows_usage(tmp_path):
    proc = _run_cli(cwd=tmp_path)
    assert proc.returncode == 2
    assert "usage:" in proc.stderr
