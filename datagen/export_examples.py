"""④ 데이터셋 퍼즐을 examples/ 공용 명세 형식으로 내보낸다.

examples/ 형식(③ 작성, examples/README.md):
  {"name", "title", "note", "rules_text", "givens", "constraints", "solution"}
  - constraints 좌표는 1부터 센 "r행c열" (데이터셋 spec은 0부터 센 [행, 열])
  - rules_text는 ③ 예시와 같은 문장 형식

③ baseline(llm_parser.baseline)은 examples/*.json을 모두 읽으므로, 여기서 추가한 퍼즐도
LLM 단독 풀이 vs 파서+엔진 비교에 들어간다.

사용 예
-------
python datagen/export_examples.py          # → examples/06~10 (변형마다 1개)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (변형, 구간). 구간은 쉬움·보통·추측 필요가 섞이도록 돌려 가며 고른다. 각 파일의 첫 퍼즐을 쓴다.
PICKS = [("diagonal", "easy"), ("thermo", "medium"), ("arrow", "expert"),
         ("mixed", "easy"), ("killer", "medium")]
FIRST_NUMBER = 6  # ③ 예시가 01~05

TITLES = {"diagonal": "대각선", "thermo": "온도계", "arrow": "화살표",
          "mixed": "대각선 + 온도계 + 화살표", "killer": "킬러 케이지"}
DIAGONAL_RULE = "두 대각선(r1c1→r9c9, r1c9→r9c1)에도 1부터 9까지가 한 번씩만 들어간다."


def rc(cell: list[int]) -> str:
    return f"r{cell[0] + 1}c{cell[1] + 1}"


def rcs(cells: list[list[int]]) -> str:
    return ", ".join(rc(c) for c in cells)


def convert(con: dict) -> tuple[dict, str]:
    """데이터셋 제약 하나 → (examples 형식 제약, 규칙 문장)."""
    t = con["type"]
    if t == "diagonal":
        return {"type": "diagonal"}, DIAGONAL_RULE
    if t == "thermo":
        bulb, *rest = con["path"]
        return ({"type": "thermo", "path": [rc(c) for c in con["path"]]},
                f"온도계는 {rc(bulb)}(전구)에서 시작해 {rcs(rest)} 순서로 이어지며, "
                f"전구에서 멀어질수록 숫자가 커진다.")
    if t == "arrow":
        return ({"type": "arrow", "circle": rc(con["circle"]), "path": [rc(c) for c in con["path"]]},
                f"{rc(con['circle'])}의 원 안 숫자는 화살표가 지나는 {rcs(con['path'])}의 합과 같다.")
    if t == "killer":
        return ({"type": "killer", "cells": [rc(c) for c in con["cells"]], "sum": con["sum"]},
                f"킬러 케이지 {rcs(con['cells'])}의 합은 {con['sum']}이고, 케이지 안에는 같은 숫자가 없다.")
    raise ValueError(f"내보낼 수 없는 제약 종류: {t}")


def to_example(rec: dict, number: int) -> dict:
    variant = "mixed" if len(rec["variant"]) > 1 else rec["variant"][0]
    pairs = [convert(c) for c in rec["spec"]["constraints"]]
    d = rec["difficulty"]
    name = f"{number:02d}_{variant}_{d['tier']}"
    return {
        "name": name,
        "title": f"{TITLES[variant]} (④ 생성)",
        "note": f"④ 데이터셋 {rec['id']} · 구간 {d['tier_label']} · 엔진 난이도 {d['label']} · 단서 {rec['givens']}개.",
        "rules_text": " ".join(sentence for _, sentence in pairs),
        "givens": rec["spec"]["givens"],
        "constraints": [c for c, _ in pairs],
        "solution": rec["solution"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="④ 데이터셋 퍼즐 → examples/ 공용 명세")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "examples")
    args = ap.parse_args()

    for i, (variant, tier) in enumerate(PICKS):
        path = ROOT / "puzzles" / f"{variant}_{tier}.jsonl"
        rec = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        ex = to_example(rec, FIRST_NUMBER + i)
        out = args.out_dir / f"{ex['name']}.json"
        out.write_text(json.dumps(ex, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{out.relative_to(ROOT)}  ← {rec['id']} ({tier}, 제약 {len(ex['constraints'])}개)")


if __name__ == "__main__":
    main()
