"""④-B benchmark runner for the current sudoku_engine.

Run from the engine directory:
    python run_bench.py --experiment all --limit 20

The script records one row per puzzle/configuration pair.  E1 fixes propagation
at FC so that variable/value ordering can be compared. E2 fixes MRV+ASC and
compares the propagation levels currently implemented by the engine.

IMPORTANT: in the current source, propagation='ac3' calls hidden-single logic
inside ac3(). Therefore E2's 'ac3' row is NOT pure AC-3. Do not describe it as
pure AC-3 until the engine is changed and re-tested by the algorithm owner.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from sudoku_engine import Grid, Model, Solver, SolverConfig

ENGINE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ENGINE_DIR / "results"


def read_puzzles(path: Path, limit: int | None = None) -> list[tuple[str, str]]:
    """Read legacy .txt files: one 81-character puzzle per non-empty line."""
    puzzles: list[tuple[str, str]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        puzzle = raw.strip()
        if not puzzle or puzzle.startswith("#"):
            continue
        if len(puzzle) != 81:
            raise ValueError(
                f"{path}:{line_no}: expected 81 characters, got {len(puzzle)}"
            )
        puzzles.append((f"{path.stem}_{len(puzzles)+1:03d}", puzzle))
        if limit is not None and len(puzzles) >= limit:
            break
    return puzzles


def configurations(experiment: str) -> list[tuple[str, SolverConfig]]:
    configs: list[tuple[str, SolverConfig]] = []
    if experiment in ("E1", "all"):
        # Isolate heuristic effects: same propagation level (FC) for all rows.
        for var_order in ("static", "mrv", "mrv_degree"):
            for val_order in ("asc", "lcv"):
                label = f"{var_order}_{val_order}_fc"
                configs.append((label, SolverConfig(
                    var_order=var_order, val_order=val_order,
                    propagation="fc", time_limit=5.0,
                )))
    if experiment in ("E2", "all"):
        # Isolate propagation effects: same variable/value ordering.
        for propagation in ("none", "fc", "ac3", "full"):
            label = f"mrv_asc_{propagation}"
            configs.append((label, SolverConfig(
                var_order="mrv", val_order="asc",
                propagation=propagation, time_limit=5.0,
            )))
    return configs


def run(experiment: str, limit: int | None, time_limit: float, output_dir: Path) -> Path:
    puzzle_sources = [
        ENGINE_DIR / "puzzles_easy.txt",
        ENGINE_DIR / "puzzles_hard.txt",
    ]
    puzzles: list[tuple[str, str]] = []
    for source in puzzle_sources:
        if source.exists():
            puzzles.extend(read_puzzles(source, limit=limit))
        else:
            print(f"[skip] not found: {source}", file=sys.stderr)

    if not puzzles:
        raise RuntimeError("No puzzles loaded. Check puzzles_easy.txt / puzzles_hard.txt")

    configs = configurations(experiment)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{experiment}_raw.csv"
    fields = [
        "experiment", "puzzle_id", "config", "var_order", "val_order",
        "propagation", "solved", "timed_out", "solutions_found", "nodes",
        "branch_nodes", "backtracks", "assignments", "elapsed_ms",
    ]

    total = len(puzzles) * len(configs)
    completed = 0
    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for puzzle_id, puzzle_text in puzzles:
            grid = Grid()
            for label, base_cfg in configs:
                cfg = SolverConfig(
                    var_order=base_cfg.var_order,
                    val_order=base_cfg.val_order,
                    propagation=base_cfg.propagation,
                    seed=base_cfg.seed,
                    max_nodes=base_cfg.max_nodes,
                    time_limit=time_limit,
                )
                model = Model(grid)
                model.load_puzzle(puzzle_text)
                result = Solver(model, cfg).solve()
                stats = result.stats.as_dict()
                writer.writerow({
                    "experiment": experiment,
                    "puzzle_id": puzzle_id,
                    "config": label,
                    "var_order": cfg.var_order,
                    "val_order": cfg.val_order,
                    "propagation": cfg.propagation,
                    "solved": result.solved,
                    "timed_out": stats["timed_out"],
                    "solutions_found": stats["solutions_found"],
                    "nodes": stats["nodes"],
                    "branch_nodes": stats["branch_nodes"],
                    "backtracks": stats["backtracks"],
                    "assignments": stats["assignments"],
                    "elapsed_ms": stats["elapsed_ms"],
                })
                completed += 1
                if completed % 20 == 0 or completed == total:
                    print(f"Progress: {completed}/{total}")

    print(f"Saved raw results: {output_path}")
    print(f"Puzzles: {len(puzzles)} | Configurations: {len(configs)} | Runs: {total}")
    if experiment in ("E2", "all"):
        print("NOTE: current propagation='ac3' includes hidden-single checks; it is not pure AC-3.")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="④-B E1/E2 benchmark runner")
    parser.add_argument("--experiment", choices=("E1", "E2", "all"), default="all")
    parser.add_argument("--limit", type=int, default=None,
                        help="maximum puzzles per input file (default: all)")
    parser.add_argument("--time-limit", type=float, default=5.0,
                        help="seconds allowed per puzzle/configuration")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(args.experiment, args.limit, args.time_limit, args.output_dir)


if __name__ == "__main__":
    main()
