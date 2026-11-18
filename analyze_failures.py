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


# Categories that are the correct outcome for the puzzle; every other category
# goes to the details CSV.
OK_CATEGORIES = {"solved", "unsat_confirmed"}
REQUIRED_COLUMNS = {"config", "puzzle_id", "solved", "timed_out"}


def read_rows(path: Path) -> list[dict[str, str]]:
    """Read a run_bench.py raw CSV; reject other CSV formats and broken rows."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        missing = REQUIRED_COLUMNS - set(header)
        if header and missing:
            raise ValueError(f"{path}: run_bench.py raw CSV가 아닙니다. "
                             f"필수 열이 없습니다: {', '.join(sorted(missing))}")
        rows = []
        for row in reader:
            if None in row or None in row.values():
                raise ValueError(f"{path}:{reader.line_num}: 열 개수가 헤더({len(header)}개)와 "
                                 "다릅니다. CSV가 중간에 끊기지 않았는지 확인하세요.")
            rows.append(row)
    if not rows:
        raise ValueError(f"CSV에 데이터 행이 없습니다: {path}")
    return rows


def truth(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def expected_count(row: dict[str, str]) -> int | None:
    """expected_solutions as int, or None when empty (.txt input) or not a number."""
    value = row.get("expected_solutions", "").strip()
    try:
        return int(float(value)) if value else None
    except ValueError:
        return None


def classify(row: dict[str, str]) -> str:
    if truth(row.get("timed_out", "")):
        return "timeout"
    if not truth(row.get("solved", "")):
        # Solver sets timed_out for both time_limit and max_nodes, so an
        # unsolved run without timeout means the search space was exhausted.
        expected_n = expected_count(row)
        if expected_n == 0:
            return "unsat_confirmed"  # correct: the puzzle has no solution
        if expected_n is not None:
            return "missed_solution"  # puzzle has a solution -> suspect a solver bug
        return "not_solved_no_timeout"  # expected count unknown (e.g. .txt input)
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
    rows = read_rows(csv_path)

    out_dir.mkdir(parents=True, exist_ok=True)
    detail_path = out_dir / f"{csv_path.stem}_failure_details.csv"
    summary_path = out_dir / f"{csv_path.stem}_failure_summary.csv"
    detail_fields = list(rows[0].keys()) + ["failure_category"]
    counts: Counter[tuple[str, str]] = Counter()
    totals: Counter[str] = Counter()
    details = []

    for row in rows:
        category = classify(row)
        config = row["config"]
        totals[config] += 1
        counts[(config, category)] += 1
        if category not in OK_CATEGORIES:
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
    unsat_ok = sum(n for (_, category), n in counts.items() if category == "unsat_confirmed")
    if unsat_ok:
        print(f"Correctly proven UNSAT (unsat_confirmed, not listed in details): {unsat_ok}")
    if details:
        print("\nCategories (missed_solution = search ended without finding an existing solution):")
        for (config, category), count in sorted(counts.items()):
            if category not in OK_CATEGORIES:
                print(f"- {config}: {category} = {count}")
    else:
        print("No timeout or unsuccessful rows found in this CSV.")
    return detail_path, summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="④-B failure/edge-case analysis")
    parser.add_argument("csv_file", type=Path, help="run_bench.py *_raw.csv")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    if not args.csv_file.is_file():
        parser.error(f"CSV 파일을 찾을 수 없습니다: {args.csv_file}")
    try:
        analyze(args.csv_file, args.out_dir or args.csv_file.parent / "failure_analysis")
    except (OSError, ValueError) as exc:
        raise SystemExit(f"오류: {exc}") from None


if __name__ == "__main__":
    main()
