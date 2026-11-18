"""datagen 공용 코드: 경로, 엔진 import 경로 설정, jsonl 입출력, 좌표 표기.

각 스크립트는 `python datagen/xxx.py`로 실행하므로 이 모듈을 `import common`으로 불러온다.
엔진(sudoku_engine)보다 먼저 import해야 `engine/`이 import 경로에 들어간다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUZZLES_DIR = ROOT / "puzzles"

# 엔진은 설치하지 않고 engine/ 을 import 경로에 직접 추가한다.
_ENGINE_DIR = str(ROOT / "engine")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)


# ------------------------------------------------------------------ jsonl
def dump_line(rec: dict) -> str:
    """레코드 하나를 jsonl 한 줄(개행 포함)로."""
    return json.dumps(rec, ensure_ascii=False) + "\n"


def read_jsonl(path: Path) -> list[dict]:
    """빈 줄을 건너뛰고 한 줄에 하나씩 읽는다."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(dump_line(rec))


# ------------------------------------------------------------------ 좌표 표기
def fmt_cell(cell: list[int], style: str = "rc") -> str:
    """0부터 센 [행, 열]을 1부터 센 표기로. style: rc("r3c2") / korean("3행 2열") / paren("(3, 2)")."""
    r, c = cell[0] + 1, cell[1] + 1
    if style == "rc":
        return f"r{r}c{c}"
    if style == "korean":
        return f"{r}행 {c}열"
    return f"({r}, {c})"


def fmt_cells(cells: list[list[int]], style: str = "rc", sep: str = ", ") -> str:
    return sep.join(fmt_cell(c, style) for c in cells)
