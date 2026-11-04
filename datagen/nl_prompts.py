"""④-A ③ 지원용 자연어 문제 설명 + 정답 명세 (A6).

puzzles/{variant}_{tier}.jsonl에서 퍼즐을 골라, 사람이 쓴 것 같은 한국어 문제 설명(text)과
정답 spec 쌍을 만든다. ③은 text를 LLM 파서에 넣고, 출력 JSON을 spec과 비교해 정확도를 잰다.

파서가 표기 차이에 흔들리는지 보려고, 퍼즐마다 표현 방식을 돌려 가며 쓴다.
  - 좌표: "r3c2" / "3행 2열" / "(3, 2)" — 모두 1부터 센다. spec은 0부터 센 [행, 열]
  - 단서 격자: 9줄 / 81자 한 줄
  - 규칙 문장: 제약 종류마다 2~3가지 표현

출력: puzzles/nl_prompts.jsonl, 한 줄에 하나
  {"id", "puzzle_id", "variant", "tier", "text", "spec", "style"{"coord", "grid", "phrasing"}}

사용 예
-------
python datagen/nl_prompts.py                 # → puzzles/nl_prompts.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 변형별로 뽑을 개수 (규칙이 단순한 classic은 적게)
PICK = {"classic": 4, "diagonal": 6, "thermo": 10, "arrow": 10, "mixed": 10}
COORD_STYLES = ("rc", "korean", "paren")
GRID_STYLES = ("rows", "string")

COORD_NOTES = {
    "rc": "칸 위치는 r행c열로 적습니다 (r1c1이 왼쪽 위).",
    "korean": "칸 위치는 '행 열' 순서이고, 맨 위 행과 맨 왼쪽 열이 1입니다.",
    "paren": "칸 위치는 (행, 열)로 적고, 왼쪽 위가 (1, 1)입니다.",
}

CLASSIC_RULES = (
    "가로줄, 세로줄, 3×3 상자마다 1부터 9까지 숫자가 한 번씩 들어갑니다.",
    "일반 스도쿠 규칙을 따릅니다. 각 행·열·3x3 박스에 1~9가 겹치지 않게 들어갑니다.",
    "기본 규칙: 모든 행, 모든 열, 9개의 3×3 구역에 1~9를 하나씩 채웁니다.",
)
DIAGONAL_RULES = (
    "두 대각선에도 1부터 9까지 숫자가 한 번씩 들어갑니다.",
    "추가로, 왼쪽 위에서 오른쪽 아래로 가는 대각선과 오른쪽 위에서 왼쪽 아래로 가는 대각선 각각에도 숫자가 겹치면 안 됩니다.",
    "X 스도쿠입니다. 양쪽 대각선 9칸에도 1~9가 하나씩 들어갑니다.",
)
THERMO_RULES = (
    "온도계: {bulb}의 둥근 끝에서 시작해 {rest} 순서로 갈수록 숫자가 커집니다.",
    "{path} 칸들은 온도계입니다. 앞쪽({bulb})이 가장 작고 뒤로 갈수록 숫자가 증가합니다.",
    "전구가 {bulb}에 있는 온도계가 {rest}까지 이어집니다. 전구에서 멀어질수록 값이 엄격하게 커져야 합니다.",
)
ARROW_RULES = (
    "화살표: {circle}의 원 안 숫자는 화살표가 지나가는 {path} 칸 숫자의 합과 같습니다.",
    "{circle}에 원이 있고, 거기서 나온 화살표가 지나가는 칸은 {path}입니다. 화살표 위 숫자를 더하면 원 안의 숫자가 됩니다.",
    "{path} 칸의 합 = {circle} 칸의 숫자 (화살표 규칙).",
)


def fmt_cell(cell: list[int], style: str) -> str:
    r, c = cell[0] + 1, cell[1] + 1
    if style == "rc":
        return f"r{r}c{c}"
    if style == "korean":
        return f"{r}행 {c}열"
    return f"({r}, {c})"


def fmt_cells(cells: list[list[int]], style: str, sep: str = ", ") -> str:
    return sep.join(fmt_cell(c, style) for c in cells)


def fmt_grid(givens: str, style: str) -> str:
    if style == "string":
        return f"처음 주어진 숫자 (81자, 왼쪽 위부터 한 줄씩, 빈칸은 .):\n{givens}"
    rows = "\n".join(givens[i:i + 9] for i in range(0, 81, 9))
    return f"처음 주어진 숫자 (빈칸은 .):\n{rows}"


def describe(rec: dict, coord: str, grid_style: str, phrasing: int) -> str:
    """퍼즐 레코드 하나를 자연어 문제 설명으로 바꾼다."""
    lines = ["9×9 스도쿠 문제입니다.", CLASSIC_RULES[phrasing % len(CLASSIC_RULES)]]
    extra = []
    for k, con in enumerate(rec["spec"]["constraints"]):
        p = (phrasing + k) % 3
        if con["type"] == "diagonal":
            extra.append(DIAGONAL_RULES[p])
        elif con["type"] == "thermo":
            path = con["path"]
            extra.append(THERMO_RULES[p].format(
                bulb=fmt_cell(path[0], coord),
                rest=fmt_cells(path[1:], coord, " → "),
                path=fmt_cells(path, coord, " → ")))
        elif con["type"] == "arrow":
            extra.append(ARROW_RULES[p].format(
                circle=fmt_cell(con["circle"], coord),
                path=fmt_cells(con["path"], coord)))
        else:  # pragma: no cover — 생성기가 만들지 않는 종류
            raise ValueError(f"설명 템플릿이 없는 제약: {con['type']}")
    if extra:
        lines.append(COORD_NOTES[coord])
        lines.append("추가 규칙:")
        lines += [f"{i}. {s}" for i, s in enumerate(extra, 1)]
    lines.append(fmt_grid(rec["spec"]["givens"], grid_style))
    return "\n".join(lines)


def load_puzzles(variant: str) -> list[dict]:
    recs = []
    for path in sorted((ROOT / "puzzles").glob(f"{variant}_*.jsonl")):
        recs += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return recs


def pick(recs: list[dict], n: int, rnd: random.Random) -> list[dict]:
    """구간이 고르게 섞이도록 구간별로 돌아가며 뽑는다."""
    by_tier: dict[str, list[dict]] = {}
    for r in recs:
        by_tier.setdefault(r["difficulty"]["tier"], []).append(r)
    for group in by_tier.values():
        rnd.shuffle(group)
    out, tiers = [], sorted(by_tier)
    while len(out) < n and any(by_tier.values()):
        for t in tiers:
            if by_tier[t] and len(out) < n:
                out.append(by_tier[t].pop())
    return out


def build(seed: int = 0) -> list[dict]:
    rnd = random.Random(seed)
    items = []
    for variant, n in PICK.items():
        for rec in pick(load_puzzles(variant), n, rnd):
            k = len(items)
            style = {
                "coord": COORD_STYLES[k % len(COORD_STYLES)],
                "grid": GRID_STYLES[(k // len(COORD_STYLES)) % len(GRID_STYLES)],
                "phrasing": k % 3,
            }
            items.append({
                "id": f"nl-{k + 1:03d}",
                "puzzle_id": rec["id"],
                "variant": rec["variant"],
                "tier": rec["difficulty"]["tier"],
                "text": describe(rec, style["coord"], style["grid"], style["phrasing"]),
                "spec": rec["spec"],
                "style": style,
            })
    return items


def main() -> None:
    ap = argparse.ArgumentParser(description="③ 파서 평가용 자연어 문제 + 정답 spec 생성")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=ROOT / "puzzles" / "nl_prompts.jsonl")
    args = ap.parse_args()
    items = build(args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"{len(items)}개 → {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
