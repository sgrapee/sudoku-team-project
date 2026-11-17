"""Create the three ④-B benchmark figures from run_bench.py raw CSV.

Usage (repository root):
    python plot_results.py results/E1_raw.csv
    python plot_results.py results/E2_raw.csv
    python plot_results.py results/E1_raw.csv --out-dir figures/E1

Requires matplotlib: python -m pip install matplotlib
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

TIER_ORDER = {"easy": 1, "medium": 2, "hard": 3, "expert": 4}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"CSV에 데이터 행이 없습니다: {path}")
    required = {"config", "puzzle_id", "solved", "timed_out", "branch_nodes", "elapsed_ms"}
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"필수 열이 없습니다: {', '.join(sorted(missing))}")
    return rows


def as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def make_plots(csv_path: Path, out_dir: Path) -> list[Path]:
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("matplotlib이 필요합니다. 실행: python -m pip install matplotlib") from exc

    rows = read_rows(csv_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    configs = sorted({r["config"] for r in rows})
    valid = [r for r in rows if as_bool(r["solved"]) and not as_bool(r["timed_out"])]
    if not valid:
        raise ValueError("성공적으로 완료된 실행이 없어 성능 그래프를 만들 수 없습니다.")

    outputs: list[Path] = []

    # 1) Median branch nodes by configuration, using successful runs only.
    grouped_nodes: dict[str, list[float]] = defaultdict(list)
    for row in valid:
        grouped_nodes[row["config"]].append(float(row["branch_nodes"]))
    labels = [c for c in configs if grouped_nodes[c]]
    medians = []
    for config in labels:
        values = sorted(grouped_nodes[config])
        middle = len(values) // 2
        medians.append(values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2)

    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 1.2), 5))
    ax.bar(labels, medians)
    ax.set_title("Median branch nodes by configuration")
    ax.set_xlabel("Configuration")
    ax.set_ylabel("Median branch nodes (successful runs)")
    ax.tick_params(axis="x", rotation=35)
    fig.tight_layout()
    path = out_dir / f"{csv_path.stem}_01_branch_nodes.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    outputs.append(path)

    # 2) Execution-time boxplot, excluding timeouts and unsuccessful runs.
    time_data = [[float(r["elapsed_ms"]) for r in valid if r["config"] == c] for c in labels]
    keep = [(c, values) for c, values in zip(labels, time_data) if values]
    fig, ax = plt.subplots(figsize=(max(8, len(keep) * 1.2), 5))
    try:
        ax.boxplot([v for _, v in keep], tick_labels=[c for c, _ in keep], showfliers=True)
    except TypeError:  # matplotlib < 3.9
        ax.boxplot([v for _, v in keep], labels=[c for c, _ in keep], showfliers=True)
    ax.set_title("Execution time by configuration")
    ax.set_xlabel("Configuration")
    ax.set_ylabel("Elapsed time (ms; successful runs)")
    ax.tick_params(axis="x", rotation=35)
    fig.tight_layout()
    path = out_dir / f"{csv_path.stem}_02_elapsed_boxplot.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    outputs.append(path)

    # 3) Difficulty tier vs branch nodes. If tier is unavailable, use givens
    # as an explicitly labelled proxy (fewer givens usually means harder).
    has_tier = any(r.get("tier", "").strip().lower() in TIER_ORDER for r in valid)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for config in labels:
        xs, ys = [], []
        for row in valid:
            if row["config"] != config:
                continue
            tier = row.get("tier", "").strip().lower()
            if has_tier:
                if tier not in TIER_ORDER:
                    continue
                xs.append(TIER_ORDER[tier])
            else:
                givens = row.get("givens", "").strip()
                if not givens:
                    continue
                xs.append(float(givens))
            ys.append(float(row["branch_nodes"]))
        if xs:
            ax.scatter(xs, ys, alpha=0.65, label=config)
    if has_tier:
        ax.set_xticks([1, 2, 3, 4], ["easy", "medium", "hard", "expert"])
        ax.set_xlabel("Difficulty tier (ordered category)")
    else:
        ax.set_xlabel("Given clues (proxy; fewer clues often means harder)")
    ax.set_ylabel("Branch nodes")
    ax.set_title("Difficulty indicator vs search cost")
    ax.legend(fontsize="small", loc="best")
    fig.tight_layout()
    path = out_dir / f"{csv_path.stem}_03_difficulty_scatter.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    outputs.append(path)

    print(f"Figures saved to: {out_dir}")
    for item in outputs:
        print(f"- {item}")
    print(f"Note: plots include successful, non-timeout runs only ({len(valid)}/{len(rows)} rows).")
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="④-B benchmark figure generator")
    parser.add_argument("csv_file", type=Path, help="run_bench.py *_raw.csv")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    out_dir = args.out_dir or args.csv_file.parent / "figures"
    make_plots(args.csv_file, out_dir)


if __name__ == "__main__":
    main()
