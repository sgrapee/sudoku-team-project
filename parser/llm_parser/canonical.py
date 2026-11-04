"""명세 정규화 — 표기가 달라도 의미가 같으면 같은 제약으로 본다.

파싱 정확도를 문자열 비교로 재면 "r1c1"과 [0,0], greaterthan과 뒤집힌 lessthan,
even 한 묶음과 칸별 even이 전부 다르게 잡힌다. 그래서 모든 제약을 의미 단위 튜플로
바꾼 뒤 멀티셋으로 비교한다.

  killer   → ("killer", 칸 집합, 합)
  thermo   → ("thermo", 칸 순서)          순서가 의미를 가짐(전구 → 끝)
  arrow    → ("arrow", 원, 칸 집합)       경로 칸은 합만 의미가 있으므로 집합
  sandwich → ("sandwich", 줄 칸 집합, 합)
  alldiff  → ("alldiff", 칸 집합)
  even/odd → 칸마다 ("parity", 칸, 짝수 여부)   묶음 방식과 무관하게 비교
  부등호   → ("lessthan", 작은 칸, 큰 칸)
  diagonal → ("diagonal",)
  classic  → 제외(항상 포함)
"""

from __future__ import annotations

from collections import Counter

from sudoku_engine.core import Grid, cells_from_json
from sudoku_engine.spec import _TYPE_ALIASES

_GRID = Grid()


def _g(item: dict, *keys: str, default=None):
    for k in keys:
        if k in item:
            return item[k]
    return default


def canonical_items(spec: dict) -> Counter:
    out: Counter = Counter()
    for item in spec.get("constraints", []) or []:
        t = _TYPE_ALIASES.get(str(_g(item, "type", "kind", "name", default="")).strip().lower())
        if t == "classic":
            continue
        if t == "diagonal":
            out[("diagonal",)] += 1
        elif t == "killer":
            cells = frozenset(cells_from_json(_g(item, "cells", "cage")))
            out[("killer", cells, int(_g(item, "sum", "total", "value")))] += 1
        elif t == "thermo":
            out[("thermo", tuple(cells_from_json(_g(item, "path", "cells", "thermo"))))] += 1
        elif t == "arrow":
            circle = cells_from_json([_g(item, "circle", "bulb", "head")])[0]
            path = frozenset(cells_from_json(_g(item, "path", "cells", "tail")))
            out[("arrow", circle, path)] += 1
        elif t == "sandwich":
            if "cells" in item or "line_cells" in item:
                line = cells_from_json(_g(item, "cells", "line_cells"))
            else:
                kind = str(_g(item, "line", "orientation", "direction")).lower()
                kind = {"rows": "row", "column": "col"}.get(kind, kind)
                line = _GRID.line(kind, int(_g(item, "index", "line_index", "n")))
            out[("sandwich", frozenset(line), int(_g(item, "sum", "total", "value")))] += 1
        elif t == "alldiff":
            out[("alldiff", frozenset(cells_from_json(item["cells"])))] += 1
        elif t in ("even", "odd", "parity"):
            even = bool(item.get("even", True)) if t == "parity" else t == "even"
            for c in cells_from_json(item["cells"]):
                out[("parity", c, even)] += 1
        elif t in ("lessthan", "greaterthan"):
            a = cells_from_json([_g(item, "smaller", "left", "a")])[0]
            b = cells_from_json([_g(item, "larger", "right", "b")])[0]
            if t == "greaterthan":
                a, b = b, a
            out[("lessthan", a, b)] += 1
        else:
            out[("unknown", t)] += 1
    return out


def safe_canonical(spec: dict | None) -> Counter | None:
    """정규화 불가(형식 붕괴)면 None."""
    if spec is None:
        return None
    try:
        return canonical_items(spec)
    except Exception:  # noqa: BLE001
        return None


def compare(pred: Counter | None, gold: Counter) -> dict:
    """제약 단위 TP/FP/FN과 완전일치 여부."""
    if pred is None:
        return {"tp": 0, "fp": 0, "fn": sum(gold.values()), "exact": False}
    tp = sum((pred & gold).values())
    return {
        "tp": tp,
        "fp": sum(pred.values()) - tp,
        "fn": sum(gold.values()) - tp,
        "exact": pred == gold,
    }
