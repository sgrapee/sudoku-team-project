"""JSON 제약 명세 → Model 로더. ③ LLM 파서와의 인터페이스 계약.

설계 원칙
---------
입력에는 관대하게, 검증에는 엄격하게. LLM이 내놓는 JSON은 셀 표기나 키 이름이
흔들리므로 여러 표기를 받아주되, 의미가 잘못된 제약(격자 밖 좌표, 불가능한 합,
중복 케이지 등)은 확실히 거부하고 사람이 읽을 수 있는 오류 메시지를 돌려준다.
파서가 만든 제약을 그대로 믿고 풀면, 답이 없는 문제를 몇 분씩 탐색하게 된다.

JSON 스키마
-----------
{
  "size": 9, "box_rows": 3, "box_cols": 3,        // 생략 시 9x9 표준
  "givens": "53..7....6..195...",                  // 81자 문자열 또는 {"r1c1": 5} 딕셔너리
  "constraints": [
    {"type": "classic"},                            // 생략해도 기본 포함
    {"type": "diagonal"},
    {"type": "killer",   "cells": [[0,0],[0,1]], "sum": 12},
    {"type": "thermo",   "path":  [[4,4],[4,5],[4,6]]},
    {"type": "arrow",    "circle": [0,0], "path": [[0,1],[0,2]]},
    {"type": "sandwich", "line": "row", "index": 0, "sum": 15},
    {"type": "alldiff",  "cells": [[0,0],[1,1]]},
    {"type": "even",     "cells": [[3,3]]},
    {"type": "odd",      "cells": [[3,4]]},
    {"type": "lessthan", "smaller": [0,0], "larger": [0,1]}
  ]
}

셀 표기는 [row, col](0-indexed), "r1c1"(1-indexed), {"row":0,"col":0} 모두 허용.
"""

from __future__ import annotations

import json
from typing import Any

from .constraints import (
    AllDifferent,
    Arrow,
    Constraint,
    KillerCage,
    LessThan,
    Parity,
    Sandwich,
    Thermometer,
    diagonal_constraints,
)
from .core import Cell, Grid, cells_from_json
from .model import Model


class SpecError(ValueError):
    """명세가 문법적으로 잘못되었거나 의미가 성립하지 않을 때."""


# 타입 이름 표기 흔들림 흡수
_TYPE_ALIASES = {
    "classic": "classic",
    "standard": "classic",
    "normal": "classic",
    "vanilla": "classic",
    "diagonal": "diagonal",
    "sudoku_x": "diagonal",
    "x_sudoku": "diagonal",
    "killer": "killer",
    "cage": "killer",
    "killer_cage": "killer",
    "sum": "killer",
    "thermo": "thermo",
    "thermometer": "thermo",
    "arrow": "arrow",
    "sandwich": "sandwich",
    "alldiff": "alldiff",
    "alldifferent": "alldiff",
    "all_different": "alldiff",
    "unique": "alldiff",
    "even": "even",
    "odd": "odd",
    "parity": "parity",
    "lessthan": "lessthan",
    "less_than": "lessthan",
    "inequality": "lessthan",
    "greaterthan": "greaterthan",
    "greater_than": "greaterthan",
}


def _get(obj: dict, *keys: str, required: bool = True, default: Any = None) -> Any:
    for k in keys:
        if k in obj:
            return obj[k]
    if required:
        raise SpecError(f"필수 항목이 없습니다: {keys[0]} (받은 키: {sorted(obj)})")
    return default


def _validate_cells(cells: list[Cell], grid: Grid, where: str) -> None:
    if not cells:
        raise SpecError(f"{where}: 셀 목록이 비어 있습니다")
    for r, c in cells:
        if not (0 <= r < grid.size and 0 <= c < grid.size):
            raise SpecError(f"{where}: 격자 밖 좌표 ({r}, {c})")
    if len(set(cells)) != len(cells):
        raise SpecError(f"{where}: 같은 칸이 중복해서 들어 있습니다")


def _parse_givens(raw: Any, grid: Grid) -> dict[Cell, int]:
    if raw is None:
        return {}
    if isinstance(raw, str):
        return grid.parse(raw)
    if isinstance(raw, dict):
        out: dict[Cell, int] = {}
        for key, val in raw.items():
            cell = cells_from_json([key])[0]
            if not (0 <= cell[0] < grid.size and 0 <= cell[1] < grid.size):
                raise SpecError(f"givens: 격자 밖 좌표 {key}")
            out[cell] = int(val)
        return out
    if isinstance(raw, list):  # 9x9 중첩 리스트
        out = {}
        for r, row in enumerate(raw):
            for c, val in enumerate(row):
                if val in (0, None, ".", ""):
                    continue
                out[(r, c)] = int(val)
        return out
    raise SpecError(f"givens 형식을 해석할 수 없습니다: {type(raw).__name__}")


def _build_constraint(spec: dict, grid: Grid) -> list[Constraint]:
    raw_type = str(_get(spec, "type", "kind", "name")).strip().lower()
    ctype = _TYPE_ALIASES.get(raw_type)
    if ctype is None:
        raise SpecError(
            f"알 수 없는 제약 종류 '{raw_type}'. 지원 목록: "
            + ", ".join(sorted(set(_TYPE_ALIASES.values())))
        )

    if ctype == "classic":
        return []  # Model이 기본으로 넣는다
    if ctype == "diagonal":
        return diagonal_constraints(grid)

    if ctype == "killer":
        cells = cells_from_json(_get(spec, "cells", "cage"))
        _validate_cells(cells, grid, "killer")
        total = int(_get(spec, "sum", "total", "value"))
        n = len(cells)
        lo, hi = n * (n + 1) // 2, sum(range(grid.size - n + 1, grid.size + 1))
        if not lo <= total <= hi:
            raise SpecError(
                f"killer: {n}칸 케이지의 합은 {lo}~{hi} 범위여야 하는데 {total}입니다"
            )
        return [KillerCage(cells, total)]

    if ctype == "thermo":
        path = cells_from_json(_get(spec, "path", "cells", "thermo"))
        _validate_cells(path, grid, "thermo")
        if len(path) > grid.size:
            raise SpecError(f"thermo: 경로 길이 {len(path)}가 격자 크기를 넘습니다")
        return [Thermometer(path)]

    if ctype == "arrow":
        circle = cells_from_json([_get(spec, "circle", "bulb", "head")])[0]
        path = cells_from_json(_get(spec, "path", "cells", "tail"))
        _validate_cells([circle] + path, grid, "arrow")
        if len(path) * 1 > grid.size:
            raise SpecError("arrow: 경로 합이 격자 최댓값을 넘을 수 없습니다")
        return [Arrow(circle, path)]

    if ctype == "sandwich":
        if "cells" in spec or "line_cells" in spec:
            line = cells_from_json(_get(spec, "cells", "line_cells"))
        else:
            kind = str(_get(spec, "line", "orientation", "direction")).lower()
            kind = {"row": "row", "rows": "row", "col": "col", "column": "col"}.get(kind, kind)
            idx = int(_get(spec, "index", "line_index", "n"))
            if not 0 <= idx < grid.size:
                raise SpecError(f"sandwich: 줄 번호 {idx}가 범위를 벗어납니다")
            line = grid.line(kind, idx)
        _validate_cells(line, grid, "sandwich")
        total = int(_get(spec, "sum", "total", "value"))
        low = int(_get(spec, "low", required=False, default=1))
        high = int(_get(spec, "high", required=False, default=grid.size))
        max_between = sum(range(2, grid.size))  # 1과 9를 제외한 나머지 합
        if not 0 <= total <= max_between:
            raise SpecError(f"sandwich: 합은 0~{max_between} 범위여야 하는데 {total}입니다")
        return [Sandwich(line, total, low, high)]

    if ctype == "alldiff":
        cells = cells_from_json(_get(spec, "cells"))
        _validate_cells(cells, grid, "alldiff")
        if len(cells) > grid.size:
            raise SpecError(f"alldiff: {len(cells)}칸은 서로 다른 값을 가질 수 없습니다")
        return [AllDifferent(cells, spec.get("label", ""))]

    if ctype in ("even", "odd", "parity"):
        cells = cells_from_json(_get(spec, "cells"))
        _validate_cells(cells, grid, ctype)
        if ctype == "parity":
            even = bool(_get(spec, "even", required=False, default=True))
        else:
            even = ctype == "even"
        return [Parity(cells, even)]

    if ctype in ("lessthan", "greaterthan"):
        a = cells_from_json([_get(spec, "smaller", "left", "a")])[0]
        b = cells_from_json([_get(spec, "larger", "right", "b")])[0]
        _validate_cells([a, b], grid, ctype)
        if ctype == "greaterthan":
            a, b = b, a
        return [LessThan(a, b)]

    raise SpecError(f"처리되지 않은 제약 종류: {ctype}")  # pragma: no cover


def load_spec(spec: dict | str) -> Model:
    """JSON 명세(dict 또는 문자열)를 Model로 변환한다.

    잘못된 명세는 SpecError를 던진다. ③ 담당은 이 예외 메시지를 그대로
    LLM에게 되먹여 재시도시키면 된다.
    """
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except json.JSONDecodeError as exc:
            raise SpecError(f"JSON 파싱 실패: {exc}") from exc
    if not isinstance(spec, dict):
        raise SpecError("최상위는 객체(dict)여야 합니다")

    size = int(spec.get("size", 9))
    box_rows = int(spec.get("box_rows", 3 if size == 9 else 2))
    box_cols = int(spec.get("box_cols", size // box_rows))
    try:
        grid = Grid(size, box_rows, box_cols)
    except ValueError as exc:
        raise SpecError(str(exc)) from exc

    givens = _parse_givens(spec.get("givens") or spec.get("puzzle"), grid)
    for cell, v in givens.items():
        if not 1 <= v <= grid.size:
            raise SpecError(f"givens: {cell}의 값 {v}가 범위를 벗어납니다")

    raw_constraints = spec.get("constraints", [])
    if not isinstance(raw_constraints, list):
        raise SpecError("constraints는 배열이어야 합니다")

    built: list[Constraint] = []
    for i, item in enumerate(raw_constraints):
        if not isinstance(item, dict):
            raise SpecError(f"constraints[{i}]는 객체여야 합니다")
        try:
            built.extend(_build_constraint(item, grid))
        except SpecError as exc:
            raise SpecError(f"constraints[{i}] — {exc}") from exc

    model = Model(grid, built, givens, include_classic=True)

    # 단서 자체가 제약을 위반하면 즉시 알린다
    if not model.is_valid(givens):
        raise SpecError("주어진 단서가 제약을 이미 위반하고 있습니다")
    return model


def validate_spec(spec: dict | str) -> tuple[bool, str]:
    """(성립 여부, 메시지). ③ 담당의 검증 레이어가 쓰기 좋은 형태."""
    try:
        model = load_spec(spec)
    except SpecError as exc:
        return False, str(exc)
    return True, model.summary()


def spec_to_model_or_reason(spec: dict | str) -> tuple[Model | None, str]:
    """풀이 가능성까지 확인한다. 해가 없으면 그 사실을 메시지로 알린다."""
    from .solver import SolverConfig, count_solutions

    try:
        model = load_spec(spec)
    except SpecError as exc:
        return None, f"명세 오류: {exc}"
    n = count_solutions(model, limit=2, config=SolverConfig(time_limit=10.0))
    if n == 0:
        return None, "명세는 문법적으로 맞지만 해가 존재하지 않습니다"
    if n > 1:
        return model, "경고: 해가 둘 이상입니다(단서 부족)"
    return model, "유일해를 갖는 정상 명세입니다"
