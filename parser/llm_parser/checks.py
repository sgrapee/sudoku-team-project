"""검증 계층: JSON 추출 → 엔진 검증(안전 래퍼) → 그럴듯함 검사.

엔진의 validate_spec은 SpecError만 잡기 때문에, LLM이 "R1-C1" 같은 표기나 "열둘" 같은
값을 내면 ValueError로 크래시한다. 재시도 루프가 멈추지 않도록 모든 예외를
"거부 사유 문자열"로 바꾼다.

그럴듯함 검사는 엔진이 문법상 통과시키지만 실제 퍼즐에서는 거의 항상 파싱 실수인
패턴(케이지 겹침, 떨어진 케이지, 끊긴 경로, 떨어진 부등호)을 잡는다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sudoku_engine.core import cells_from_json
from sudoku_engine.spec import _TYPE_ALIASES, validate_spec

Cell = tuple[int, int]


class OutputFormatError(ValueError):
    """LLM 출력이 약속한 최상위 형식이 아닐 때."""


def extract_json(text: str) -> dict:
    """LLM 응답에서 JSON 객체를 꺼낸다. 코드펜스나 앞뒤 잡담을 허용한다."""
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end <= start:
        raise OutputFormatError("응답에서 JSON 객체를 찾지 못했습니다. JSON 객체 하나만 출력하세요.")
    try:
        obj = json.loads(s[start : end + 1])
    except json.JSONDecodeError as exc:
        raise OutputFormatError(f"JSON 문법 오류: {exc.msg} (위치 {exc.pos})") from exc
    if not isinstance(obj, dict):
        raise OutputFormatError("최상위는 JSON 객체여야 합니다.")
    return obj


def split_output(obj: dict) -> tuple[dict, list[str]]:
    """LLM 출력 → (엔진에 넘길 명세, unsupported 목록)."""
    constraints = obj.get("constraints", [])
    if constraints is None:
        constraints = []
    if not isinstance(constraints, list):
        raise OutputFormatError("constraints는 배열이어야 합니다.")
    unsupported = obj.get("unsupported", []) or []
    if not isinstance(unsupported, list):
        unsupported = [str(unsupported)]
    return {"constraints": constraints}, [str(u) for u in unsupported]


def safe_validate(spec: dict | str) -> tuple[bool, str]:
    """validate_spec을 감싸서 어떤 입력에도 크래시하지 않는다."""
    try:
        return validate_spec(spec)
    except Exception as exc:  # noqa: BLE001 — 모든 예외를 거부 사유로 바꾸는 것이 목적
        return False, f"명세를 해석할 수 없습니다 ({type(exc).__name__}): {exc}"


# ---------------------------------------------------------------- 그럴듯함 검사

def _ctype(item: dict) -> str | None:
    raw = item.get("type", item.get("kind", item.get("name", "")))
    return _TYPE_ALIASES.get(str(raw).strip().lower())


def _cells(raw: Any) -> list[Cell]:
    return cells_from_json(raw)


def _cell(raw: Any) -> Cell:
    return cells_from_json([raw])[0]


def _king_adjacent(a: Cell, b: Cell) -> bool:
    return a != b and abs(a[0] - b[0]) <= 1 and abs(a[1] - b[1]) <= 1


def _ortho_adjacent(a: Cell, b: Cell) -> bool:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1


def _connected(cells: list[Cell]) -> bool:
    todo, seen = [cells[0]], {cells[0]}
    pool = set(cells)
    while todo:
        r, c = todo.pop()
        for n in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if n in pool and n not in seen:
                seen.add(n)
                todo.append(n)
    return len(seen) == len(pool)


def _rc(cell: Cell) -> str:
    return f"r{cell[0] + 1}c{cell[1] + 1}"


def _chain_break(path: list[Cell]) -> str | None:
    for a, b in zip(path, path[1:]):
        if not _king_adjacent(a, b):
            return f"{_rc(a)}와 {_rc(b)}가 이웃하지 않습니다"
    return None


def plausibility_problems(spec: dict) -> list[str]:
    """엔진은 통과시키지만 실제 퍼즐에서는 파싱 실수일 가능성이 높은 패턴 목록.

    엔진 검증(safe_validate)을 통과한 명세에만 호출한다고 가정한다.
    """
    problems: list[str] = []
    cage_owner: dict[Cell, int] = {}

    for i, item in enumerate(spec.get("constraints", [])):
        where = f"constraints[{i}]"

        t = _ctype(item)
        try:
            if t == "killer":
                cells = _cells(item.get("cells", item.get("cage")))
                for c in cells:
                    if c in cage_owner:
                        problems.append(
                            f"{where}: 킬러 케이지가 constraints[{cage_owner[c]}]와 "
                            f"{_rc(c)} 칸을 공유합니다(케이지는 겹치지 않아야 함)"
                        )
                        break
                for c in cells:
                    cage_owner.setdefault(c, i)
                if not _connected(cells):
                    problems.append(
                        f"{where}: 킬러 케이지 칸들이 상하좌우로 이어져 있지 않습니다 "
                        f"({', '.join(_rc(c) for c in cells)}). 좌표를 다시 확인하세요"
                    )
            elif t == "thermo":
                path = _cells(item.get("path", item.get("cells", item.get("thermo"))))
                if len(path) < 2:
                    problems.append(f"{where}: 온도계는 최소 2칸이어야 합니다")
                elif (msg := _chain_break(path)):
                    problems.append(f"{where}: 온도계 경로가 끊겼습니다 — {msg}")
            elif t == "arrow":
                circle = _cell(item.get("circle", item.get("bulb", item.get("head"))))
                path = _cells(item.get("path", item.get("cells", item.get("tail"))))
                if (msg := _chain_break([circle] + path)):
                    problems.append(f"{where}: 화살표가 원에서 이어지지 않습니다 — {msg}")
            elif t in ("lessthan", "greaterthan"):
                a = _cell(item.get("smaller", item.get("left", item.get("a"))))
                b = _cell(item.get("larger", item.get("right", item.get("b"))))
                if not _ortho_adjacent(a, b):
                    problems.append(
                        f"{where}: 부등호의 두 칸 {_rc(a)}, {_rc(b)}가 상하좌우로 붙어 있지 않습니다"
                    )
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{where}: 좌표를 해석할 수 없습니다 ({exc})")

    # 표기가 달라도 의미가 같은 제약이 두 번 나오면 중복 (예: even [r4c4,r4c5] + even [r4c4])
    from .canonical import canonical_items

    try:
        dups = [k for k, n in canonical_items(spec).items() if n > 1]
    except Exception:  # noqa: BLE001
        dups = []
    if dups:
        problems.append(f"의미가 같은 제약이 {len(dups)}건 중복되었습니다. 같은 제약은 한 번만 출력하세요")
    return problems


def extract_givens(text: str) -> str | None:
    """퍼즐 설명 문장 안의 단서 격자를 코드로 꺼낸다(LLM에게 81칸을 옮겨 적게 하지 않는다).

    지원 형식: 9자씩 9줄(공백·| 구분 허용) 또는 81자 한 줄. 빈칸은 '.' 또는 '0' → '.'로 통일.
    여러 개가 있으면 마지막 것을 쓴다. 없으면 None.
    """
    lines = [re.sub(r"[\s|]", "", ln) for ln in text.splitlines()]
    found: list[str] = []
    for ln in lines:
        if re.fullmatch(r"[0-9.]{81}", ln):
            found.append(ln)
    for i in range(len(lines) - 8):
        block = lines[i:i + 9]
        if all(re.fullmatch(r"[0-9.]{9}", b) for b in block):
            found.append("".join(block))
    if not found:
        return None
    return found[-1].replace("0", ".")
