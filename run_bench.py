"""④-B benchmark runner for the current sudoku_engine.

Run from the repository root:
    python run_bench.py --experiment all --limit 20             # engine/puzzles_*.txt
    python run_bench.py --experiment E1 --puzzles puzzles/bench/classic.jsonl

--puzzles accepts legacy .txt files (one 81-character classic puzzle per line)
and puzzles/*.jsonl dataset files (format: puzzles/README.md). JSONL puzzles are
built with load_spec(), so variant constraints are included.

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
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENGINE_DIR = ROOT / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from sudoku_engine import Grid, Model, Solver, SolverConfig  # noqa: E402
from sudoku_engine.spec import load_spec  # noqa: E402

DEFAULT_OUTPUT = ROOT / "results"
LEGACY_SOURCES = [ENGINE_DIR / "puzzles_easy.txt", ENGINE_DIR / "puzzles_hard.txt"]


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


def read_jsonl_puzzles(path: Path, limit: int | None = None) -> list[dict]:
    """Read puzzles/*.jsonl: one record per line (see puzzles/README.md)."""
    puzzles: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        rec = json.loads(raw)
        # bench/unsat·multi records keep the tier under "source" instead of "difficulty"
        tier = (rec.get("difficulty") or {}).get("tier") or (rec.get("source") or {}).get("tier", "")
        puzzles.append({
            "puzzle_id": rec["id"],
            "spec": rec["spec"],
            "source_file": path.name,
            "variant": "+".join(rec["variant"]),
            "tier": tier,
            "givens": rec["givens"],
            # dataset puzzles are unique; bench/unsat·multi say otherwise in "expected"
            "expected_solutions": (rec.get("expected") or {}).get("num_solutions", 1),
        })
        if limit is not None and len(puzzles) >= limit:
            break
    return puzzles


def load_sources(sources: list[Path], limit: int | None) -> list[dict]:
    """Load .txt and .jsonl inputs into one list of puzzle dicts."""
    puzzles: list[dict] = []
    for source in sources:
        if not source.exists():
            print(f"[skip] not found: {source}", file=sys.stderr)
            continue
        if source.suffix == ".jsonl":
            puzzles.extend(read_jsonl_puzzles(source, limit=limit))
            continue
        for puzzle_id, text in read_puzzles(source, limit=limit):
            puzzles.append({
                "puzzle_id": puzzle_id, "text": text, "source_file": source.name,
                "variant": "classic", "tier": "",
                "givens": sum(ch not in ".0" for ch in text), "expected_solutions": "",
            })
    seen: set[str] = set()
    for p in puzzles:
        if p["puzzle_id"] in seen:
            raise ValueError(f"duplicate puzzle_id {p['puzzle_id']}: pass each puzzle file once")
        seen.add(p["puzzle_id"])
    return puzzles


def build_model(puzzle: dict) -> Model:
    if "spec" in puzzle:
        return load_spec(puzzle["spec"])
    model = Model(Grid())
    model.load_puzzle(puzzle["text"])
    return model


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


def run(experiment: str, limit: int | None, time_limit: float, output_dir: Path,
        sources: list[Path] | None = None) -> Path:
    puzzles = load_sources(sources or LEGACY_SOURCES, limit)
    if not puzzles:
        raise RuntimeError("No puzzles loaded. Check the --puzzles paths")

    configs = configurations(experiment)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{experiment}_raw.csv"
    fields = [
        "experiment", "puzzle_id", "config", "var_order", "val_order",
        "propagation", "solved", "timed_out", "solutions_found", "nodes",
        "branch_nodes", "backtracks", "assignments", "elapsed_ms",
        "source_file", "variant", "tier", "givens", "expected_solutions",
    ]

    total = len(puzzles) * len(configs)
    completed = 0
    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for puzzle in puzzles:
            for label, base_cfg in configs:
                cfg = SolverConfig(
                    var_order=base_cfg.var_order,
                    val_order=base_cfg.val_order,
                    propagation=base_cfg.propagation,
                    seed=base_cfg.seed,
                    max_nodes=base_cfg.max_nodes,
                    time_limit=time_limit,
                )
                model = build_model(puzzle)
                result = Solver(model, cfg).solve()
                stats = result.stats.as_dict()
                writer.writerow({
                    "experiment": experiment,
                    "puzzle_id": puzzle["puzzle_id"],
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
                    "source_file": puzzle["source_file"],
                    "variant": puzzle["variant"],
                    "tier": puzzle["tier"],
                    "givens": puzzle["givens"],
                    "expected_solutions": puzzle["expected_solutions"],
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
    parser.add_argument("--puzzles", type=Path, nargs="+", default=None,
                        help=".txt or .jsonl puzzle files (default: engine/puzzles_easy.txt, "
                             "engine/puzzles_hard.txt)")
    args = parser.parse_args()
    run(args.experiment, args.limit, args.time_limit, args.output_dir, args.puzzles)


if __name__ == "__main__":
    main()
