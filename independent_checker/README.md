# 엔진 독립 스도쿠 결과 검사기

이 검사기는 `sudoku_engine`을 import하지 않는다. 결과 JSON의 `givens`, `constraints`,
`actual_solution`을 직접 읽고 각 규칙을 별도로 구현하여 검사한다. 엔진이 저장한
`expected_solution`은 판정에 사용하지 않는다.

## 독립성의 범위

- **독립인 부분**: 규칙 계산(행·열·박스 중복, 킬러 합, 온도계 증가, 화살표 합, 샌드위치 합,
  짝·홀, 부등호). 엔진 코드를 보지 않고 새로 구현했다.
- **엔진과 같은 부분**: 입력 스키마(키 이름, type 별칭, 좌표 표기). 같은 결과 파일을 읽으려면
  파서·엔진과 같은 명세 형식을 받아야 하기 때문이다.
- **엔진과 다르게 한 부분**: 애매한 값을 추측하지 않는다. 엔진은 `"even": "false"`를 짝수로,
  `"sum": 12.9`를 12로, `even`이 없는 `parity`를 짝수로 읽지만, 검사기는 `"false"`를 홀수로 읽고
  나머지 둘은 "판정 불가"로 돌려준다.

그래서 엔진과 검사기의 판정이 일치한다는 것은 "규칙 계산이 맞다"는 근거이고,
"명세 형식을 둘 다 같은 방식으로 잘못 읽었을 가능성"까지 없애 주지는 않는다.

## 판정

| 판정 | 조건 | CLI 종료 코드 |
|---|---|---|
| **정답** | 모든 단서, 행·열·박스, 명세의 변형 제약을 만족하고 검사하지 못한 항목이 없다 | 0 |
| **규칙 위반** | 하나 이상의 단서 또는 규칙을 어겼다. 위반 규칙, 칸, 기대값과 실제값을 표시한다 | 1 |
| **판정 불가** | 위반은 없지만 검사하지 못한 항목이 있다 | 2 |

- 위반이 확인되면 검사하지 못한 항목이 함께 있어도 **규칙 위반**이 우선한다. 격자가 틀렸다는
  사실은 바뀌지 않기 때문이다. 검사하지 못한 항목은 보고서에 따로 함께 적는다.
- 판정 불가가 되는 경우:
  - 격자·단서 형식 오류, 모르는 제약 type, 값이 애매한 제약(정수가 아닌 합, 값 없는 `parity` 등)
  - 비정상 제약(원이 경로에 들어간 화살표, 1칸 온도계, 같은 두 칸의 부등호, `low == high`인 샌드위치)
  - **`constraints` 키가 없음.** 변형 규칙이 빠졌는지 알 수 없으므로, 클래식만인 퍼즐은 `[]`을 명시한다
  - **`unsupported`(또는 `unsupported_rules`)가 비어 있지 않음.** LLM이 명세로 옮기지 못한 규칙이
    있다는 뜻이라 퍼즐 전체를 검사했다고 할 수 없다
- 샌드위치 줄에 1이나 9가 한 번씩 있지 않으면 명세 오류가 아니라 **격자의 위반**(`sandwich.bounds`)이다.

검사 범위는 **완성 격자가 주어진 명세를 지키는가**이다. 자연어 규칙을 LLM이 명세로
정확하게 변환했는지와 해가 유일한지는 이 검사기의 범위가 아니다.

## 지원 규칙

- 클래식 행·열·3×3 박스
- 대각선 (`diagonal`, `x_sudoku`, `sudoku_x`)
- 킬러: 합과 케이지 내부 중복 금지 (`killer`, `cage`, `killer_cage`, `sum`)
- 온도계: 구근부터 엄격 증가, 2칸 이상 (`thermo`, `thermometer`)
- 화살표: 원 = 경로 합
- 샌드위치: `index`는 0-based, 1과 9 사이만 합산, 붙어 있으면 합 0. 줄 방향 키는 `line`/`orientation`/`direction`
- `alldiff` (`alldifferent`, `all_different`, `unique`)
- 짝수·홀수·`parity` (`even`/`parity` 값은 `true`/`false`/`"even"`/`"odd"`만)
- `lessthan`·`greaterthan` (`less_than`, `inequality`, `greater_than`)

type 키는 `type`/`kind`/`name`을 받는다. 좌표 문자열 `r1c1`은 1-based, 배열 `[0, 0]`과
`{"row": 0, "col": 0}`은 0-based로 해석한다. 단서는 81자 문자열, 좌표-값 객체, 9×9 배열을 받는다.

## 1. 결과 JSON 만들기

방법은 두 가지다. 둘 다 같은 `sudoku-result-v1` 형식을 만들고, 판정은 하지 않는다.

- **팀 GUI**: 보드를 다 채운 뒤(풀이 또는 직접 입력) 오른쪽 아래 `결과 JSON 저장`을 누른다.
  LLM으로 파싱한 퍼즐이면 적용 안 된 규칙(`unsupported`)도 함께 저장된다.
- **명령행**: 엔진으로 풀어 저장한다.

```bash
python validation_tools/export_solver_result.py examples/01_x_sudoku.json actual_result.json
```

검사에 필요한 핵심 필드는 다음과 같다. 형식 전체는 `independent_checker/sample_result.json`과 같다.

```json
{
  "title": "X-스도쿠 (대각선)",
  "givens": "초기 퍼즐 81자",
  "constraints": [{"type": "diagonal"}],
  "unsupported": [],
  "actual_solution": "백트래킹 결과 81개 숫자"
}
```

GUI로 저장한 파일에는 `filled_by`(단서·직접 입력·엔진이 채운 칸 수)가 더 들어 있고,
엔진으로 푼 경우에만 `solver`·`stats`가 들어간다. 검사기는 이 필드들을 판정에 쓰지 않는다.

## 2. 검사기 실행

GUI:

```bash
python independent_checker/checker.py
```

결과 JSON을 선택하고 `결과 검사`를 누른다. 위반 내역과 검사하지 못한 항목이 따로 표시되고,
검사 보고서는 JSON으로 다시 저장할 수 있다.

명령행:

```bash
python independent_checker/checker.py actual_result.json --report validation_report.json
```

## 3. 검사기 자체 테스트

```bash
python -m unittest independent_checker.test_validator -v
```

24개 테스트로 다음을 확인한다.
- 저장된 예제 정답이 통과한다.
- 각 제약을 의도적으로 깨뜨린 격자와 단서 변경이 `규칙 위반`이 된다.
- 알 수 없는 type, 잘못된 길이의 격자, `constraints` 누락, `unsupported`, 애매한 값, 비정상 제약이 `판정 불가`가 된다.
- 위반과 판정 불가가 함께 있으면 `규칙 위반`이 된다.
- 엔진이 받는 별칭·표기를 검사기도 받는다.

## 4. 엔진 해 대량 교차검증

```bash
python validation_tools/batch_validate.py
```

하네스는 엔진을 실행해 해를 만들지만, 판정은 엔진을 import하지 않는 `validator.py`가 한다.
결과는 `results/independent_validation_batch.json`에 저장된다.

| 대상 | 내용 |
|---|---|
| 평가 50개 | LLM(gemini-3.5-flash)이 만든 명세를 엔진으로 풀어 검사. 저장된 정답 격자와도 비교 |
| bench 전체 | classic 100, variant 150, multi 12, unsat 12. 해가 없는 unsat은 완성 격자가 없어 검사기 범위 밖이므로 엔진이 "해 없음"을 냈는지만 센다 |
| 음성 대조군 | 엔진 해의 숫자를 무작위로 바꿔 끼운 격자(행·열·박스는 그대로 만족, 단서는 비움)를 검사기와 엔진 제약 검사에 함께 넣어 판정이 같은지 본다 |

결과 (2026-11-25, 제한 10초, 대조군은 해마다 5개, seed 0):

| 세트 | 퍼즐 | 엔진 해 | 검사기 정답 | 정답 격자 일치 | 해 없음 확인 |
|---|---|---|---|---|---|
| 평가 50개 | 50 | 50 | 50 | 50 | - |
| bench/classic | 100 | 100 | 100 | - | - |
| bench/variant | 150 | 150 | 150 | - | - |
| bench/multi | 12 | 12 | 12 | - | - |
| bench/unsat | 12 | 0 | - | - | 12 |

음성 대조군 1,560개에서 검사기와 엔진 제약 검사의 판정 불일치는 0개였다(둘 다 위반 787, 둘 다 정답 773).
"둘 다 정답" 773개 중 770개는 변형 제약이 없거나 대각선뿐인 퍼즐 154개(× 5)에서 나왔다.
숫자를 바꿔 끼워도 이런 규칙은 그대로 만족하므로 정답이 맞다. 변형 제약이 있는 퍼즐의 대조군은 거의 모두 위반으로 잡혔다.
