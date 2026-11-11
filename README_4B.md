# ④-B 실험 파트 — 내일 조별모임 준비 자료

## 현재 준비한 파일

- `run_bench.py`: 기존 Solver를 이용해 퍼즐×설정별 원시 측정값을 CSV로 저장
- `analyze.py`: 공통으로 풀린 퍼즐 집합 기준 중앙값·IQR을 계산하고, SciPy가 있으면 Wilcoxon 검정을 출력
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

## 실험 설계

- E1: 전파 수준을 FC로 고정하고 `static / mrv / mrv_degree` × `asc / lcv` 6개 설정을 비교한다.
- E2: 변수·값 선택을 `mrv / asc`로 고정하고 현재 구현된 `none / fc / ac3 / full` 4개 단계를 비교한다.
- 저장 열: puzzle_id, 설정, solved, timed_out, nodes, branch_nodes, backtracks, assignments, elapsed_ms 등. 입력 정보로 source_file, variant, tier, givens, expected_solutions(해 개수, txt 입력은 빈칸)도 남긴다.

## 반드시 공유할 구현상 한계

현재 `sudoku_engine/propagation.py`의 `ac3()` 내부에서 `_hidden_singles_unit()`을 호출한다. 따라서 현재 `propagation="ac3"`는 **순수 AC-3가 아니라 Hidden Single 검사를 포함한 AC-3**다. 계획서의 E2에서 요구한 `순수 AC-3`와 `AC-3 + hidden single`을 구분하려면 ② 알고리즘 담당자가 코드를 분리하고 테스트해야 한다. 이번 예비 실행 결과를 순수 AC-3 결과라고 부르면 안 된다.

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
