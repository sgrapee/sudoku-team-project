"""E4 난이도 vs 탐색 비용: run_bench.py 원시 CSV의 branch_nodes와 데이터셋 난이도(rate_difficulty)의 상관을 본다.

    python datagen/difficulty_vs_cost.py results/E2_full/classic/E2_raw.csv results/E2_full/variant/E2_raw.csv

입력 CSV마다 같은 폴더에 두 파일을 만든다.
- <이름>_difficulty.md   설정별 스피어만 순위상관(난이도 점수·level·단서 수 vs branch_nodes)
- <이름>_difficulty.png  설정마다 level별 branch_nodes 분포 (점 + 중앙값)

- 난이도는 puzzles/*.jsonl의 difficulty.score / difficulty.level (엔진 rate_difficulty 값). 레코드에
  difficulty가 없는 퍼즐(bench의 unsat·multi, .txt 입력)은 뺀다
- 시간 초과 없이 푼 실행만 쓴다. 설정마다 표본이 다를 수 있어 n을 같이 적는다
- 그래프는 matplotlib 필요 (없으면 표만 만든다)
"""
from __future__ import annotations

import argparse
import csv
import random
import statistics
from collections import defaultdict
from pathlib import Path

from common import PUZZLES_DIR, read_jsonl

LEVELS = (1, 2, 3, 4, 5, 6)
# run_bench.py 설정 순서 (plot_results.py와 같은 규칙)
VAR_ORDER = ("static", "mrv", "mrv_degree")
VAL_ORDER = ("asc", "lcv")
PROPAGATION_ORDER = ("none", "fc", "ac3_pure", "ac3", "full")
BLUE, TEXT, MUTED, GRID, SURFACE = "#2a78d6", "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def load_difficulty() -> dict[str, dict]:
    """퍼즐 id -> {score, level, givens} (difficulty가 있는 레코드만)."""
    out = {}
    for path in sorted(PUZZLES_DIR.glob("**/*.jsonl")):
        if path.name == "nl_prompts.jsonl":
            continue
        for rec in read_jsonl(path):
            d = rec.get("difficulty")
            if d and d.get("level") is not None:
                out[rec["id"]] = {"score": d.get("score"), "level": d["level"], "givens": rec["givens"]}
    return out


def ranks(values: list[float]) -> list[float]:
    """동점은 평균 순위."""
    order = sorted(range(len(values)), key=values.__getitem__)
    r = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None
    rx, ry = ranks(x), ranks(y)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    return sxy / (sxx * syy) ** 0.5 if sxx and syy else None


def ordered_configs(rows: list[dict[str, str]]) -> list[str]:
    first: dict[str, dict[str, str]] = {}
    for r in rows:
        first.setdefault(r["config"], r)

    def rank(order, value):
        return order.index(value) if value in order else len(order)

    return sorted(first, key=lambda c: (rank(VAR_ORDER, first[c].get("var_order")),
                                        rank(VAL_ORDER, first[c].get("val_order")),
                                        rank(PROPAGATION_ORDER, first[c].get("propagation")), c))


def analyze(csv_path: Path, difficulty: dict[str, dict]) -> None:
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"오류: {csv_path}에 데이터 행이 없습니다.")
    configs = ordered_configs(rows)
    data: dict[str, list[tuple[dict, float]]] = defaultdict(list)
    for r in rows:
        ok = r["solved"].strip().lower() == "true" and r["timed_out"].strip().lower() == "false"
        if ok and r["puzzle_id"] in difficulty:
            data[r["config"]].append((difficulty[r["puzzle_id"]], float(r["branch_nodes"])))
    if not any(data.values()):
        raise SystemExit(f"오류: {csv_path}에 난이도가 있는 퍼즐을 푼 실행이 없습니다 (bench unsat·multi나 .txt 입력?).")

    lines = [f"# 난이도 vs 탐색 비용: `{csv_path}`", "",
             "스피어만 순위상관 ρ (branch_nodes와). 시간 초과 없이 푼 실행만, n = 실행 수.", "",
             "| 설정 | n | 난이도 점수 ρ | level ρ | 단서 수 ρ | level별 branch_nodes 중앙값 (1→6) |",
             "|---|---|---|---|---|---|"]
    for c in configs:
        pts = data.get(c, [])
        nodes = [b for _, b in pts]

        def rho(key):
            v = spearman([d[key] for d, _ in pts], nodes)
            return f"{v:+.2f}" if v is not None else "-"

        by_level = defaultdict(list)
        for d, b in pts:
            by_level[d["level"]].append(b)
        medians = " / ".join(f"{statistics.median(by_level[lv]):g}" if by_level[lv] else "-" for lv in LEVELS)
        lines.append(f"| {c} | {len(pts)} | {rho('score')} | {rho('level')} | {rho('givens')} | {medians} |")
    md_path = csv_path.with_name(f"{csv_path.stem}_difficulty.md")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"saved: {md_path}")
    print("\n".join(lines[4:]))
    plot(csv_path, configs, data)


def plot(csv_path: Path, configs: list[str], data) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib이 없어 그래프는 건너뜁니다. 설치: python -m pip install matplotlib")
        return
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.size": 9.5, "text.color": TEXT, "axes.labelcolor": TEXT, "axes.edgecolor": MUTED,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "axes.axisbelow": True,
    })
    ncols = min(4, len(configs))
    nrows = -(-len(configs) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(3.3 * ncols, 3.4 * nrows), sharey=True, squeeze=False)
    jitter = random.Random(0)
    top = max((b for pts in data.values() for _, b in pts), default=1)
    for ax, c in zip(axes.flat, configs):
        pts = data.get(c, [])
        by_level = defaultdict(list)
        for d, b in pts:
            by_level[d["level"]].append(b)
        for lv in LEVELS:
            ys = by_level.get(lv, [])
            if not ys:
                continue
            ax.scatter([lv + jitter.uniform(-0.2, 0.2) for _ in ys], ys, s=10, color=BLUE, alpha=0.45,
                       linewidth=0, zorder=2)
            med = statistics.median(ys)
            ax.plot([lv - 0.3, lv + 0.3], [med, med], color=TEXT, linewidth=2, zorder=3)
        rho = spearman([d["level"] for d, _ in pts], [b for _, b in pts])
        ax.set_title(f"{c}\nρ(level, nodes) = {rho:+.2f}, n = {len(pts)}" if rho is not None else c,
                     fontsize=9.5, loc="left")
        ax.set_xticks(LEVELS)
        ax.grid(axis="x", visible=False)
        ax.set_yscale("symlog", linthresh=1)
        ax.set_ylim(-0.5, max(top, 1) * 3)
    for ax in axes.flat[len(configs):]:
        ax.set_visible(False)
    for ax in axes[:, 0]:
        ax.set_ylabel("Branch nodes (symlog)")
    for ax in axes[-1, :]:
        ax.set_xlabel("Difficulty level (6 = no logic solve)")
    fig.suptitle(f"Difficulty level vs search cost: {csv_path.parent.name}/{csv_path.name} "
                 "(line = median, dots = solved runs)", x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout()
    png_path = csv_path.with_name(f"{csv_path.stem}_difficulty.png")
    fig.savefig(png_path, dpi=180)
    plt.close(fig)
    print(f"saved: {png_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="E4: 난이도(rate_difficulty) vs branch_nodes 상관")
    ap.add_argument("csv_files", type=Path, nargs="+", help="run_bench.py *_raw.csv")
    args = ap.parse_args()
    for path in args.csv_files:
        if not path.is_file():
            ap.error(f"CSV 파일을 찾을 수 없습니다: {path}")
    difficulty = load_difficulty()
    for path in args.csv_files:
        analyze(path, difficulty)


if __name__ == "__main__":
    main()
