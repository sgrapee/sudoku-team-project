# puzzles/ — 퍼즐 데이터셋

`datagen/`의 생성기로 만든 퍼즐입니다. 모든 퍼즐은 유일해이고, `python datagen/validate_dataset.py`로 검증합니다.

| 파일 | 개수 | 내용 |
|---|---|---|
| `classic_{easy,medium,hard,expert}.jsonl` | 4 × 25 = 100 | 일반 스도쿠 |
| `{diagonal,thermo,arrow,killer,mixed}_{easy,medium,expert}.jsonl` | 5 × 3 × 25 = 375 | 변형 스도쿠 (mixed = 대각선 + 온도계 + 화살표) |
| `nl_prompts.jsonl` | 40 | 자연어 문제 설명 + 정답 명세 (파서 평가용, 형식이 다름) |
| `bench/` | 274 | 로컬서치 vs 백트래킹 비교용 세트 (아래 설명) |

## 레코드 형식

한 줄에 퍼즐 하나가 들어갑니다.

```json
{"id": "classic-0006", "variant": ["classic"],
 "spec": {"givens": "6.8.92....7.6.....(81자)", "constraints": []},
 "solution": "658492731974613582(81자)", "givens": 24,
 "difficulty": {"tier": "easy", "tier_label": "쉬움", "level": 1, "label": "쉬움",
                "score": 55, "solvable_by_logic": true,
                "techniques": {"hidden_single": 12, "naked_single": 43}},
 "seed": 6,
 "meta": {"target_givens": 24, "symmetric": false, "gen_ms": 322.1}}
```

| 필드 | 설명 |
|---|---|
| `id` | `{변형}-{seed 4자리}`. seed와 1:1이라 난이도 기준이 바뀌어도 그대로다 |
| `variant` | 들어 있는 규칙 목록. mixed는 `["diagonal", "thermo", "arrow"]` |
| `spec` | `engine/sudoku_engine/spec.py` 형식 그대로. **`load_spec(rec["spec"])`로 바로 Model이 된다.** 셀 좌표는 0부터 센 `[행, 열]`, 클래식은 `constraints: []` |
| `solution` | 정답 81자 |
| `givens` | 단서 개수 |
| `difficulty.tier` | 난이도 구간 (아래 표). `level`·`label`·`score`는 `rate_difficulty` 결과 그대로 |
| `seed`, `meta` | 다시 만들 때 쓰는 값. `meta.gen_ms`는 실행 환경마다 다르다 |

### 난이도 구간 (`difficulty.tier`)

`rate_difficulty`의 `level`(어떤 기법이 필요한가)로 나눕니다. `score`는 level끼리 범위가 겹쳐서 쓰지 않습니다.

| tier | 클래식 | 변형 |
|---|---|---|
| `easy` | level 1 (naked/hidden single) | level 1 |
| `medium` | level 2~3 (pair, pointing 등) | level 2~5 |
| `hard` | level 4~5 (x-wing, swordfish 등) | 없음 (변형은 hard가 0~5%뿐이라 medium에 합침) |
| `expert` | level 6 (엔진 기법으로 못 풂, 유일해는 보장) | level 6 |

- 변형은 구간을 정할 때만 변형 제약 전파를 level 1로 봅니다. 그래서 변형 레코드는 `level`이 2인데 `tier`가 `easy`일 수 있습니다.
- 킬러는 부분 케이지 방식입니다: 퍼즐마다 케이지 8개(2~4칸), 단서 18개.

## bench/ — 로컬서치 vs 백트래킹 비교용

`python datagen/bench_sets.py`로 만들고 검증합니다. 같은 명령을 다시 실행하면 같은 파일이 나옵니다.

| 파일 | 개수 | 내용 |
|---|---|---|
| `classic.jsonl` | 100 | 클래식 4구간 × 25 (원본 레코드 그대로) |
| `variant.jsonl` | 150 | diagonal·thermo·arrow·killer·mixed × 3구간 × 앞 10개 (원본 그대로) |
| `unsat.jsonl` | 12 | **해 없음**. 클래식 구간마다 3개. 빈칸 하나에 정답이 아닌 값을 넣었다. 같은 행·열·박스의 단서와 겹치지 않아 겉보기에는 정상 퍼즐이다 |
| `multi.jsonl` | 12 | **해가 여러 개**. 클래식 구간마다 3개. 단서 하나를 지워 해가 2개 이상이 되게 했다 |

`unsat`·`multi`는 레코드 형식이 조금 다릅니다.

- `solution`은 `null`, `difficulty`는 없음
- `expected.num_solutions`: 해 개수. `multi`는 `count_limit`(20)까지만 세므로 20이면 "20개 이상"
- `source`: 원본 퍼즐 id와 구간, 바꾼 내용(`change`)

백트래킹은 해가 없다는 것을 증명하고 해 개수를 셀 수 있지만, 로컬서치는 해가 없으면 끝나지 않고 해가 여러 개여도 하나만 찾습니다. 참고로 `unsat` 12개를 백트래킹으로 풀면 다음과 같습니다 (제한 10초).

| 설정 | 해 없음 증명 | 시간 중앙값 (최대) |
|---|---|---|
| `static/asc/none` | 8 / 12 (4개 시간 초과) | 3.3초 (10초) |
| `mrv/asc/fc` | 12 / 12 | 2ms (28ms) |
| `mrv_degree/lcv/ac3` (`SolverConfig` 기본) | 12 / 12 | 1.7ms (6.9ms) |

## 읽는 법

```python
import json
from pathlib import Path
from sudoku_engine import Solver, SolverConfig
from sudoku_engine.spec import load_spec

def read_puzzles(path, limit=None):
    """jsonl → [(id, spec, 레코드)]"""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out.append((rec["id"], rec["spec"], rec))
            if limit is not None and len(out) >= limit:
                break
    return out

for pid, spec, rec in read_puzzles("puzzles/bench/classic.jsonl"):
    model = load_spec(spec)            # 실행할 때마다 새로 만든다. 변형 제약도 같이 들어간다
    result = Solver(model, SolverConfig(time_limit=10)).solve()
    tier = rec.get("difficulty", {}).get("tier") or rec["source"]["tier"]
```

- 81자 문자열로 `Model.load_puzzle`을 부르면 클래식 규칙만 들어갑니다. 변형을 풀려면 `load_spec(spec)`을 써야 합니다.
- 결과 표에 `variant`(`"+".join(rec["variant"])`), `tier`, `givens` 열을 같이 남기면 난이도·변형별로 나눠 보기 쉽습니다.
- `unsat`에서 `solved`가 False이고 `timed_out`도 False이면 "해 없음을 증명함", `timed_out`이 True이면 "판정 못 함"입니다.
