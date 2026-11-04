# sudoku_engine — 알고리즘 엔진 (② 파트)

변형 스도쿠 CSP solver. 백트래킹 탐색, 제약 전파, 인간 추론 기법, 난이도 판정,
벤치마크 하네스를 포함한다.

```bash
python demo.py          # 전체 기능 데모
pytest -q tests/        # 테스트 77개
```

---

## 1. 팀 인터페이스 계약

다른 파트가 알아야 할 것은 이 세 가지뿐이다.

### ③ LLM 파서 → 엔진

```python
from sudoku_engine.spec import load_spec, validate_spec, spec_to_model_or_reason

ok, message = validate_spec(json_from_llm)   # (성립 여부, 사람이 읽을 메시지)
model, reason = spec_to_model_or_reason(spec)  # 해 존재 여부까지 확인
```

JSON 스키마는 `spec.py` 상단 docstring에 있다. 셀 표기는 `[0,0]`, `"r1c1"`,
`{"row":0,"col":0}` 세 가지를 모두 받는다. LLM 출력의 표기가 흔들려도 통과한다.

거부할 때는 반드시 이유를 문자열로 돌려주므로, 그 메시지를 LLM에게 그대로
되먹여 재시도시키면 된다. 예:

```
constraints[0] — killer: 2칸 케이지의 합은 3~17 범위여야 하는데 30입니다
constraints[2] — 알 수 없는 제약 종류 'unicorn'. 지원 목록: alldiff, arrow, ...
```

문법이 맞아도 해가 없는 명세(순환 온도계 등)는 `spec_to_model_or_reason`이
잡아낸다. 이 검증을 건너뛰면 답 없는 문제를 몇 분씩 탐색하게 된다.

### ④ 생성기·실험 → 엔진

```python
from sudoku_engine import count_solutions, has_unique_solution
from sudoku_engine.benchmark import run_configs, format_table, generate_puzzle
from sudoku_engine.techniques import rate_difficulty

has_unique_solution(model)              # 칸을 지울 때마다 호출
rate_difficulty(model)                  # 난이도 라벨링
run_configs(puzzles, configs)           # 설정별 벤치마크 → 마크다운 표
```

`benchmark.py`의 생성기는 엔진 자체 검증용 최소 구현이다. 본 생성기는 ④가
만들되 `has_unique_solution`만 가져다 쓰면 된다.

### ⑤ 데모 UI → 엔진

```python
from sudoku_engine.techniques import next_hint, solve_logically

hint = next_hint(model, current=user_filled_cells)
hint.explanation   # "r5c5의 후보가 5 하나뿐이므로 5로 확정하고, ..."
hint.cell, hint.value, hint.eliminated
```

힌트 설명은 한국어 완성 문장이라 UI에 그대로 출력하면 된다.

### 제약 클래스 (직접 만들 경우)

```python
class Constraint:
    def scope(self) -> tuple[Cell, ...]
    def propagate(self, domains: dict) -> bool   # in-place 축소, 모순이면 False
    def check(self, assignment: dict) -> bool    # 부분/완전 할당 위반 여부
    def binary_arcs(self) -> list[tuple[Cell, Cell]]  # AC-3용, 없으면 []
```

1주차 스케치에서는 `propagate`가 새 dict를 반환하는 형태였으나, 탐색 중
수십만 번 호출되므로 **in-place 축소 + bool 반환**으로 확정했다. 새 dict가
필요하면 `core.copy_domains()`로 복사한 뒤 넘긴다.

---

## 2. 구현 범위

| 항목 | 내용 |
|---|---|
| 변수 순서 | static / MRV / MRV+Degree / random |
| 값 순서 | ascending / LCV / random |
| 전파 강도 | none / fc / ac3 / full (ac3 + naked subset) |
| 변형 제약 | Killer, Thermometer, Arrow, Sandwich, 대각선, 짝·홀, 부등호 |
| 인간 기법 | naked·hidden single, naked pair·triple, hidden pair·triple, pointing, claiming, X-Wing, XY-Wing, Swordfish |
| 계측 | nodes, branch_nodes, backtracks, assignments, arc_revisions, value_eliminations, elapsed |

킬러 케이지는 도메인 곱이 20만 이하면 **모든 조합을 열거해 완전 필터링**하고,
그보다 크면 min/max 경계 가지치기로 자동 전환한다.

---

## 3. 검증 결과

| 검증 | 결과 |
|---|---|
| 휴리스틱 36개 조합 정합성 | 전부 동일한 정답 |
| 전파 건전성(변형 제약 무작위 60회) | 정답 값 오제거 **0건** |
| 생성 퍼즐 60개 논리 solver 교차검증 | 오답 **0건** |
| 불가능 명세 탐지 | 순환 온도계·과대 케이지·격자 밖 좌표 전부 거부 |
| pytest | 77개 통과 (2.65초) |

전파 건전성이 가장 중요하다. 전파가 정답 값을 실수로 지우면 solver는 조용히
"해 없음"을 내놓고, 겉으로는 버그가 드러나지 않는다.

---

## 4. 실험 결과

**24단서 퍼즐 20개, 제한 3초.** 분기 노드 = 값을 2개 이상 시도한 실제 선택 지점.

| 설정 | 성공 | 공통 중앙 분기노드 | 중앙 시간 |
|---|---|---|---|
| static / asc / none | 8/20 | 8,630 | 1,931 ms |
| static / asc / fc | 19/20 | 863 | 68 ms |
| mrv / asc / fc | 20/20 | 10 | 4.6 ms |
| mrv / asc / ac3 | 20/20 | 0 | 7.9 ms |
| mrv / asc / full | 20/20 | 0 | 10.0 ms |

**발견 세 가지**

1. 전방검사만 켜도 분기가 10배, MRV까지 붙이면 863 → 10으로 86배 줄어든다.
   무전파는 40%만 시간 내에 푼다.
2. AC-3부터는 분기가 사실상 0이지만 **벽시계 시간은 오히려 늘어난다**
   (4.6 → 7.9 ms). 이 난이도 구간에서는 전파 비용이 탐색 절감을 초과한다.
   "제일 간단하고 빠른 방법을 선택했는가" 항목에 정확히 대응하는 결과.
3. Degree 타이브레이크는 도움이 되지 않는다(10 → 21). 스도쿠는 모든 칸의
   정적 차수가 20으로 동일해 타이브레이크가 변별력을 갖지 못한다.

**변형 제약의 정보량**: 같은 18단서에 대해 변형 제약을 켜면 유일해,
끄면 해가 50개 이상. 변형 제약이 실제로 문제를 결정한다는 정량적 증거다.

**XY-Wing·Swordfish 추가 효과**: 40개 퍼즐 중 "논리 불가" 판정이
19건 → 14건으로 26% 감소했다.

---

## 5. 알려진 한계 (보고서 "결과 검증" 항목용)

- **인간 기법 미구현분**: coloring, unique rectangle, forcing chain 등이 없어
  24단서 퍼즐의 약 30%가 여전히 "논리 불가"로 분류된다. 이 등급은 "정말로
  추측이 필요하다"가 아니라 "우리가 구현한 기법으로는 못 푼다"는 뜻이다.
  보고서에 이 구분을 명시할 것.
- **Sandwich 전파의 불완전성**: 1과 9의 위치 후보를 가지치기하고, 모든 배치에서
  항상 "사이"에 오는 칸의 1·9를 제거하는 수준까지만 구현했다. 사이 칸들의
  값 조합까지 완전 열거하지는 않는다.
- **AC-3는 이진 분해에 의존**: 전역 제약은 자체 `propagate()`로 처리하므로
  제약별 전파 강도가 균일하지 않다. 킬러는 완전 필터, 화살표는 경계 가지치기다.
- **메모리**: 분기마다 도메인 전체를 복사한다(81칸 × set). 9×9에서는 문제없지만
  16×16으로 확장하면 trailing 방식으로 바꿔야 한다.

---

## 6. 파일 구성

```
sudoku_engine/
  core.py          격자 기하, 도메인 유틸, 파싱·렌더링
  constraints.py   Constraint 인터페이스 + 변형 제약 7종
  model.py         격자·제약·단서 결합, 인덱싱
  propagation.py   FC, AC-3, hidden single, naked subset
  solver.py        백트래킹 + 휴리스틱 + 계측
  techniques.py    인간 기법 11종, 난이도, 힌트
  spec.py          JSON 명세 로더 (③ 인터페이스)
  benchmark.py     퍼즐 생성기, 벤치마크 하네스
tests/test_engine.py
demo.py
```

---

## 7. 개발 중 잡은 결함 (방법론으로 보고서에 포함할 것)

**FC 의미론 오류.** 도메인이 1개로 줄어든 것을 "할당됨"으로 취급해, 확정값이
이웃에 전파되지 않았다. 그 결과 전방검사가 무전파보다 노드를 더 많이 쓰는
이상 현상이 나왔다. AIMA 정의대로 명시적 할당 집합을 도입해 재작성했고,
수정 전후로 결론이 뒤집혔다.

**난이도 판정 왜곡.** 단서 반영(초기 후보 제거)을 `naked_single` 기법으로
집계해 등급이 부풀려졌다. `seed_domains()` 설정 단계를 분리해 수정했다.

**벤치마크 생존 편향.** 설정마다 푼 퍼즐 집합이 달라 중앙값 비교가 무의미했다.
모든 설정이 푼 공통 부분집합 기준 열(`common_*`)을 추가했다. 설정 간 비교는
반드시 이 열로 해야 한다.
