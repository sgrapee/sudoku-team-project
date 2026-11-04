"""④-B first-pass analysis for run_bench.py CSV output.

Run from the engine directory:
    python analyze.py results/E1_raw.csv
    python analyze.py results/E2_raw.csv

Outputs a configuration summary CSV using the common solved-puzzle subset.
If SciPy is installed, paired Wilcoxon tests are also printed for branch_nodes
and elapsed_ms. This is a first-pass analysis; inspect timeout rates and sample
sizes before interpreting p-values.
"""
from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path


def quartiles_iqr(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    if len(values) == 1:
        return values[0], values[0], 0.0
    q = statistics.quantiles(values, n=4, method="inclusive")
    return q[0], q[2], q[2] - q[0]


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"No data rows in {path}")
    for row in rows:
        for key in ("nodes", "branch_nodes", "backtracks", "elapsed_ms"):
            row[key] = float(row[key])
        row["solved"] = row["solved"].lower() == "true"
        row["timed_out"] = row["timed_out"].lower() == "true"
    return rows


def analyze(path: Path) -> Path:
    rows = load_rows(path)
    by_config: dict[str, dict[str, dict]] = defaultdict(dict)
    all_puzzles = {r["puzzle_id"] for r in rows}
    configs = sorted({r["config"] for r in rows})
    for row in rows:
        by_config[row["config"]][row["puzzle_id"]] = row

    common = set(all_puzzles)
    for config in configs:
        common &= {pid for pid, row in by_config[config].items() if row["solved"] and not row["timed_out"]}

    fields = ["config", "runs", "solved", "timeouts", "common_puzzles",
              "median_branch_nodes", "q1_branch_nodes", "q3_branch_nodes", "iqr_branch_nodes",
              "median_elapsed_ms", "q1_elapsed_ms", "q3_elapsed_ms", "iqr_elapsed_ms"]
    out_rows = []
    for config in configs:
        cr = [by_config[config][pid] for pid in sorted(common)]
        branches = [r["branch_nodes"] for r in cr]
        times = [r["elapsed_ms"] for r in cr]
        bq1, bq3, biqr = quartiles_iqr(branches)
        tq1, tq3, tiqr = quartiles_iqr(times)
        own = list(by_config[config].values())
        out_rows.append({
            "config": config,
            "runs": len(own),
            "solved": sum(r["solved"] for r in own),
            "timeouts": sum(r["timed_out"] for r in own),
            "common_puzzles": len(common),
            "median_branch_nodes": statistics.median(branches) if branches else "",
            "q1_branch_nodes": bq1 if bq1 is not None else "",
            "q3_branch_nodes": bq3 if bq3 is not None else "",
            "iqr_branch_nodes": biqr if biqr is not None else "",
            "median_elapsed_ms": statistics.median(times) if times else "",
            "q1_elapsed_ms": tq1 if tq1 is not None else "",
            "q3_elapsed_ms": tq3 if tq3 is not None else "",
            "iqr_elapsed_ms": tiqr if tiqr is not None else "",
        })

    out_path = path.with_name(path.stem.replace("_raw", "") + "_summary.csv")
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Input: {path}")
    print(f"Total puzzle IDs: {len(all_puzzles)} | Common solved puzzles: {len(common)}")
    print(f"Summary saved: {out_path}")
    print("\nConfig summary (common solved-puzzle subset):")
    for row in out_rows:
        print(f"- {row['config']}: solved {row['solved']}/{row['runs']}, "
              f"timeouts={row['timeouts']}, median branch={row['median_branch_nodes']}, "
              f"median ms={row['median_elapsed_ms']}")

    try:
        from scipy.stats import wilcoxon
        if len(configs) >= 2 and len(common) >= 2:
            baseline = configs[0]
            print(f"\nPaired Wilcoxon tests vs baseline: {baseline}")
            for config in configs[1:]:
                a = [by_config[baseline][pid]["branch_nodes"] for pid in sorted(common)]
                b = [by_config[config][pid]["branch_nodes"] for pid in sorted(common)]
                result = wilcoxon(a, b, zero_method="wilcox", alternative="two-sided")
                print(f"- {config}: branch_nodes statistic={result.statistic:.3g}, p={result.pvalue:.4g}")
    except ImportError:
        print("SciPy not installed: skipped Wilcoxon tests (median/IQR still calculated).")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="④-B CSV statistics")
    parser.add_argument("csv_file", type=Path)
    args = parser.parse_args()
    analyze(args.csv_file)


if __name__ == "__main__":
    main()
