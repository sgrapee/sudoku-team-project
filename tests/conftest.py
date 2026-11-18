"""Shared fixtures for tests of the root-level analysis scripts.

Run from the repository root:
    python -m pytest -q tests
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pytest

# Headless backend so the plotting tests also run on CI / without a display.
os.environ.setdefault("MPLBACKEND", "Agg")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Column order written by run_bench.py (run() -> fields).
RAW_FIELDS = [
    "experiment", "puzzle_id", "config", "var_order", "val_order",
    "propagation", "solved", "timed_out", "solutions_found", "nodes",
    "branch_nodes", "backtracks", "assignments", "elapsed_ms",
    "source_file", "variant", "tier", "givens", "expected_solutions",
]


def _raw_row(config: str = "mrv_asc_fc", puzzle_id: str = "p1", *, solved: bool = True,
             timed_out: bool = False, branch_nodes=10, elapsed_ms=1.0, tier="easy",
             givens=30, expected_solutions=1, solutions_found=None, **extra) -> dict[str, str]:
    """One run_bench-style row, already stringified as csv.DictReader would return it."""
    if solutions_found is None:
        solutions_found = 1 if solved else 0
    row = {
        "experiment": "E2", "puzzle_id": puzzle_id, "config": config,
        "var_order": "mrv", "val_order": "asc", "propagation": config.rsplit("_", 1)[-1],
        "solved": solved, "timed_out": timed_out, "solutions_found": solutions_found,
        "nodes": branch_nodes, "branch_nodes": branch_nodes, "backtracks": 0,
        "assignments": 0, "elapsed_ms": elapsed_ms, "source_file": "test.jsonl",
        "variant": "classic", "tier": tier, "givens": givens,
        "expected_solutions": expected_solutions,
    }
    row.update(extra)
    return {k: str(v) for k, v in row.items()}


@pytest.fixture
def raw_row():
    return _raw_row


@pytest.fixture
def make_raw_csv(tmp_path):
    """Write rows the same way run_bench.py does (utf-8-sig, DictWriter)."""

    def _make(rows, name: str = "E2_raw.csv", fields=None, encoding: str = "utf-8-sig") -> Path:
        path = tmp_path / name
        with path.open("w", newline="", encoding=encoding) as f:
            writer = csv.DictWriter(f, fieldnames=fields or RAW_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    return _make


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def read_out_csv():
    return read_csv
