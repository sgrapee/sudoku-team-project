"""Create the three ④-B benchmark figures from run_bench.py raw CSV.

Usage (repository root):
    python plot_results.py results/E1_raw.csv
    python plot_results.py results/E2_raw.csv
    python plot_results.py results/E1_raw.csv --out-dir figures/E1

Requires matplotlib: python -m pip install matplotlib

Figures 1-2 compare configurations on the puzzles solved by every
configuration (the same subset as analyze.py); figure 3 shows every
successful run. Y axes are symlog because branch counts span 0 to 10^4+.
"""
from __future__ import annotations

import argparse
import csv
import random
from collections import Counter, defaultdict
from pathlib import Path

DPI = 180
TIER_ORDER = ("easy", "medium", "hard", "expert")
# Logical order of run_bench.py settings; unknown values go last.
VAR_ORDER = ("static", "mrv", "mrv_degree")
VAL_ORDER = ("asc", "lcv")
PROPAGATION_ORDER = ("none", "fc", "ac3", "full")
REQUIRED_COLUMNS = {"config", "puzzle_id", "solved", "timed_out", "branch_nodes", "elapsed_ms"}
NUMERIC_COLUMNS = ("branch_nodes", "elapsed_ms")


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def read_rows(path: Path) -> list[dict[str, str]]:
    """Read a run_bench.py raw CSV; reject other formats, broken rows and non-numeric values."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        missing = REQUIRED_COLUMNS - set(header)
        if header and missing:
            raise ValueError(f"{path}: 필수 열이 없습니다: {', '.join(sorted(missing))}")
        rows = []
        for row in reader:
            where = f"{path}:{reader.line_num}"
            if None in row or None in row.values():
                raise ValueError(f"{where}: 열 개수가 헤더({len(header)}개)와 다릅니다. "
                                 "CSV가 중간에 끊기지 않았는지 확인하세요.")
            for key in NUMERIC_COLUMNS:
                if not _is_number(row[key]):
                    raise ValueError(f"{where}: {key} 값이 숫자가 아닙니다: {row[key]!r}")
            givens = (row.get("givens") or "").strip()
            if givens and not _is_number(givens):
                raise ValueError(f"{where}: givens 값이 숫자가 아닙니다: {givens!r}")
            rows.append(row)
    if not rows:
        raise ValueError(f"CSV에 데이터 행이 없습니다: {path}")
    return rows


def as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def is_success(row: dict[str, str]) -> bool:
    return as_bool(row["solved"]) and not as_bool(row["timed_out"])


def tier_of(row: dict[str, str]) -> str:
    return (row.get("tier") or "").strip().lower()


def ordered_configs(rows: list[dict[str, str]]) -> list[str]:
    """Configs in run_bench.py order (var order, value order, propagation), not alphabetical."""
    first: dict[str, dict[str, str]] = {}
    for row in rows:
        first.setdefault(row["config"], row)

    def rank(order: tuple[str, ...], value: str | None) -> int:
        return order.index(value) if value in order else len(order)

    def key(config: str) -> tuple:
        row = first[config]
        return (rank(VAR_ORDER, row.get("var_order")), rank(VAL_ORDER, row.get("val_order")),
                rank(PROPAGATION_ORDER, row.get("propagation")), config)

    return sorted(first, key=key)


def common_solved_puzzles(rows: list[dict[str, str]], configs: list[str]) -> set[str]:
    """Puzzles solved without timeout by every configuration (same subset as analyze.py)."""
    solved_by: dict[str, set[str]] = {config: set() for config in configs}
    for row in rows:
        if is_success(row):
            solved_by[row["config"]].add(row["puzzle_id"])
    return set.intersection(*solved_by.values()) if solved_by else set()


def make_plots(csv_path: Path, out_dir: Path) -> list[Path]:
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("matplotlib이 필요합니다. 실행: python -m pip install matplotlib") from exc

    rows = read_rows(csv_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    configs = ordered_configs(rows)
    valid = [r for r in rows if is_success(r)]
    if not valid:
        raise ValueError("성공적으로 완료된 실행이 없어 성능 그래프를 만들 수 없습니다.")

    runs = Counter(r["config"] for r in rows)
    solved = Counter(r["config"] for r in valid)

    # Plots 1-2 compare configurations on the same puzzles: those solved by
    # every configuration. Using each configuration's own solved set would
    # compare different (easier/harder) samples and disagree with analyze.py.
    common = common_solved_puzzles(rows, configs)
    if not common:
        solved_counts = ", ".join(f"{c}={solved[c]}" for c in configs)
        raise ValueError(
            "모든 설정이 공통으로 푼 퍼즐이 없어 설정 비교 그래프를 만들 수 없습니다 "
            f"(설정별 성공 수: {solved_counts}).")
    compared = [r for r in valid if r["puzzle_id"] in common]
    # Each tick also shows the solve rate, which the common subset hides.
    tick_labels = [f"{c}\nsolved {solved[c]}/{runs[c]}" for c in configs]
    positions = list(range(len(configs)))
    width = max(8, len(configs) * 1.6)

    outputs: list[Path] = []

    def save(fig, suffix: str) -> None:
        fig.tight_layout()
        path = out_dir / f"{csv_path.stem}_{suffix}.png"
        fig.savefig(path, dpi=DPI)
        plt.close(fig)
        outputs.append(path)

    def symlog_axis(ax, top: float, bottom: float = 0.0) -> None:
        # Values are never negative; fix the limits so symlog does not add an
        # empty negative half, and leave headroom (x3) for labels/markers.
        ax.set_yscale("symlog", linthresh=1)
        ax.set_ylim(bottom, max(top, 1.0) * 3)

    def config_axis(ax, ticks: list[float], top: float) -> None:
        ax.set_xticks(ticks, tick_labels)
        ax.set_xlabel("Configuration")
        symlog_axis(ax, top)

    # 1) Median branch nodes by configuration on the common solved puzzles.
    grouped_nodes: dict[str, list[float]] = defaultdict(list)
    for row in compared:
        grouped_nodes[row["config"]].append(float(row["branch_nodes"]))
    medians = []
    for config in configs:
        values = sorted(grouped_nodes[config])
        middle = len(values) // 2
        medians.append(values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2)

    fig, ax = plt.subplots(figsize=(width, 5))
    bars = ax.bar(positions, medians)
    ax.bar_label(bars, labels=[f"{m:g}" for m in medians], fontsize="small")
    config_axis(ax, positions, max(medians))
    ax.set_title(f"Median branch nodes by configuration (n={len(common)} puzzles solved by all)")
    ax.set_ylabel("Median branch nodes (symlog)")
    save(fig, "01_branch_nodes")

    # 2) Execution-time boxplot on the same common solved puzzles.
    time_data = [[float(r["elapsed_ms"]) for r in compared if r["config"] == c] for c in configs]
    fig, ax = plt.subplots(figsize=(width, 5))
    ax.boxplot(time_data, positions=positions, showfliers=True)
    config_axis(ax, positions, max(max(v) for v in time_data))
    ax.set_title(f"Execution time by configuration (n={len(common)} puzzles solved by all)")
    ax.set_ylabel("Elapsed time (ms, symlog)")
    save(fig, "02_elapsed_boxplot")

    # 3) Difficulty vs branch nodes for every successful run. Tier is used when
    # present, otherwise givens as a labelled proxy. Points are dodged by
    # configuration and jittered (fixed seed) so overlapping runs stay visible.
    jitter = random.Random(0)
    tiers = [t for t in TIER_ORDER if any(tier_of(r) == t for r in valid)]
    slot = 0.8 / len(configs)
    skipped = 0
    y_max = 0.0
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for i, config in enumerate(configs):
        xs, ys = [], []
        for row in valid:
            if row["config"] != config:
                continue
            if tiers:
                if tier_of(row) not in tiers:
                    skipped += 1
                    continue
                center = tiers.index(tier_of(row)) + (i - (len(configs) - 1) / 2) * slot
                xs.append(center + jitter.uniform(-0.3, 0.3) * slot)
            else:
                givens = (row.get("givens") or "").strip()
                if not givens:
                    skipped += 1
                    continue
                xs.append(float(givens) + jitter.uniform(-0.2, 0.2))
            ys.append(float(row["branch_nodes"]))
        if xs:
            ax.scatter(xs, ys, s=14, alpha=0.6, label=config)
            y_max = max(y_max, *ys)
    if tiers:
        ax.set_xticks(range(len(tiers)), tiers)
        ax.set_xlabel("Difficulty tier (points dodged by configuration, jittered)")
    else:
        ax.set_xlabel("Given clues (proxy; fewer clues often means harder; jittered)")
    symlog_axis(ax, y_max, bottom=-0.5)  # -0.5 keeps the many 0-branch points visible
    ax.set_ylabel("Branch nodes (symlog)")
    ax.set_title("Difficulty indicator vs search cost (all successful runs)")
    if ax.collections:
        # outside the axes so it never hides points
        ax.legend(fontsize="small", loc="upper left", bbox_to_anchor=(1.01, 1))
    else:
        ax.text(0.5, 0.5, "No tier or givens values to plot", ha="center", va="center",
                transform=ax.transAxes)
    save(fig, "03_difficulty_scatter")

    print(f"Figures saved to: {out_dir}")
    for item in outputs:
        print(f"- {item}")
    print(f"Note: plots 1-2 use the {len(common)} puzzles solved by every configuration "
          "(same subset as analyze.py).")
    print(f"Note: plot 3 uses all successful, non-timeout runs ({len(valid)}/{len(rows)} rows).")
    if skipped:
        what = "tier" if tiers else "givens"
        print(f"Note: plot 3 left out {skipped} successful runs without a {what} value.")
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="④-B benchmark figure generator")
    parser.add_argument("csv_file", type=Path, help="run_bench.py *_raw.csv")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    if not args.csv_file.is_file():
        parser.error(f"CSV 파일을 찾을 수 없습니다: {args.csv_file}")
    try:
        make_plots(args.csv_file, args.out_dir or args.csv_file.parent / "figures")
    except (OSError, ValueError) as exc:
        raise SystemExit(f"오류: {exc}") from None


if __name__ == "__main__":
    main()
