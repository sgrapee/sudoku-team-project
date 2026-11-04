"""핵심 자료구조: 격자 기하 구조, 셀, 도메인.

용어
----
Cell    : (row, col) 0-indexed 튜플
Domains : dict[Cell, set[int]]  — 각 칸의 후보 숫자 집합
Unit    : 서로 다른 값을 가져야 하는 셀 묶음(행/열/박스)
"""

from __future__ import annotations

from typing import Iterable

Cell = tuple[int, int]
Domains = dict[Cell, set[int]]

BLANKS = ".0*_-"


class Grid:
    """N x N 스도쿠 격자의 기하 구조를 담는다.

    9x9 표준판은 Grid()로 충분하고, 6x6(2x3 박스) 같은 변형도 지원한다.
    """

    __slots__ = (
        "size", "box_rows", "box_cols", "values", "cells",
        "rows", "cols", "boxes", "units", "units_of", "peers",
    )

    def __init__(self, size: int = 9, box_rows: int = 3, box_cols: int = 3) -> None:
        if box_rows * box_cols != size:
            raise ValueError(f"box_rows*box_cols({box_rows*box_cols}) != size({size})")
        self.size = size
        self.box_rows = box_rows
        self.box_cols = box_cols
        self.values: tuple[int, ...] = tuple(range(1, size + 1))
        self.cells: tuple[Cell, ...] = tuple(
            (r, c) for r in range(size) for c in range(size)
        )

        self.rows: list[list[Cell]] = [
            [(r, c) for c in range(size)] for r in range(size)
        ]
        self.cols: list[list[Cell]] = [
            [(r, c) for r in range(size)] for c in range(size)
        ]
        self.boxes: list[list[Cell]] = []
        for br in range(0, size, box_rows):
            for bc in range(0, size, box_cols):
                self.boxes.append(
                    [(br + i, bc + j) for i in range(box_rows) for j in range(box_cols)]
                )

        self.units: list[list[Cell]] = self.rows + self.cols + self.boxes

        self.units_of: dict[Cell, list[list[Cell]]] = {c: [] for c in self.cells}
        for unit in self.units:
            for cell in unit:
                self.units_of[cell].append(unit)

        self.peers: dict[Cell, frozenset[Cell]] = {}
        for cell in self.cells:
            acc: set[Cell] = set()
            for unit in self.units_of[cell]:
                acc.update(unit)
            acc.discard(cell)
            self.peers[cell] = frozenset(acc)

    # ------------------------------------------------------------------ 기하
    def box_index(self, cell: Cell) -> int:
        r, c = cell
        return (r // self.box_rows) * (self.size // self.box_cols) + c // self.box_cols

    def main_diagonal(self) -> list[Cell]:
        return [(i, i) for i in range(self.size)]

    def anti_diagonal(self) -> list[Cell]:
        return [(i, self.size - 1 - i) for i in range(self.size)]

    def line(self, kind: str, index: int) -> list[Cell]:
        """kind in {'row','col'} — Sandwich 등 라인 제약용."""
        if kind == "row":
            return list(self.rows[index])
        if kind == "col":
            return list(self.cols[index])
        raise ValueError(f"알 수 없는 line kind: {kind}")

    # ------------------------------------------------------------------ 입출력
    def parse(self, text: str) -> dict[Cell, int]:
        """81자 문자열(또는 여러 줄)에서 주어진 단서를 읽는다.

        빈칸은 '.', '0', '*', '_', '-' 중 아무거나 사용 가능.
        """
        flat = [ch for ch in text if not ch.isspace() and ch != "|" and ch != "+"]
        n = self.size * self.size
        if len(flat) != n:
            raise ValueError(f"셀 개수가 {len(flat)}개입니다. {n}개여야 합니다.")
        givens: dict[Cell, int] = {}
        for idx, ch in enumerate(flat):
            if ch in BLANKS:
                continue
            if ch.isdigit():
                v = int(ch)
            else:  # 10 이상은 A=10 형태로 확장
                v = ord(ch.upper()) - ord("A") + 10
            if not 1 <= v <= self.size:
                raise ValueError(f"범위를 벗어난 값 {v} (index {idx})")
            givens[self.cells[idx]] = v
        return givens

    def to_string(self, assignment: dict[Cell, int]) -> str:
        return "".join(
            str(assignment[c]) if c in assignment else "." for c in self.cells
        )

    def render(self, assignment: dict[Cell, int]) -> str:
        """사람이 보기 좋은 격자 문자열."""
        out: list[str] = []
        for r in range(self.size):
            if r and r % self.box_rows == 0:
                out.append("-" * (self.size * 2 + (self.size // self.box_cols - 1) * 2 - 1))
            row: list[str] = []
            for c in range(self.size):
                if c and c % self.box_cols == 0:
                    row.append("|")
                v = assignment.get((r, c))
                row.append(str(v) if v else ".")
            out.append(" ".join(row))
        return "\n".join(out)

    def render_candidates(self, domains: Domains) -> str:
        """후보 숫자를 함께 보여주는 디버그용 출력."""
        width = max(len(domains.get(c, set())) for c in self.cells)
        width = max(width, 1)
        lines: list[str] = []
        for r in range(self.size):
            cells = []
            for c in range(self.size):
                d = sorted(domains.get((r, c), set()))
                cells.append("".join(map(str, d)).ljust(width))
            lines.append(" ".join(cells))
        return "\n".join(lines)


# ---------------------------------------------------------------------- 도메인
def full_domains(grid: Grid, givens: dict[Cell, int] | None = None) -> Domains:
    """모든 칸을 전체 후보로 채우고, 단서 칸은 단일 값으로 고정한다."""
    givens = givens or {}
    domains: Domains = {}
    for cell in grid.cells:
        if cell in givens:
            domains[cell] = {givens[cell]}
        else:
            domains[cell] = set(grid.values)
    return domains


def copy_domains(domains: Domains) -> Domains:
    return {cell: set(vals) for cell, vals in domains.items()}


def solved_assignment(domains: Domains) -> dict[Cell, int] | None:
    """모든 도메인이 단일값이면 해 딕셔너리를, 아니면 None을 돌려준다."""
    out: dict[Cell, int] = {}
    for cell, vals in domains.items():
        if len(vals) != 1:
            return None
        out[cell] = next(iter(vals))
    return out


def partial_assignment(domains: Domains) -> dict[Cell, int]:
    """단일값으로 확정된 칸만 모은다."""
    return {cell: next(iter(v)) for cell, v in domains.items() if len(v) == 1}


def count_unsolved(domains: Domains) -> int:
    return sum(1 for v in domains.values() if len(v) > 1)


def cells_from_json(raw: Iterable) -> list[Cell]:
    """[[r,c], ...] 또는 ['r1c1', ...] 형태를 모두 받아 Cell 리스트로 정규화한다.

    LLM 파서(③)가 어느 쪽 표기를 내놓아도 받아들이기 위한 관용 처리.
    """
    out: list[Cell] = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            out.append((int(item[0]), int(item[1])))
        elif isinstance(item, str):
            s = item.strip().lower()
            if s.startswith("r") and "c" in s:
                r_part, c_part = s[1:].split("c", 1)
                # 스도쿠 관례상 r1c1이 1-indexed이므로 0-indexed로 변환
                out.append((int(r_part) - 1, int(c_part) - 1))
            else:
                raise ValueError(f"셀 표기를 해석할 수 없습니다: {item!r}")
        elif isinstance(item, dict) and "row" in item and "col" in item:
            out.append((int(item["row"]), int(item["col"])))
        else:
            raise ValueError(f"셀 표기를 해석할 수 없습니다: {item!r}")
    return out
