"""Tests for plot_results.py.

Bar heights, boxplot inputs and scatter points are read back from the real
matplotlib objects (spying on Figure.savefig / Axes.boxplot), so the numbers
are checked against hand-computed values, not just "a file was written".
"""
from __future__ import annotations

import os
import statistics
import subprocess
import sys
import warnings

import pytest

matplotlib = pytest.importorskip("matplotlib")
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

import plot_results as pr  # noqa: E402
from conftest import RAW_FIELDS, ROOT  # noqa: E402

SCRIPT = ROOT / "plot_results.py"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def spy(monkeypatch):
    """Collect every saved figure and every boxplot data argument."""
    saved: list[Figure] = []
    box_data: list[list[list[float]]] = []
    orig_savefig, orig_boxplot = Figure.savefig, Axes.boxplot

    def savefig(self, *args, **kwargs):
        saved.append(self)
        return orig_savefig(self, *args, **kwargs)

    def boxplot(self, x, *args, **kwargs):
        box_data.append([list(v) for v in x])
        return orig_boxplot(self, x, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", savefig)
    monkeypatch.setattr(Axes, "boxplot", boxplot)
    return saved, box_data


def tick_texts(fig: Figure) -> list[str]:
    return [t.get_text() for t in fig.axes[0].get_xticklabels()]


def bars(fig: Figure) -> dict[str, float]:
    """{config: bar height}; tick labels are 'config\\nsolved k/n'."""
    ax = fig.axes[0]
    names = [t.split("\n")[0] for t in tick_texts(fig)]
    return dict(zip(names, (p.get_height() for p in ax.patches)))


def scatter_points(fig: Figure) -> dict[str, list[tuple[int, float]]]:
    """{config: [(x rounded to its tier slot / givens value, y)]} - undoes dodge + jitter."""
    ax = fig.axes[0]
    return {c.get_label(): [(round(float(x)), float(y)) for x, y in c.get_offsets()]
            for c in ax.collections}


def append_line(path, line: str) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ------------------------------------------------------------ as_bool / read_rows
@pytest.mark.parametrize("value, expected", [
    ("True", True), (" true ", True), ("1", True), ("yes", True),
    ("False", False), ("0", False), ("", False),
])
def test_as_bool(value, expected):
    assert pr.as_bool(value) is expected


def test_read_rows_header_only_raises(make_raw_csv):
    with pytest.raises(ValueError, match="데이터 행이 없습니다"):
        pr.read_rows(make_raw_csv([]))


def test_read_rows_zero_byte_file_raises(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="데이터 행이 없습니다"):
        pr.read_rows(path)


def test_read_rows_lists_missing_columns(raw_row, make_raw_csv):
    fields = [f for f in RAW_FIELDS if f not in ("branch_nodes", "elapsed_ms")]
    row = {k: v for k, v in raw_row().items() if k in fields}
    with pytest.raises(ValueError, match="필수 열이 없습니다: branch_nodes, elapsed_ms"):
        pr.read_rows(make_raw_csv([row], fields=fields))


def test_read_rows_rejects_jsonl_input(tmp_path):
    path = tmp_path / "classic.jsonl"
    path.write_text('{"id": "x", "spec": {}}\n{"id": "y", "spec": {}}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="필수 열이 없습니다"):
        pr.read_rows(path)


def test_read_rows_short_row_reports_line_number(raw_row, make_raw_csv):
    csv_path = make_raw_csv([raw_row("A", "p1")])
    append_line(csv_path, "E2,p2,A,mrv,asc,fc")  # truncated line (line 3)
    with pytest.raises(ValueError, match=r"E2_raw\.csv:3: 열 개수가 헤더\(19개\)와 다릅니다"):
        pr.read_rows(csv_path)


def test_read_rows_extra_column_reports_line_number(raw_row, make_raw_csv):
    csv_path = make_raw_csv([raw_row("A", "p1")])
    append_line(csv_path, ",".join(raw_row("A", "p2").values()) + ",EXTRA")
    with pytest.raises(ValueError, match=r":3: 열 개수가 헤더"):
        pr.read_rows(csv_path)


@pytest.mark.parametrize("column, bad", [
    ("branch_nodes", ""), ("branch_nodes", "abc"), ("elapsed_ms", "1,2"), ("givens", "many"),
])
def test_read_rows_non_numeric_value_reports_line_and_column(raw_row, make_raw_csv, column, bad):
    rows = [raw_row("A", "p1"), raw_row("A", "p2", **{column: bad})]
    with pytest.raises(ValueError, match=rf":3: {column} 값이 숫자가 아닙니다: {bad!r}"):
        pr.read_rows(make_raw_csv(rows))


def test_read_rows_allows_empty_givens(raw_row, make_raw_csv):
    assert len(pr.read_rows(make_raw_csv([raw_row("A", "p1", givens="")]))) == 1


# -------------------------------------------------------------- ordered_configs
def test_ordered_configs_e2_follows_propagation_strength(raw_row):
    rows = [raw_row(f"mrv_asc_{p}", propagation=p) for p in ("full", "ac3", "none", "ac3_pure", "fc")]
    assert pr.ordered_configs(rows) == ["mrv_asc_none", "mrv_asc_fc", "mrv_asc_ac3_pure",
                                        "mrv_asc_ac3", "mrv_asc_full"]


def test_ordered_configs_e1_matches_run_bench_order(raw_row):
    expected = [f"{var}_{val}_fc" for var in ("static", "mrv", "mrv_degree") for val in ("asc", "lcv")]
    rows = [raw_row(label, var_order=label.rsplit("_", 2)[0], val_order=label.rsplit("_", 2)[1],
                    propagation="fc")
            for label in reversed(expected)]
    assert pr.ordered_configs(rows) == expected


def test_ordered_configs_unknown_values_go_last_alphabetically(raw_row):
    rows = [raw_row("zeta", propagation="x"), raw_row("alpha", propagation="y"),
            raw_row("mrv_asc_fc")]
    assert pr.ordered_configs(rows) == ["mrv_asc_fc", "alpha", "zeta"]


# -------------------------------------------------------------- make_plots()
def test_make_plots_hand_computed_values(raw_row, make_raw_csv, tmp_path, spy):
    saved, box_data = spy
    rows = [
        # common solved puzzles = p1..p4 (A times out on p5)
        # A on p1..p4: branch 1, 3, 10, 20 -> median (3 + 10) / 2 = 6.5
        raw_row("A", "p1", branch_nodes=1, elapsed_ms=5, tier="easy"),
        raw_row("A", "p2", branch_nodes=3, elapsed_ms=7, tier=" Hard "),
        raw_row("A", "p3", branch_nodes=10, elapsed_ms=9, tier="expert"),
        raw_row("A", "p4", branch_nodes=20, elapsed_ms=11, tier="medium"),
        raw_row("A", "p5", solved=False, timed_out=True, branch_nodes=999, elapsed_ms=5000, tier="expert"),
        # B on p1..p4: branch 2, 4, 6, 8 -> median 5 (p5 = 100 is not in the common set)
        raw_row("B", "p1", branch_nodes=2, elapsed_ms=1, tier="easy"),
        raw_row("B", "p2", branch_nodes=4, elapsed_ms=2, tier="hard"),
        raw_row("B", "p3", branch_nodes=6, elapsed_ms=3, tier="expert"),
        raw_row("B", "p4", branch_nodes=8, elapsed_ms=4, tier="medium"),
        raw_row("B", "p5", branch_nodes=100, elapsed_ms=50, tier="expert"),
    ]
    outputs = pr.make_plots(make_raw_csv(rows), tmp_path / "figs")

    assert [p.name for p in outputs] == [
        "E2_raw_01_branch_nodes.png", "E2_raw_02_elapsed_boxplot.png", "E2_raw_03_difficulty_scatter.png"]
    for path in outputs:
        data = path.read_bytes()
        assert data.startswith(PNG_MAGIC) and len(data) > 1000

    assert len(saved) == 3
    # 1) bars: common-subset medians, value labels, solve rate under each tick
    assert bars(saved[0]) == {"A": 6.5, "B": 5.0}
    assert [t.get_text() for t in saved[0].axes[0].texts] == ["6.5", "5"]
    assert tick_texts(saved[0]) == ["A\nsolved 4/5", "B\nsolved 5/5"]
    assert "n=4" in saved[0].axes[0].get_title()
    # 2) boxplot on the same puzzles
    assert box_data == [[[5.0, 7.0, 9.0, 11.0], [1.0, 2.0, 3.0, 4.0]]]
    assert tick_texts(saved[1]) == ["A\nsolved 4/5", "B\nsolved 5/5"]
    # 3) scatter keeps every successful run (incl. B's p5); x slot = tier index
    assert scatter_points(saved[2]) == {
        "A": [(0, 1.0), (2, 3.0), (3, 10.0), (1, 20.0)],
        "B": [(0, 2.0), (2, 4.0), (3, 6.0), (1, 8.0), (3, 100.0)],
    }
    assert tick_texts(saved[2]) == ["easy", "medium", "hard", "expert"]
    for fig in saved:
        assert fig.axes[0].get_yscale() == "symlog"


def test_scatter_dodges_configs_within_a_tier(raw_row, make_raw_csv, tmp_path, spy):
    saved, _ = spy
    rows = [raw_row(c, f"p{i}", branch_nodes=5, tier="easy")
            for c in ("mrv_asc_none", "mrv_asc_fc", "mrv_asc_ac3") for i in range(20)]
    pr.make_plots(make_raw_csv(rows), tmp_path / "figs")
    xs = {c.get_label(): [float(x) for x, _ in c.get_offsets()] for c in saved[2].axes[0].collections}
    # same tier, same y: configs must not sit on top of each other
    assert max(xs["mrv_asc_none"]) < min(xs["mrv_asc_fc"])
    assert max(xs["mrv_asc_fc"]) < min(xs["mrv_asc_ac3"])
    assert all(-0.5 < x < 0.5 for v in xs.values() for x in v)


def test_scatter_shows_only_tiers_present(raw_row, make_raw_csv, tmp_path, spy):
    saved, _ = spy
    rows = [raw_row("A", "p1", tier="easy"), raw_row("A", "p2", tier="expert")]
    pr.make_plots(make_raw_csv(rows), tmp_path / "figs")
    assert tick_texts(saved[2]) == ["easy", "expert"]
    assert scatter_points(saved[2]) == {"A": [(0, 10.0), (1, 10.0)]}


def test_scatter_reports_runs_without_tier(raw_row, make_raw_csv, tmp_path, spy, capsys):
    saved, _ = spy
    rows = [raw_row("A", "p1", tier="easy"), raw_row("A", "p2", tier=""), raw_row("A", "p3", tier="")]
    pr.make_plots(make_raw_csv(rows), tmp_path / "figs")
    assert scatter_points(saved[2]) == {"A": [(0, 10.0)]}
    assert "plot 3 left out 2 successful runs without a tier value" in capsys.readouterr().out


def test_make_plots_uses_givens_when_no_tier(raw_row, make_raw_csv, tmp_path, spy):
    saved, _ = spy
    rows = [raw_row("A", "p1", tier="", givens=30, branch_nodes=7),
            raw_row("A", "p2", tier="", givens=24, branch_nodes=70)]
    pr.make_plots(make_raw_csv(rows), tmp_path / "figs")
    assert scatter_points(saved[2]) == {"A": [(30, 7.0), (24, 70.0)]}
    assert "proxy" in saved[2].axes[0].get_xlabel()


def test_make_plots_no_tier_and_no_givens_draws_message_without_warning(
        raw_row, make_raw_csv, tmp_path, spy):
    saved, _ = spy
    rows = [raw_row("A", "p1", tier="", givens="")]
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # the old code raised a legend UserWarning here
        outputs = pr.make_plots(make_raw_csv(rows), tmp_path / "figs")
    assert all(p.is_file() for p in outputs)
    ax = saved[2].axes[0]
    assert len(ax.collections) == 0 and ax.get_legend() is None
    assert [t.get_text() for t in ax.texts] == ["No tier or givens values to plot"]


def test_make_plots_single_sample(raw_row, make_raw_csv, tmp_path, spy):
    saved, box_data = spy
    pr.make_plots(make_raw_csv([raw_row("solo", "p1", branch_nodes=42, elapsed_ms=8)]), tmp_path / "f")
    assert bars(saved[0]) == {"solo": 42.0}
    assert box_data == [[[8.0]]]


def test_make_plots_zero_median_is_drawn(raw_row, make_raw_csv, tmp_path, spy):
    # branch_nodes is often 0 for ac3/full; symlog (not log) must accept it
    saved, _ = spy
    rows = [raw_row("mrv_asc_full", f"p{i}", branch_nodes=0) for i in range(3)]
    pr.make_plots(make_raw_csv(rows), tmp_path / "figs")
    assert bars(saved[0]) == {"mrv_asc_full": 0.0}


def test_make_plots_no_successful_run_raises(raw_row, make_raw_csv, tmp_path):
    rows = [raw_row("A", "p1", solved=False, timed_out=True),
            raw_row("A", "p2", solved=False, timed_out=False)]
    with pytest.raises(ValueError, match="성공적으로 완료된 실행이 없어"):
        pr.make_plots(make_raw_csv(rows), tmp_path / "figs")


def test_make_plots_without_common_solved_puzzle_raises(raw_row, make_raw_csv, tmp_path):
    rows = [
        raw_row("A", "p1"),
        raw_row("B", "p1", solved=False, timed_out=True),
        raw_row("B", "p2"),
    ]
    with pytest.raises(ValueError, match=r"공통으로 푼 퍼즐이 없어.*A=1, B=1"):
        pr.make_plots(make_raw_csv(rows), tmp_path / "figs")


def test_make_plots_config_that_never_succeeds_raises(raw_row, make_raw_csv, tmp_path):
    rows = [raw_row("A", "p1"), raw_row("C", "p1", solved=False, timed_out=True)]
    with pytest.raises(ValueError, match="C=0"):
        pr.make_plots(make_raw_csv(rows), tmp_path / "figs")


def test_make_plots_large_input(raw_row, make_raw_csv, tmp_path, spy):
    saved, _ = spy
    n = 5000
    configs = ["mrv_asc_none", "mrv_asc_fc", "mrv_asc_ac3", "mrv_asc_full"]
    tiers = ["easy", "medium", "hard", "expert"]
    rows = [raw_row(c, f"p{i:05d}", branch_nodes=i + 1000 * k, elapsed_ms=i % 97, tier=tiers[i % 4])
            for k, c in enumerate(configs) for i in range(n)]
    outputs = pr.make_plots(make_raw_csv(rows), tmp_path / "figs")
    assert all(p.is_file() for p in outputs)
    expected = {c: statistics.median(range(1000 * k, 1000 * k + n)) for k, c in enumerate(configs)}
    assert bars(saved[0]) == expected
    assert sum(len(v) for v in scatter_points(saved[2]).values()) == len(rows)


def test_bar_medians_use_common_solved_subset(raw_row, make_raw_csv, tmp_path, spy):
    # Each config's own solved set would give none=10, fc=1000 (survivorship bias).
    saved, _ = spy
    rows = [
        raw_row("mrv_asc_none", "e1", branch_nodes=10),
        raw_row("mrv_asc_none", "h1", solved=False, timed_out=True, branch_nodes=9999),
        raw_row("mrv_asc_none", "h2", solved=False, timed_out=True, branch_nodes=9999),
        raw_row("mrv_asc_fc", "e1", branch_nodes=20),
        raw_row("mrv_asc_fc", "h1", branch_nodes=1000),
        raw_row("mrv_asc_fc", "h2", branch_nodes=2000),
    ]
    pr.make_plots(make_raw_csv(rows), tmp_path / "figs")
    # common solved subset = {e1}
    assert bars(saved[0]) == {"mrv_asc_none": 10.0, "mrv_asc_fc": 20.0}
    assert tick_texts(saved[0]) == ["mrv_asc_none\nsolved 1/3", "mrv_asc_fc\nsolved 3/3"]


def test_bar_medians_match_analyze_py_summary(raw_row, make_raw_csv, read_out_csv, tmp_path, spy):
    import analyze

    saved, _ = spy
    rows = []
    for i in range(9):
        rows.append(raw_row("mrv_asc_none", f"p{i}", solved=i < 5, timed_out=i >= 5,
                            branch_nodes=100 + 37 * i, elapsed_ms=10 + i))
        rows.append(raw_row("mrv_asc_fc", f"p{i}", branch_nodes=3 * i * i, elapsed_ms=1 + i))
        rows.append(raw_row("mrv_asc_ac3", f"p{i}", solved=i != 2, timed_out=False,
                            branch_nodes=i, elapsed_ms=2 + i))
    csv_path = make_raw_csv(rows)
    pr.make_plots(csv_path, tmp_path / "figs")
    summary = read_out_csv(analyze.analyze(csv_path))
    assert bars(saved[0]) == {r["config"]: float(r["median_branch_nodes"]) for r in summary}


# ------------------------------------------------------------------------ CLI
def _run_cli(*args, cwd, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd, env=env)


def test_cli_with_out_dir(raw_row, make_raw_csv, tmp_path):
    csv_path = make_raw_csv([raw_row("A", "p1"), raw_row("A", "p2", solved=False, timed_out=True)])
    proc = _run_cli(csv_path, "--out-dir", tmp_path / "custom", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert len(list((tmp_path / "custom").glob("E2_raw_0*.png"))) == 3
    assert "(1/2 rows)" in proc.stdout


def test_cli_default_out_dir_is_next_to_csv(raw_row, make_raw_csv, tmp_path):
    csv_path = make_raw_csv([raw_row("A", "p1")])
    proc = _run_cli(csv_path, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert (csv_path.parent / "figures" / "E2_raw_01_branch_nodes.png").is_file()


@pytest.mark.parametrize("target", ["missing", "directory"])
def test_cli_bad_path_gives_usage_error_without_traceback(tmp_path, target):
    path = tmp_path / "nope" / "E9_raw.csv" if target == "missing" else tmp_path
    proc = _run_cli(path, cwd=tmp_path)
    assert proc.returncode == 2
    assert "CSV 파일을 찾을 수 없습니다" in proc.stderr and str(path) in proc.stderr
    assert "Traceback" not in proc.stderr


def test_cli_bad_data_gives_error_without_traceback(raw_row, make_raw_csv, tmp_path):
    csv_path = make_raw_csv([raw_row("A", "p1", solved=False, timed_out=True)])
    proc = _run_cli(csv_path, cwd=tmp_path)
    assert proc.returncode == 1
    assert proc.stderr.startswith("오류: 성공적으로 완료된 실행이 없어")
    assert "Traceback" not in proc.stderr


def test_cli_without_matplotlib_prints_install_hint(raw_row, make_raw_csv, tmp_path):
    fake = tmp_path / "fake_site" / "matplotlib"
    fake.mkdir(parents=True)
    (fake / "__init__.py").write_text("raise ImportError('matplotlib hidden for test')\n")
    env = {**os.environ, "PYTHONPATH": str(fake.parent)}
    proc = _run_cli(make_raw_csv([raw_row("A", "p1")]), cwd=tmp_path, env=env)
    assert proc.returncode == 1
    assert "matplotlib이 필요합니다" in proc.stderr
    assert "Traceback" not in proc.stderr
