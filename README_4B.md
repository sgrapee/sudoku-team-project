# ④-B 실험 파트 — 내일 조별모임 준비 자료

## 현재 준비한 파일

- `run_bench.py`: 기존 Solver를 이용해 퍼즐×설정별 원시 측정값을 CSV로 저장
- `analyze.py`: 공통으로 풀린 퍼즐 집합 기준 중앙값·IQR을 계산하고, SciPy가 있으면 Wilcoxon 검정을 출력
- `plot_results.py`: 원시 CSV로 그래프 3장(PNG)을 만든다. matplotlib 필요
- `analyze_failures.py`: 원시 CSV의 실패·특이 실행을 분류해 상세·요약 CSV로 저장
- `tests/`: 위 두 스크립트의 테스트 (`python -m pytest -q tests`)
- `results/E1_raw.csv`, `results/E2_raw.csv`: 소규모 예비 실행 원시 결과
- `results/E1_summary.csv`, `results/E2_summary.csv`: 예비 실행 요약 결과

## 실행 방법

저장소 루트에서:

```bash
# E1: 변수 선택/값 선택 휴리스틱 비교
python run_bench.py --experiment E1 --limit 3 --time-limit 2
python analyze.py results/E1_raw.csv

# E2: 현재 구현된 제약 전파 단계 비교
python run_bench.py --experiment E2 --limit 3 --time-limit 2
python analyze.py results/E2_raw.csv

# 데이터셋(jsonl) 사용: --puzzles에 .txt/.jsonl 파일을 여러 개 줄 수 있다
python run_bench.py --experiment E1 --puzzles puzzles/bench/classic.jsonl
```

`--limit 3`은 입력 파일마다 최대 3개씩 읽는다는 뜻이다. `--puzzles`를 주지 않으면 기존처럼 `engine/puzzles_easy.txt`, `engine/puzzles_hard.txt`를 읽는다. 예비 실행은 빠른 점검용이며, 최종 실험에서는 `--limit`을 생략하고 충분한 시간 제한과 반복 측정을 협의한다.

## 그래프·실패 분석

```bash
python -m pip install matplotlib                 # 그래프에만 필요
python plot_results.py results/E2_raw.csv        # -> results/figures/E2_raw_0{1,2,3}_*.png
python analyze_failures.py results/E2_raw.csv    # -> results/failure_analysis/E2_raw_failure_{details,summary}.csv
python datagen/difficulty_vs_cost.py results/E2_raw.csv  # E4 -> results/E2_raw_difficulty.{md,png}
```

앞의 둘은 `--out-dir`로 저장 위치를 바꿀 수 있다. `difficulty_vs_cost.py`는 CSV 옆에 저장하고, 여러 CSV를 한 번에 받는다. 데이터셋 레코드의 `difficulty.score`·`level`(엔진 `rate_difficulty` 값)과 `branch_nodes`의 스피어만 순위상관을 설정별로 계산하고, level별 분포를 그린다. 난이도가 없는 퍼즐(bench unsat·multi, .txt 입력)은 뺀다.

E3(변형 제약 효과)는 `python datagen/variant_effect.py`로 돌린다. 변형 퍼즐 375개마다 같은 단서에서 변형 제약을 켰을 때와 껐을 때의 해 개수(1000개까지)와 첫 해까지의 탐색 비용을 재고, 혼합 퍼즐은 제약 종류를 하나씩 뺀 해 개수도 센다. 결과는 `results/E3_full/`(원시 CSV, `E3_summary.md`, 그래프 3장)에 저장하고, `--plot-only`로 그래프·표만 다시 만들 수 있다.

백트래킹 vs 로컬서치 비교 결과와 그래프는 `results/compare/README.md`에 있다.

`plot_results.py` 그래프:

1. 설정별 branch_nodes 중앙값 (막대)
2. 설정별 실행 시간 (박스플롯)
3. 난이도 구간(tier, 없으면 단서 수)별 branch_nodes (점)

- 1·2는 **모든 설정이 공통으로 푼 퍼즐**만 쓴다. `analyze.py`와 같은 기준이라 숫자가 `*_summary.csv`와 같다. 설정마다 자기가 푼 퍼즐로 계산하면 쉬운 퍼즐만 푼 설정이 유리해 보인다. 각 설정 이름 아래에 전체 해결 수(`solved k/n`)를 함께 적는다.
- 공통으로 푼 퍼즐이 하나도 없으면(예: 어떤 설정이 하나도 못 풂) 그래프를 만들지 않고 설정별 성공 수를 보여 주며 멈춘다.
- 3은 성공한 실행을 모두 쓴다. 점이 겹치지 않게 설정별로 옆으로 나누고 조금씩 흔들어(jitter, seed 고정) 찍는다.
- y축은 symlog다. branch_nodes가 0부터 수만까지 퍼져 있어서 선형 축이면 none 말고는 막대가 보이지 않는다.

`analyze_failures.py` 분류 (`failure_category`):

| 분류 | 뜻 | 상세 CSV에 넣는지 |
|---|---|---|
| `solved` | 정상 해결 | 넣지 않음 |
| `unsat_confirmed` | 해 없음 퍼즐(`expected_solutions=0`)에서 탐색을 끝까지 해 해가 없음을 확인 (정답) | 넣지 않음 |
| `timeout` | 시간 또는 노드 제한 초과 | 넣음 |
| `missed_solution` | 해가 있는 퍼즐인데 시간 초과 없이 탐색이 끝남 → 솔버 버그 의심 | 넣음 |
| `not_solved_no_timeout` | 시간 초과 없이 못 풂, 기대 해 개수를 모름(.txt 입력) | 넣음 |
| `multi_solution_case_single_solution_search` | 여러 해 퍼즐. `solve()`는 해 하나에서 멈추므로 해 개수는 확인하지 않음 | 넣음 |
| `unexpected_solution_*`, `solved_count_not_comparable` | 기대 해 개수와 찾은 개수가 안 맞거나 비교할 수 없음 | 넣음 |

엔진은 시간 제한과 `max_nodes` 초과를 모두 `timed_out=True`로 기록한다. 그래서 `solved=False`·`timed_out=False`는 탐색을 끝까지 했다는 뜻이다.

두 스크립트 모두 `run_bench.py`의 원시 CSV만 받는다. 다음 경우에는 파일 경로와 줄 번호를 담은 오류를 내고 멈춘다.

- 필수 열이 없는 CSV (예: `*_summary.csv`)
- 열 개수가 헤더와 다른 행 (중간에 끊긴 파일)
- 숫자가 아닌 `branch_nodes`·`elapsed_ms`·`givens` 값 (그래프 스크립트만 검사)

## 실험 설계

- E1: 전파 수준을 FC로 고정하고 `static / mrv / mrv_degree` × `asc / lcv` 6개 설정을 비교한다.
- E2: 변수·값 선택을 `mrv / asc`로 고정하고 `none / fc / ac3_pure / ac3 / full` 5개 단계를 비교한다.
- 저장 열: puzzle_id, 설정, solved, timed_out, nodes, branch_nodes, backtracks, assignments, elapsed_ms 등. 입력 정보로 source_file, variant, tier, givens, expected_solutions(해 개수, txt 입력은 빈칸)도 남긴다.

## 반드시 공유할 구현상 한계

`sudoku_engine/propagation.py`의 `propagation="ac3"`는 `ac3()` 안에서 `_hidden_singles_unit()`도 호출한다. 그래서 **`ac3`는 순수 AC-3가 아니라 Hidden Single 검사를 포함한 AC-3**다. 엔진 기본값과 기존 결과를 바꾸지 않으려고 `ac3`는 그대로 두고, 순수 AC-3는 `propagation="ac3_pure"`로 따로 추가했다(2026-11-18). 보고서에서는 `ac3`를 "AC-3 + hidden single", `ac3_pure`를 "순수 AC-3"로 쓴다.

실행기는 `--puzzles`로 공통 데이터 형식인 `puzzles/*.jsonl`도 읽는다. jsonl 퍼즐은 `load_spec(spec)`으로 만들어서 변형 제약도 함께 들어간다. 레코드 형식과 비교용 세트(`puzzles/bench/`)는 `puzzles/README.md`에 있다.

## 예비 실행 결과 — 최종 결과 아님

- E1: 6개 퍼즐 × 6개 설정 = 36회. 모든 설정이 6개 모두 해결했다.
- E2: 6개 퍼즐 × 4개 설정 = 24회. `none`은 2개 시간 초과, 나머지 설정은 6개 모두 해결했다. 모든 설정이 공통으로 해결한 4개 퍼즐을 기준으로 요약했다.
- 이 표본은 설정과 저장 형식이 작동하는지 확인하는 예비 점검이다. 최종 결론·보고서 통계로 사용하지 않는다.

## 조별모임에서 합의/질문할 사항

1. ④-A와 JSONL 데이터셋의 정확한 스키마 및 전달 시점을 확정한다.
2. ②에게 `SolverConfig`의 지원 값, 실행별 통계 필드, 시간 제한 기준을 확인한다.
3. ②에게 AC-3와 Hidden Single을 분리할 수 있는지 요청한다.
4. E1/E2 최종 퍼즐 수, 반복 횟수, 시간 제한, 결과 파일 저장 위치를 합의한다.
5. ③과 E5에서 받을 LLM 파싱 결과 및 정답 명세 형식을 합의한다.

## 기존 엔진 테스트

원본 저장소의 `engine` 디렉터리에서 `python -m pytest -q tests` 실행 결과: **77 passed**.
