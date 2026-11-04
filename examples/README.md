# examples — 공용 명세 JSON (③ 작성 · ④ 실험 · ⑤ UI)

`engine/sudoku_engine/spec.py` 형식의 변형 스도쿠 명세 5개. 모두 **현재 엔진(패치 전)에서 유일해**를 갖고,
`fc` / `ac3` / `full` 전파 설정 모두에서 저장된 정답과 같은 해가 나오는 것을 확인했다.

| 파일 | 변형 | 단서 | 제약 수 | 난이도(rate_difficulty) |
|---|---|---|---|---|
| `01_x_sudoku.json` | 대각선 | 24 | 1 | 매우 어려움 |
| `02_killer.json` | 킬러 케이지 8개 | 26 | 8 | 논리 불가(추측 필요) |
| `03_thermo_parity.json` | 온도계 3개 + 짝수·홀수 칸 | 24 | 5 | 보통 |
| `04_arrow_inequality.json` | 화살표 3개 + 부등호 5개 | 25 | 8 | 논리 불가(추측 필요) |
| `05_sandwich_mix.json` | 샌드위치 3개 + 킬러 2개 + 대각선 | 24 | 6 | 쉬움 |

## 파일 형식

```json
{
  "name": "02_killer",
  "title": "킬러 케이지",
  "note": "한 줄 설명",
  "rules_text": "자연어 규칙 (③ 파서 입력 / ⑤ 화면 표시용)",
  "givens": "81자, 빈칸은 '.'",
  "constraints": [ {"type": "killer", "cells": ["r2c9", "r3c9"], "sum": 17}, ... ],
  "solution": "81자 정답 (④ 채점용)"
}
```

- `load_spec()`은 `givens`·`constraints`만 읽고 나머지 키는 무시하므로 **파일을 그대로 넣으면 된다.**
- 좌표는 1-indexed `"r행c열"`. 샌드위치 `index`만 0부터 센다(1행 → 0).

## 사용 예

```python
import json
from sudoku_engine import solve
from sudoku_engine.spec import load_spec

ex = json.load(open("examples/02_killer.json", encoding="utf-8"))
model = load_spec(ex)              # ④⑤: 바로 풀이·힌트에 사용
result = solve(model)
assert "".join(str(result.solution[(r, c)]) for r in range(9) for c in range(9)) == ex["solution"]

# ③: 자연어 → 명세 파싱 결과를 정답 constraints와 비교
from llm_parser import parse_rules
from llm_parser.canonical import canonical_items
# parse_rules(ex["rules_text"], client, givens=ex["givens"]).spec 과 ex 를 canonical_items로 비교
```

## 주의

- **9칸 미만 `alldiff`는 넣지 않았다.** 현재 엔진은 ac3/full 전파에서 이런 제약이 있으면 해가 있어도
  "해 없음"을 낸다(② 결함 A, `parser/for_engine_team/README.md`).
- 킬러 예시는 현재 엔진에서 약 0.5초 걸린다(합 전파 미호출, 결함 B). 패치 적용 시 약 0.01초.
- 퍼즐 생성기는 ④ 담당이라 생성 스크립트는 포함하지 않았다. 형식만 맞추면 ④가 만든 퍼즐도 여기에 추가할 수 있다.
