"""엔진과 독립된 변형 스도쿠 결과 검증기.

이 파일은 ``sudoku_engine``을 import하지 않는다. 결과 JSON의 ``givens``,
``constraints``, ``actual_solution``을 직접 해석하고 규칙 정의를 별도로 구현한다.

독립성의 범위
-------------
- 규칙 계산(합, 증가, 중복, 짝·홀, 부등호, 샌드위치)은 엔진 코드를 보지 않고 새로 구현했다.
- 입력 스키마(키 이름, 좌표 표기)는 엔진과 파서가 공유하는 명세 형식을 따른다.
  형식이 같아야 같은 결과 파일을 읽을 수 있기 때문이다. 다만 엔진의 관대한 기본값은
  가져오지 않는다: 값이 애매하면 추측하지 않고 "판정 불가"로 돌려준다.

판정 규칙
---------
- 규칙 위반이 하나라도 확인되면 "규칙 위반"이다. 검사하지 못한 항목이 함께 있어도
  격자가 틀렸다는 사실은 바뀌지 않으므로 위반이 우선한다.
- 위반이 없지만 검사하지 못한 항목(형식 오류, 모르는 규칙, 적용 안 된 규칙)이 있으면 "판정 불가"다.
- 둘 다 없으면 "정답"이다.

검증 범위
---------
- 완성 격자가 명세의 단서와 규칙을 지키는지 검사한다.
- 자연어가 올바른 명세로 변환됐는지는 검사하지 않는다.
- 해의 유일성은 검사하지 않는다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


STATUS_CORRECT = "correct"
STATUS_VIOLATION = "violation"
STATUS_UNVERIFIABLE = "unverifiable"
STATUS_LABELS = {
    STATUS_CORRECT: "정답",
    STATUS_VIOLATION: "규칙 위반",
    STATUS_UNVERIFIABLE: "판정 불가",
}

# 명세 형식에서 쓰는 type 이름과 별칭 → 검사 규칙 이름
TYPE_ALIASES = {
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
SUPPORTED_TYPES = set(TYPE_ALIASES.values())

Cell = tuple[int, int]


class InputFormatError(ValueError):
    """검사할 수 없는 입력 형식 또는 명세를 나타낸다."""


def _issue(
    rule: str,
    message: str,
    *,
    cells: list[Cell] | None = None,
    expected: Any = None,
    actual: Any = None,
    constraint_index: int | None = None,
) -> dict[str, Any]:
    return {
        "rule": rule,
        "message": message,
        "cells": [_cell_name(cell) for cell in (cells or [])],
        "expected": expected,
        "actual": actual,
        "constraint_index": constraint_index,
    }


def _cell_name(cell: Cell) -> str:
    return f"r{cell[0] + 1}c{cell[1] + 1}"


# --------------------------------------------------------------------------- 값 해석

def _to_int(raw: Any, label: str) -> int:
    """정수만 받는다. 12.9를 12로 자르는 식의 추측은 하지 않는다."""
    if isinstance(raw, bool):
        raise InputFormatError(f"{label}: 정수가 필요하지만 {raw!r}입니다.")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        if raw.is_integer():
            return int(raw)
        raise InputFormatError(f"{label}: 정수가 필요하지만 {raw!r}입니다.")
    if isinstance(raw, str) and re.fullmatch(r"\s*[+-]?\d+\s*", raw):
        return int(raw)
    raise InputFormatError(f"{label}: 정수가 필요하지만 {raw!r}입니다.")


_TRUE_WORDS = {"true", "yes", "1", "even", "짝수"}
_FALSE_WORDS = {"false", "no", "0", "odd", "홀수"}


def _to_bool(raw: Any, label: str) -> bool:
    """참·거짓만 받는다. 문자열 "false"를 참으로 읽는 bool() 함정을 피한다."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str):
        word = raw.strip().lower()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
    raise InputFormatError(f"{label}: 참/거짓 값이 필요하지만 {raw!r}입니다.")


def _parse_cell(raw: Any, label: str = "cell") -> Cell:
    if isinstance(raw, str):
        match = re.fullmatch(r"\s*[rR]([1-9])\s*[cC]([1-9])\s*", raw)
        if not match:
            raise InputFormatError(f"{label}: 좌표는 r1c1~r9c9 형식이어야 합니다: {raw!r}")
        return int(match.group(1)) - 1, int(match.group(2)) - 1

    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        row = _to_int(raw[0], f"{label} 행")
        col = _to_int(raw[1], f"{label} 열")
        if not (0 <= row < 9 and 0 <= col < 9):
            raise InputFormatError(f"{label}: 0-based 좌표 범위를 벗어났습니다: {raw!r}")
        return row, col

    if isinstance(raw, dict) and "row" in raw and "col" in raw:
        return _parse_cell([raw["row"], raw["col"]], label)

    raise InputFormatError(f"{label}: 지원하지 않는 좌표 형식입니다: {raw!r}")


def _parse_cells(raw: Any, label: str, *, min_len: int = 1) -> list[Cell]:
    if not isinstance(raw, list) or not raw:
        raise InputFormatError(f"{label}: 하나 이상의 좌표 목록이 필요합니다.")
    cells = [_parse_cell(item, label) for item in raw]
    if len(set(cells)) != len(cells):
        raise InputFormatError(f"{label}: 같은 칸이 중복되어 있습니다.")
    if len(cells) < min_len:
        raise InputFormatError(f"{label}: 최소 {min_len}칸이 필요하지만 {len(cells)}칸입니다.")
    return cells


def _required(spec: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in spec:
            return spec[name]
    raise InputFormatError(f"필수 필드가 없습니다: {'/'.join(names)}")


def _parse_grid(raw: Any) -> list[int]:
    if isinstance(raw, str):
        text = "".join(raw.split())
        if len(text) != 81:
            raise InputFormatError(f"actual_solution은 81칸이어야 하지만 {len(text)}칸입니다.")
        if any(ch not in "123456789" for ch in text):
            raise InputFormatError("actual_solution에는 1~9 이외의 값이 있습니다.")
        return [int(ch) for ch in text]

    if isinstance(raw, list):
        flat: list[Any] = []
        for item in raw:
            flat.extend(item if isinstance(item, list) else [item])
        if len(flat) != 81:
            raise InputFormatError(f"actual_solution은 81칸이어야 하지만 {len(flat)}칸입니다.")
        values: list[int] = []
        for item in flat:
            try:
                value = _to_int(item, "actual_solution")
            except InputFormatError as exc:
                raise InputFormatError("actual_solution에는 1~9 이외의 값이 있습니다.") from exc
            if not 1 <= value <= 9:
                raise InputFormatError("actual_solution에는 1~9 이외의 값이 있습니다.")
            values.append(value)
        return values

    raise InputFormatError("actual_solution은 81자 문자열 또는 9×9 배열이어야 합니다.")


_EMPTY_GIVENS = (None, 0, "0", ".", "")


def _parse_givens(raw: Any) -> dict[Cell, int]:
    if isinstance(raw, str):
        text = "".join(raw.split())
        if len(text) != 81:
            raise InputFormatError(f"givens는 81칸이어야 하지만 {len(text)}칸입니다.")
        if any(ch not in ".0123456789" for ch in text):
            raise InputFormatError("givens에는 '.', '0', 1~9만 사용할 수 있습니다.")
        return {
            (index // 9, index % 9): int(ch)
            for index, ch in enumerate(text)
            if ch not in ".0"
        }

    if isinstance(raw, dict):
        givens: dict[Cell, int] = {}
        for key, value in raw.items():
            cell = _parse_cell(key, "given")
            digit = _to_int(value, f"given {_cell_name(cell)}")
            if not 1 <= digit <= 9:
                raise InputFormatError(f"given {_cell_name(cell)} 값은 1~9여야 합니다.")
            givens[cell] = digit
        return givens

    if isinstance(raw, list):  # 9×9 중첩 배열, 빈칸은 0 / None / "." / ""
        if len(raw) != 9 or any(not isinstance(row, (list, tuple)) or len(row) != 9 for row in raw):
            raise InputFormatError("givens 배열은 9×9여야 합니다.")
        givens = {}
        for r, row in enumerate(raw):
            for c, value in enumerate(row):
                if value in _EMPTY_GIVENS and not isinstance(value, bool):
                    continue
                digit = _to_int(value, f"given r{r + 1}c{c + 1}")
                if not 1 <= digit <= 9:
                    raise InputFormatError(f"given r{r + 1}c{c + 1} 값은 1~9여야 합니다.")
                givens[(r, c)] = digit
        return givens

    raise InputFormatError("givens는 81자 문자열, 좌표-값 객체 또는 9×9 배열이어야 합니다.")


def _unsupported_reason(raw: Any) -> dict[str, Any] | None:
    """LLM이 '적용 안 된 규칙'으로 보고한 내용이 있으면 판정 불가 사유를 만든다."""
    if raw in (None, False, "", []):
        return None
    if isinstance(raw, list):
        detail = "; ".join(str(item) for item in raw)
    elif raw is True:
        detail = "명세에 넣지 못한 규칙이 있음"
    else:
        detail = str(raw)
    return _issue(
        "unsupported",
        f"명세에 반영되지 않은 규칙이 있어 퍼즐 전체를 검사할 수 없습니다: {detail}",
    )


# --------------------------------------------------------------------------- 규칙 검사

def _value(grid: list[int], cell: Cell) -> int:
    return grid[cell[0] * 9 + cell[1]]


def _values(grid: list[int], cells: list[Cell]) -> list[int]:
    return [_value(grid, cell) for cell in cells]


def _all_different_issue(
    grid: list[int], cells: list[Cell], rule: str, location: str, index: int | None = None
) -> dict[str, Any] | None:
    values = _values(grid, cells)
    if len(values) == len(set(values)):
        return None
    return _issue(
        rule,
        f"{location}에서 숫자가 중복됩니다.",
        cells=cells,
        expected="모든 값이 서로 다름",
        actual=values,
        constraint_index=index,
    )


def _validate_classic(grid: list[int]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for row in range(9):
        cells = [(row, col) for col in range(9)]
        issue = _all_different_issue(grid, cells, "classic.row", f"{row + 1}행")
        if issue:
            issues.append(issue)
    for col in range(9):
        cells = [(row, col) for row in range(9)]
        issue = _all_different_issue(grid, cells, "classic.column", f"{col + 1}열")
        if issue:
            issues.append(issue)
    for box_row in range(3):
        for box_col in range(3):
            cells = [
                (row, col)
                for row in range(box_row * 3, box_row * 3 + 3)
                for col in range(box_col * 3, box_col * 3 + 3)
            ]
            issue = _all_different_issue(
                grid,
                cells,
                "classic.box",
                f"박스({box_row + 1},{box_col + 1})",
            )
            if issue:
                issues.append(issue)
    return issues


def _constraint_kind(spec: dict[str, Any], index: int) -> str:
    raw = None
    for key in ("type", "kind", "name"):
        if key in spec:
            raw = spec[key]
            break
    if raw is None or not str(raw).strip():
        raise InputFormatError(f"constraints[{index}]에 type이 없습니다.")
    raw_type = str(raw).strip().lower()
    kind = TYPE_ALIASES.get(raw_type)
    if kind is None:
        raise InputFormatError(f"constraints[{index}]의 알 수 없는 type: {raw_type}")
    return kind


def _validate_constraint(
    grid: list[int], spec: dict[str, Any], index: int
) -> list[dict[str, Any]]:
    kind = _constraint_kind(spec, index)
    if kind == "classic":
        return []

    issues: list[dict[str, Any]] = []

    if kind == "diagonal":
        diagonals = (
            ([(i, i) for i in range(9)], "주대각선"),
            ([(i, 8 - i) for i in range(9)], "부대각선"),
        )
        for cells, label in diagonals:
            issue = _all_different_issue(grid, cells, "diagonal", label, index)
            if issue:
                issues.append(issue)
        return issues

    if kind == "killer":
        cells = _parse_cells(_required(spec, "cells", "cage"), f"killer[{index}]")
        target = _to_int(_required(spec, "sum", "total", "value"), f"killer[{index}].sum")
        values = _values(grid, cells)
        actual_sum = sum(values)
        if actual_sum != target:
            issues.append(_issue(
                "killer.sum",
                f"킬러 케이지 합이 {target}이 아닙니다.",
                cells=cells,
                expected=target,
                actual=actual_sum,
                constraint_index=index,
            ))
        if len(values) != len(set(values)):
            issues.append(_issue(
                "killer.distinct",
                "킬러 케이지 안에 중복 숫자가 있습니다.",
                cells=cells,
                expected="케이지 안의 모든 값이 서로 다름",
                actual=values,
                constraint_index=index,
            ))
        return issues

    if kind == "thermo":
        cells = _parse_cells(
            _required(spec, "path", "cells", "thermo"), f"thermo[{index}]", min_len=2
        )
        values = _values(grid, cells)
        bad = [i for i in range(len(values) - 1) if values[i] >= values[i + 1]]
        if bad:
            involved = sorted({pos for i in bad for pos in (i, i + 1)})
            issues.append(_issue(
                "thermo",
                "온도계 값이 구근부터 끝까지 엄격하게 증가하지 않습니다.",
                cells=[cells[pos] for pos in involved],
                expected="각 다음 값이 이전 값보다 큼",
                actual=values,
                constraint_index=index,
            ))
        return issues

    if kind == "arrow":
        circle = _parse_cell(_required(spec, "circle", "bulb", "head"), f"arrow[{index}].circle")
        path = _parse_cells(_required(spec, "path", "cells", "tail"), f"arrow[{index}].path")
        if circle in path:
            raise InputFormatError(f"arrow[{index}]: 원 {_cell_name(circle)}이 화살표 경로에 들어 있습니다.")
        circle_value = _value(grid, circle)
        path_sum = sum(_values(grid, path))
        if circle_value != path_sum:
            issues.append(_issue(
                "arrow",
                "화살표 원의 값이 경로 숫자의 합과 다릅니다.",
                cells=[circle] + path,
                expected=path_sum,
                actual=circle_value,
                constraint_index=index,
            ))
        return issues

    if kind == "sandwich":
        if "cells" in spec or "line_cells" in spec:
            cells = _parse_cells(
                _required(spec, "cells", "line_cells"), f"sandwich[{index}]", min_len=2
            )
        else:
            line = str(_required(spec, "line", "orientation", "direction", "axis")).strip().lower()
            index_value = _to_int(
                _required(spec, "index", "line_index", "n"), f"sandwich[{index}].index"
            )
            if not 0 <= index_value < 9:
                raise InputFormatError(f"sandwich[{index}]: index는 0~8이어야 합니다.")
            if line in ("row", "rows"):
                cells = [(index_value, col) for col in range(9)]
            elif line in ("col", "cols", "column", "columns"):
                cells = [(row, index_value) for row in range(9)]
            else:
                raise InputFormatError(f"sandwich[{index}]: line은 row 또는 col이어야 합니다.")
        target = _to_int(_required(spec, "sum", "total", "value"), f"sandwich[{index}].sum")
        low = _to_int(spec.get("low", 1), f"sandwich[{index}].low")
        high = _to_int(spec.get("high", 9), f"sandwich[{index}].high")
        if low == high:
            raise InputFormatError(f"sandwich[{index}]: low와 high가 같습니다.")
        values = _values(grid, cells)
        if values.count(low) != 1 or values.count(high) != 1:
            # 격자의 문제이지 명세의 문제가 아니므로 위반으로 센다.
            issues.append(_issue(
                "sandwich.bounds",
                f"샌드위치 줄에 경계값 {low}, {high}가 각각 한 번씩 있어야 합니다.",
                cells=cells,
                expected=f"{low} 한 번, {high} 한 번",
                actual=f"{low} {values.count(low)}번, {high} {values.count(high)}번",
                constraint_index=index,
            ))
            return issues
        first, second = sorted((values.index(low), values.index(high)))
        actual_sum = sum(values[first + 1:second])
        if actual_sum != target:
            issues.append(_issue(
                "sandwich",
                "샌드위치 경계값 사이의 합이 다릅니다.",
                cells=cells,
                expected=target,
                actual=actual_sum,
                constraint_index=index,
            ))
        return issues

    if kind == "alldiff":
        cells = _parse_cells(_required(spec, "cells"), f"alldiff[{index}]")
        issue = _all_different_issue(grid, cells, "alldiff", "지정된 칸", index)
        return [issue] if issue else []

    if kind in ("even", "odd", "parity"):
        cells = _parse_cells(_required(spec, "cells"), f"{kind}[{index}]")
        if kind == "parity":
            # 엔진처럼 '없으면 짝수'로 추측하지 않는다.
            if "even" in spec:
                even = _to_bool(spec["even"], f"parity[{index}].even")
            elif "parity" in spec:
                even = _to_bool(spec["parity"], f"parity[{index}].parity")
            else:
                raise InputFormatError(f"parity[{index}]: even 또는 parity 값이 없습니다.")
        else:
            even = kind == "even"
        bad_cells = [cell for cell in cells if (_value(grid, cell) % 2 == 0) != even]
        if bad_cells:
            issues.append(_issue(
                "parity.even" if even else "parity.odd",
                "지정된 칸의 짝수/홀수 조건을 만족하지 않습니다.",
                cells=bad_cells,
                expected="짝수" if even else "홀수",
                actual=[_value(grid, cell) for cell in bad_cells],
                constraint_index=index,
            ))
        return issues

    if kind in ("lessthan", "greaterthan"):
        left = _parse_cell(_required(spec, "smaller", "left", "a"), f"{kind}[{index}].left")
        right = _parse_cell(_required(spec, "larger", "right", "b"), f"{kind}[{index}].right")
        if left == right:
            raise InputFormatError(f"{kind}[{index}]: 두 칸이 같습니다: {_cell_name(left)}")
        left_value, right_value = _value(grid, left), _value(grid, right)
        valid = left_value < right_value if kind == "lessthan" else left_value > right_value
        if not valid:
            symbol = "<" if kind == "lessthan" else ">"
            issues.append(_issue(
                kind,
                f"부등호 방향을 만족하지 않습니다: {_cell_name(left)} {symbol} {_cell_name(right)}",
                cells=[left, right],
                expected=f"{_cell_name(left)} {symbol} {_cell_name(right)}",
                actual=f"{left_value} {symbol} {right_value} (거짓)",
                constraint_index=index,
            ))
        return issues

    raise InputFormatError(f"constraints[{index}]: 처리되지 않은 type: {kind}")  # pragma: no cover


# --------------------------------------------------------------------------- 진입점

def validate_payload(data: Any) -> dict[str, Any]:
    """결과 JSON 객체를 검사하고 직렬화 가능한 보고서를 반환한다."""
    title = "이름 없음"
    if isinstance(data, dict):
        title = str(data.get("title") or data.get("puzzle") or title)

    report: dict[str, Any] = {
        "status": STATUS_UNVERIFIABLE,
        "status_label": STATUS_LABELS[STATUS_UNVERIFIABLE],
        "puzzle": title,
        "violations": [],
        "unverifiable_reasons": [],
        "summary": {
            "givens_checked": 0,
            "givens_changed": 0,
            "constraints_declared": 0,
            "constraints_checked": 0,
            "violation_count": 0,
        },
    }

    if not isinstance(data, dict):
        report["unverifiable_reasons"].append(_issue("input", "결과 JSON은 객체여야 합니다."))
        return report

    try:
        grid = _parse_grid(data.get("actual_solution"))
        givens = _parse_givens(data.get("givens"))
    except InputFormatError as exc:
        report["unverifiable_reasons"].append(_issue("input", str(exc)))
        return report

    violations: list[dict[str, Any]] = []
    unverifiable: list[dict[str, Any]] = []

    # constraints 키가 없으면 변형 규칙이 빠진 것인지 알 수 없다. 클래식만이면 []를 명시해야 한다.
    if "constraints" not in data:
        constraints: list[Any] = []
        unverifiable.append(_issue(
            "input",
            "constraints 키가 없습니다. 변형 규칙이 없는 퍼즐이면 빈 배열 []을 넣으세요.",
        ))
    else:
        constraints = data["constraints"]
        if not isinstance(constraints, list):
            report["unverifiable_reasons"].append(_issue("input", "constraints는 배열이어야 합니다."))
            return report

    for key in ("unsupported", "unsupported_rules"):
        reason = _unsupported_reason(data.get(key))
        if reason:
            unverifiable.append(reason)

    report["summary"]["givens_checked"] = len(givens)
    report["summary"]["constraints_declared"] = len(constraints)

    for cell, expected in givens.items():
        actual = _value(grid, cell)
        if actual != expected:
            violations.append(_issue(
                "given",
                f"단서 {_cell_name(cell)}의 값이 변경되었습니다.",
                cells=[cell],
                expected=expected,
                actual=actual,
            ))

    violations.extend(_validate_classic(grid))

    checked = 0
    for index, constraint in enumerate(constraints):
        if not isinstance(constraint, dict):
            unverifiable.append(_issue(
                "constraint", f"constraints[{index}]는 객체여야 합니다.", constraint_index=index
            ))
            continue
        try:
            violations.extend(_validate_constraint(grid, constraint, index))
            checked += 1
        except (InputFormatError, TypeError, ValueError) as exc:
            unverifiable.append(_issue(
                "constraint",
                str(exc),
                constraint_index=index,
            ))

    report["violations"] = violations
    report["unverifiable_reasons"] = unverifiable
    report["summary"]["givens_changed"] = sum(1 for issue in violations if issue["rule"] == "given")
    report["summary"]["constraints_checked"] = checked
    report["summary"]["violation_count"] = len(violations)

    # 위반이 확인되면 격자는 틀린 것이다. 검사 못 한 항목이 있어도 위반이 우선한다.
    if violations:
        status = STATUS_VIOLATION
    elif unverifiable:
        status = STATUS_UNVERIFIABLE
    else:
        status = STATUS_CORRECT
    report["status"] = status
    report["status_label"] = STATUS_LABELS[status]
    return report


def validate_file(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return validate_payload({"title": source.name, "actual_solution": None, "givens": None}) | {
            "unverifiable_reasons": [_issue("input", f"파일을 찾을 수 없습니다: {source}")]
        }
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return validate_payload({"title": source.name, "actual_solution": None, "givens": None}) | {
            "unverifiable_reasons": [_issue("input", f"올바른 JSON이 아닙니다: {exc}")]
        }
    return validate_payload(data)


def write_report(report: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
