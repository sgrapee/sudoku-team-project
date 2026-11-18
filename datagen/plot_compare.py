"""백트래킹 vs 로컬서치 비교 결과(results/compare/*.csv)로 보고서용 그래프 4장과 숫자 표를 만든다.

    python datagen/plot_compare.py          # 결과: results/compare/figures/

1. 01_givens_curve.png   단서 수별 성공률. 클래식(givens_curve.csv) / 변형(variant_curve.csv)
2. 02_bench_outcome.png  bench 세트별 정답 비율(runs.csv). unsat은 '해 없음 증명'을 정답으로 센다
3. 03_time_to_solve.png  시간 t 안에 푼 비율(runs.csv, classic + variant). 제한 시간을 바꿔도 결론이 같은지 본다
4. 04_ls_failures.png    로컬서치가 못 푼 퍼즐에서 가장 좋았을 때 남은 위반 수(ls_failures.csv)
summary.md               그래프에 쓴 숫자 표 (보고서에 붙일 수 있게)

입력 CSV는 compare_bench.py, compare_givens_curve.py, compare_variant_curve.py, compare_ls_failures.py가 만든다.
matplotlib 필요: python -m pip install matplotlib
"""
from __future__ import annotations

import csv
import random
import statistics
import sys
from collections import defaultdict

from common import ROOT

COMPARE_DIR = ROOT / "results" / "compare"
OUT_DIR = COMPARE_DIR / "figures"
DPI = 180

# 방법마다 색·선·표식을 고정해 모든 그래프에서 같은 방법은 같은 모양으로 보이게 한다.
# 로컬서치 두 색은 밝은 배경 대비가 3:1 미만이라 점선·빈 표식·값 라벨·summary.md 표를 같이 쓴다.
METHODS = {
    "bt_mrv_degree_lcv_ac3": ("Backtracking + propagation (mrv_degree/lcv/ac3)", "#2a78d6", "-", "o", True),
    "bt_static_asc_none": ("Plain backtracking (static/asc/none)", "#eb6834", "-", "s", False),
    "ls_min_conflicts_random": ("Min-conflicts, init random", "#1baf7a", "--", "^", False),
    "ls_min_conflicts_row": ("Min-conflicts, init row", "#eda100", "--", "D", False),
}
# runs.csv·givens_curve.csv의 로컬서치는 기본 설정(init random)이다
ALIASES = {"local_min_conflicts": "ls_min_conflicts_random"}
SHORT = {"bt_mrv_degree_lcv_ac3": "BT+propagation", "bt_static_asc_none": "plain BT",
         "ls_min_conflicts_random": "min-conflicts random", "ls_min_conflicts_row": "min-conflicts row"}

TEXT, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
SETS = (("classic", "Classic"), ("variant", "Variant"), ("multi", "Multiple solutions"),
        ("unsat", "No solution"))
VARIANT_NAMES = {"classic": "classic", "diagonal": "diagonal", "thermo": "thermo", "arrow": "arrow",
                 "killer": "killer", "diagonal+thermo+arrow": "mixed"}

# 결과 CSV를 만드는 스크립트 (파일이 없을 때 안내용)
SOURCES = {"runs.csv": "compare_bench.py", "givens_curve.csv": "compare_givens_curve.py",
           "variant_curve.csv": "compare_variant_curve.py", "ls_failures.csv": "compare_ls_failures.py"}


def read(name: str) -> list[dict[str, str]]:
    path = COMPARE_DIR / name
    if not path.is_file():
        sys.exit(f"오류: {path} 가 없습니다. 먼저 python datagen/{SOURCES[name]} 를 실행하세요.")
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["method"] = ALIASES.get(r.get("method", ""), r.get("method", ""))
    return rows


def pct(solved: int, total: int) -> float:
    return 100.0 * solved / total if total else 0.0


def style(plt) -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.size": 10, "text.color": TEXT, "axes.labelcolor": TEXT, "axes.titlesize": 11,
        "axes.edgecolor": MUTED, "axes.linewidth": 0.8, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "legend.frameon": False,
    })


def draw_method(ax, method: str, xs, ys, **kw):
    label, color, line, marker, filled = METHODS[method]
    return ax.plot(xs, ys, line, color=color, linewidth=2, marker=marker,
                   markersize=5 if filled else 8, markerfacecolor=color if filled else SURFACE,
                   markeredgewidth=1.6, label=label, zorder=3 if filled else 2, **kw)[0]


# ------------------------------------------------------------ 1. 단서 수별 성공률
def curve(rows: list[dict[str, str]]) -> dict[str, dict[int, tuple[int, int, list[float]]]]:
    """{method: {목표 단서 수: (성공, 시도, 성공한 실행의 ms)}}"""
    acc: dict[str, dict[int, list]] = defaultdict(lambda: defaultdict(lambda: [0, 0, []]))
    for r in rows:
        cell = acc[r["method"]][int(r["target"])]
        cell[1] += 1
        if r["solved"] == "1":
            cell[0] += 1
            cell[2].append(float(r["ms"]))
    return {m: {g: tuple(v) for g, v in levels.items()} for m, levels in acc.items()}


def plot_givens_curve(plt, classic, variant) -> None:
    panels = (("Classic: 8 puzzles per level, 5 s limit", classic),
              ("Variant (killer + thermo + even): 4 puzzles per level, 10 s limit", variant))
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6), sharey=True)
    for ax, (title, data) in zip(axes, panels):
        levels = sorted({g for m in data.values() for g in m}, reverse=True)
        for method in METHODS:
            if method not in data:
                continue
            ys = [pct(*data[method][g][:2]) for g in levels]
            draw_method(ax, method, levels, ys)
        ax.set_xticks(levels)
        ax.invert_xaxis()  # 왼쪽이 단서 많음(쉬움), 오른쪽으로 갈수록 어려움
        ax.set_xlabel("Givens (fewer = harder)")
        ax.set_title(title, loc="left")
        ax.set_ylim(-6, 106)
        ax.set_yticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    axes[0].set_ylabel("Success rate within the limit")
    handles = [plt.Line2D([], [], linestyle=line, color=color, linewidth=2, marker=marker,
                          markersize=5 if filled else 8, markerfacecolor=color if filled else SURFACE,
                          markeredgewidth=1.6, label=label)
               for label, color, line, marker, filled in METHODS.values()]
    fig.legend(handles=handles, loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Success rate by number of givens (local search: 3 seeds per puzzle)",
                 x=0.01, ha="left", fontsize=12, fontweight="bold")
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.savefig(OUT_DIR / "01_givens_curve.png", dpi=DPI)
    plt.close(fig)


# ------------------------------------------------------------ 2. bench 세트별 정답 비율
def correct(row: dict[str, str]) -> bool:
    if row["set"] == "unsat":  # 해 없음 퍼즐: 시간 초과 없이 탐색을 끝냈으면 '해 없음 증명'
        return row["solved"] == "0" and row["timed_out"] == "0"
    return row["solved"] == "1"


def bench_outcome(rows) -> dict[str, dict[str, tuple[int, int]]]:
    acc: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in rows:
        cell = acc[r["set"]][r["method"]]
        cell[1] += 1
        cell[0] += correct(r)
    return {s: {m: tuple(v) for m, v in ms.items()} for s, ms in acc.items()}


def plot_bench_outcome(plt, rows, outcome) -> None:
    puzzles = defaultdict(set)
    for r in rows:
        puzzles[r["set"]].add(r["id"])
    methods = [m for m in METHODS if any(m in outcome[s] for s, _ in SETS)]
    width = 0.8 / len(methods)
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    for i, method in enumerate(methods):
        label, color, *_ = METHODS[method]
        xs = [j + (i - (len(methods) - 1) / 2) * width for j in range(len(SETS))]
        ys = [pct(*outcome[s].get(method, (0, 0))) for s, _ in SETS]
        bars = ax.bar(xs, ys, width=width, color=color, label=label,
                      edgecolor=SURFACE, linewidth=2)  # 막대 사이 2px 간격
        ax.bar_label(bars, labels=[f"{y:.0f}%" for y in ys], padding=2, fontsize=9, color=TEXT)
    ax.set_xticks(range(len(SETS)), [f"{name}\n{len(puzzles[s])} puzzles" for s, name in SETS])
    ax.set_ylim(0, 112)
    ax.set_yticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.set_ylabel("Correct outcome within 5 s")
    ax.grid(axis="x", visible=False)
    ax.set_title("Bench sets: share of correct outcomes\n"
                 "No solution = proved unsatisfiable; others = found a valid solution. "
                 "Local search: 3 seeds per puzzle", loc="left", fontsize=10)
    # 막대가 100%까지 차므로 범례는 그래프 아래에 둔다
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "02_bench_outcome.png", dpi=DPI)
    plt.close(fig)


# ------------------------------------------------------------ 3. 시간 t 안에 푼 비율
def plot_time_to_solve(plt, rows, limit_ms: float = 5000.0) -> dict[str, tuple[int, int]]:
    solvable = [r for r in rows if r["set"] in ("classic", "variant")]
    n_puzzles = len({r["id"] for r in solvable})
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    totals: dict[str, tuple[int, int]] = {}
    for method in METHODS:
        runs = [r for r in solvable if r["method"] == method]
        if not runs:
            continue
        times = sorted(float(r["ms"]) for r in runs if r["solved"] == "1")
        totals[method] = (len(times), len(runs))
        xs = [1.0] + times + [limit_ms]
        ys = [0.0] + [pct(k + 1, len(runs)) for k in range(len(times))] + [pct(len(times), len(runs))]
        label, color, line, *_ = METHODS[method]
        ax.step(xs, ys, where="post", linestyle=line, color=color, linewidth=2, label=label)
        ax.annotate(f"{ys[-1]:.0f}%", (limit_ms, ys[-1]), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=9, color=TEXT)
    ax.axvline(limit_ms, color=MUTED, linewidth=1, linestyle=":")
    ax.text(limit_ms, 104, "time limit ", ha="right", va="bottom", fontsize=9, color=MUTED)
    ax.set_xscale("log")
    ax.set_xlim(1, limit_ms * 1.6)
    ax.set_ylim(-3, 110)
    ax.set_yticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.set_xlabel("Time t (ms, log scale)")
    ax.set_ylabel("Runs solved within t")
    ax.set_title(f"Classic + variant bench puzzles ({n_puzzles} puzzles; local search 3 seeds each)",
                 loc="left")
    # 오른쪽 가운데(100 ms~제한, 30~90%)는 곡선이 지나가지 않는다
    ax.legend(loc="center right", bbox_to_anchor=(0.97, 0.6), fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "03_time_to_solve.png", dpi=DPI)
    plt.close(fig)
    return totals


# ------------------------------------------------------------ 4. 로컬서치 실패 시 남은 위반 수
def plot_ls_failures(plt, rows) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        if r["solved"] == "0":
            groups[VARIANT_NAMES.get(r["variant"], r["variant"])].append(int(r["best_violation"]))
    order = [v for v in VARIANT_NAMES.values() if v in groups]
    jitter = random.Random(0)
    color = METHODS["ls_min_conflicts_random"][1]
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    for i, name in enumerate(order):
        values = groups[name]
        xs = [i + jitter.uniform(-0.18, 0.18) for _ in values]
        ax.scatter(xs, values, s=30, color=color, alpha=0.75, edgecolor=SURFACE, linewidth=1, zorder=2)
        med = statistics.median(values)
        ax.plot([i - 0.28, i + 0.28], [med, med], color=TEXT, linewidth=2, zorder=3)
        ax.annotate(f"median {med:g}", (i + 0.3, med), va="center", fontsize=8.5, color=MUTED)
    ax.set_xticks(range(len(order)), [f"{n}\n{len(groups[n])} puzzles" for n in order])
    ax.set_xlim(-0.6, len(order) - 0.1)
    top = max(max(v) for v in groups.values())
    ax.set_ylim(0, top + 2)
    ax.set_yticks(range(0, top + 2, 2))
    ax.grid(axis="x", visible=False)
    ax.set_ylabel("Violations left at best state (0 = solved)")
    ax.set_title("Min-conflicts failures: how close it got before the 5 s limit (seed 0, every point is a puzzle)",
                 loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "04_ls_failures.png", dpi=DPI)
    plt.close(fig)
    return groups


# ------------------------------------------------------------ 숫자 표
def curve_table(title: str, data, note: str) -> list[str]:
    methods = [m for m in METHODS if m in data]
    levels = sorted({g for m in data.values() for g in m}, reverse=True)
    lines = [f"### {title}", "", note, "",
             "| 단서 수 | " + " | ".join(SHORT[m] for m in methods) + " |",
             "|---|" + "---|" * len(methods)]
    for g in levels:
        cells = []
        for m in methods:
            solved, total, ms = data[m].get(g, (0, 0, []))
            text = f"{pct(solved, total):.0f}% ({solved}/{total})"
            if m.startswith("bt_") and ms:
                text += f", {statistics.median(ms):.0f} ms"
            cells.append(text)
        lines.append(f"| {g} | " + " | ".join(cells) + " |")
    return lines + [""]


def write_summary(classic, variant, outcome, totals, groups) -> None:
    lines = ["# 백트래킹 vs 로컬서치 비교: 그래프 숫자", "",
             "`python datagen/plot_compare.py`가 만든다. 시간은 성공한 실행의 중앙값이고 컴퓨터마다 다르다.", ""]
    lines += curve_table("단서 수별 성공률: 클래식 (01_givens_curve.png 왼쪽)", classic,
                         "단계마다 8퍼즐, 백트래킹 1회, 로컬서치 seed 3회, 제한 5초 (`givens_curve.csv`)")
    lines += curve_table("단서 수별 성공률: 변형 (01_givens_curve.png 오른쪽)", variant,
                         "킬러 5 + 온도계 + 짝수 칸 8, 단계마다 4퍼즐, 로컬서치 seed 3회, 제한 10초 (`variant_curve.csv`)")
    methods = [m for m in METHODS if any(m in outcome[s] for s, _ in SETS)]
    lines += ["### bench 세트별 정답 비율 (02_bench_outcome.png)", "",
              "해 없음 세트는 '해 없음을 증명'한 실행을 정답으로 센다. 제한 5초 (`runs.csv`)", "",
              "| 세트 | " + " | ".join(SHORT[m] for m in methods) + " |", "|---|" + "---|" * len(methods)]
    for s, name in SETS:
        cells = [f"{pct(*outcome[s][m]):.0f}% ({outcome[s][m][0]}/{outcome[s][m][1]})"
                 if m in outcome[s] else "-" for m in methods]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "### 5초 안에 푼 실행 (03_time_to_solve.png, classic + variant)", "",
              "| 방법 | 푼 실행 |", "|---|---|"]
    for m, (solved, total) in totals.items():
        lines.append(f"| {SHORT[m]} | {pct(solved, total):.0f}% ({solved}/{total}) |")
    lines += ["", "### 로컬서치 실패 시 남은 위반 수 (04_ls_failures.png)", "",
              "| 종류 | 퍼즐 | 최소 | 중앙값 | 최대 |", "|---|---|---|---|---|"]
    for name, values in groups.items():
        lines.append(f"| {name} | {len(values)} | {min(values)} | {statistics.median(values):g} | {max(values)} |")
    (OUT_DIR / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        sys.exit("matplotlib이 필요합니다. 실행: python -m pip install matplotlib")

    runs, ls_failures = read("runs.csv"), read("ls_failures.csv")
    classic, variant = curve(read("givens_curve.csv")), curve(read("variant_curve.csv"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    style(plt)
    plot_givens_curve(plt, classic, variant)
    outcome = bench_outcome(runs)
    plot_bench_outcome(plt, runs, outcome)
    totals = plot_time_to_solve(plt, runs)
    groups = plot_ls_failures(plt, ls_failures)
    write_summary(classic, variant, outcome, totals, {k: groups[k] for k in VARIANT_NAMES.values() if k in groups})
    print(f"saved: {OUT_DIR}")
    for path in sorted(OUT_DIR.iterdir()):
        print(f"- {path.name}")


if __name__ == "__main__":
    main()
