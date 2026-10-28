"""sudoku_engine — 변형 스도쿠 CSP 알고리즘 엔진 (팀 프로젝트 ② 파트)."""

from .core import Cell, Domains, Grid, full_domains, copy_domains
from .constraints import (
    Constraint, AllDifferent, KillerCage, Thermometer, Arrow,
    Sandwich, Parity, LessThan, classic_constraints, diagonal_constraints,
)
from .model import Model
from .solver import (
    Solver, SolverConfig, SolverResult, SolverStats,
    solve, count_solutions, has_unique_solution,
)

__all__ = [
    "Cell", "Domains", "Grid", "full_domains", "copy_domains",
    "Constraint", "AllDifferent", "KillerCage", "Thermometer", "Arrow",
    "Sandwich", "Parity", "LessThan", "classic_constraints", "diagonal_constraints",
    "Model", "Solver", "SolverConfig", "SolverResult", "SolverStats",
    "solve", "count_solutions", "has_unique_solution",
]
