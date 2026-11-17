"""Summarize unsuccessful and edge-case runs from a ④-B raw benchmark CSV.

Usage (repository root):
    python analyze_failures.py results/E1_raw.csv
    python analyze_failures.py results/E2_raw.csv --out-dir results/failure_analysis
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


def truth(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def classify(row: dict[str, str]) -> str:
    if truth(row.get("timed_out", "")):
        return "timeout"
    if not truth(row.get("solved", "")):
        # A non-timeout unsuccessful run is not automatically proof of UNSAT.
        return "not_solved_no_timeout"
    expected = row.get("expected_solutions", "").strip()
    found = row.get("solutions_found", "").strip()
    if expected and found:
        try:
            expected_n, found_n = int(float(expected)), int(float(found))
        except ValueError:
            return "solved_count_not_comparable"
        if expected_n == 0 and found_n > 0:
            return "unexpected_solution_for_unsat_case"
        if expected_n == 1 and found_n != 1:
            return "unexpected_solution_count"
        if expected_n > 1:
            # Solver.solve() may stop after finding one solution. This CSV
            # alone does not establish the total number of solutions.
            return "multi_solution_case_single_solution_search"
    return "solved"


def analyze(csv_path: Path, out_dir: Path) -> tuple[Path, Path]:
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"CSV에 데이터 행이 없습니다: {csv_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    detail_path = out_dir / f"{csv_path.stem}_failure_details.csv"
    summary_path = out_dir / f"{csv_path.stem}_failure_summary.csv"
    detail_fields = list(rows[0].keys()) + ["failure_category"]
    counts: Counter[tuple[str, str]] = Counter()
    totals: Counter[str] = Counter()
    details = []

    for row in rows:
        category = classify(row)
        config = row.get("config", "unknown")
        totals[config] += 1
        counts[(config, category)] += 1
        if category != "solved":
            details.append({**row, "failure_category": category})

    with detail_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=detail_fields)
        writer.writeheader()
        writer.writerows(details)

    summary_fields = ["config", "total_runs", "category", "count"]
    with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fields)
        writer.writeheader()
        for config in sorted(totals):
            categories = sorted(category for cfg, category in counts if cfg == config)
            for category in categories:
                writer.writerow({
                    "config": config,
                    "total_runs": totals[config],
                    "category": category,
                    "count": counts[(config, category)],
                })

    print(f"Input rows: {len(rows)}")
    print(f"Non-standard/unsuccessful rows: {len(details)}")
    print(f"Details: {detail_path}")
    print(f"Summary: {summary_path}")
    if details:
        print("\nCategories (do not interpret 'not_solved_no_timeout' as proven UNSAT):")
        for (config, category), count in sorted(counts.items()):
            if category != "solved":
                print(f"- {config}: {category} = {count}")
    else:
        print("No timeout or unsuccessful rows found in this CSV.")
    return detail_path, summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="④-B failure/edge-case analysis")
    parser.add_argument("csv_file", type=Path, help="run_bench.py *_raw.csv")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    analyze(args.csv_file, args.out_dir or args.csv_file.parent / "failure_analysis")


if __name__ == "__main__":
    main()
