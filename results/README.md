# 실험 결과 (E1·E2·E3·E4)

백트래킹 탐색 실험 결과입니다. 백트래킹 vs 로컬서치 비교는 [compare/README.md](compare/README.md)에 따로 있습니다.
실험 설계와 스크립트 사용법은 저장소 루트의 `README_4B.md`를 보세요.

## 폴더

| 폴더 | 실험 | 실행일 | 만든 방법 |
|---|---|---|---|
| `E1_full/` | E1 탐색 휴리스틱: 전파 FC 고정, 변수 순서(static / mrv / mrv_degree) × 값 순서(asc / lcv) 6설정 | 2026-11-18 | `run_bench.py --experiment E1` |
| `E2_full/` | E2 전파 강도: mrv + asc 고정, 전파 none / fc / ac3 / full 4설정 | 2026-11-11 | `run_bench.py --experiment E2` |
| `E3_full/` | E3 변형 제약 효과: 같은 단서에서 변형 제약을 켰을 때와 껐을 때 | 2026-11-18 | `datagen/variant_effect.py` |

E1·E2는 같은 퍼즐 499개를 세 묶음으로 나눠 돌렸습니다.

| 하위 폴더 | 퍼즐 |
|---|---|
| `classic/` | `puzzles/classic_{easy,medium,hard,expert}.jsonl` 100개 |
| `variant/` | `puzzles/{diagonal,thermo,arrow,killer,mixed}_{easy,medium,expert}.jsonl` 375개 |
| `special/` | `puzzles/bench/unsat.jsonl` 12개(해 없음) + `multi.jsonl` 12개(해 여러 개) |

하위 폴더마다 들어 있는 파일:

| 파일 | 내용 | 만드는 스크립트 |
|---|---|---|
| `E*_raw.csv` | 퍼즐 × 설정 한 행씩 원시 결과 | `run_bench.py` |
| `E*_summary.csv` | 모든 설정이 공통으로 푼 퍼즐 기준 중앙값·IQR | `analyze.py` |
| `figures/` | 분기 노드 막대, 시간 상자그림, 난이도별 산점도 | `plot_results.py` |
| `failure_analysis/` | 시간 초과·해 없음 확인 등 실행 분류 (상세·요약) | `analyze_failures.py` |
| `E*_raw_difficulty.{md,png}` | E4: 엔진 난이도와 분기 노드의 순위상관 (classic·variant만, special은 난이도 정보가 없음) | `datagen/difficulty_vs_cost.py` |

## 실행 조건 (해석 전에 읽어 주세요)

- 퍼즐·설정마다 제한 5초. 한 컴퓨터에서 프로세스 4개를 동시에 돌렸습니다(classic, variant 두 묶음, special).
- 그래서 **시간(`elapsed_ms`)에는 병렬 부하가 섞여 있습니다.** 시간은 보조 지표로 보고, 비교는 결정적인 `branch_nodes`(값을 2개 이상 시도한 분기 노드 수)로 하세요.
- 제한 시간 근처에서 끝나는 실행(E2 none, E1 static)은 부하에 따라 시간 초과 여부가 바뀔 수 있습니다.
- E2의 `ac3`는 hidden single 검사를 포함한 AC-3입니다(엔진 `propagation.py`의 `ac3()`). 순수 AC-3 결과라고 쓰면 안 됩니다.
- E3는 엔진 기본 설정(mrv_degree/lcv/ac3), 제한 10초, 프로세스 4개, 해는 1000개까지 셌습니다.

## 다시 만들기

```bash
# E1 classic (E2는 --experiment E2, variant·special은 위 표의 퍼즐 파일로)
python run_bench.py --experiment E1 --time-limit 5 --output-dir results/E1_full/classic \
  --puzzles puzzles/classic_easy.jsonl puzzles/classic_medium.jsonl puzzles/classic_hard.jsonl puzzles/classic_expert.jsonl
python analyze.py results/E1_full/classic/E1_raw.csv
python plot_results.py results/E1_full/classic/E1_raw.csv
python analyze_failures.py results/E1_full/classic/E1_raw.csv
python datagen/difficulty_vs_cost.py results/E1_full/classic/E1_raw.csv

# E3 (실행 + 그래프·표)
python datagen/variant_effect.py
```

variant는 시간을 줄이려고 diagonal·thermo·arrow와 killer·mixed 두 묶음으로 나눠 돌린 뒤 CSV를 합쳤습니다. 한 번에 돌려도 결과 형식은 같습니다.

## 결과 요약

분기 노드는 모든 설정이 공통으로 푼 퍼즐 기준 중앙값입니다(`E*_summary.csv`).

- **E1 탐색 휴리스틱**: static → MRV로 분기 노드가 약 100배 줄어든다(클래식 1561 → 15, 변형 3100 → 47). static은 변형 375개 중 36~40개가 시간 초과. degree 타이브레이크는 변형에서만 줄인다(47 → 37, Wilcoxon p = 3e-7, 클래식은 p = 0.41). LCV는 뚜렷한 차이가 없다.
- **E2 전파 강도**: 전파가 없으면 5초 안에 클래식 42/100, 변형 59/375만 푼다. 분기 노드는 클래식 none 7584 → fc 14 → ac3 1 → full 1, 변형 7536 → 23 → 1 → 1. 해 없음 12개는 fc·ac3·full이 모두 증명하고 none은 6개만 증명한다.
- **E3 변형 제약 효과**: 제약을 켜면 375개 모두 유일해, 끄면 93~100%가 해 1000개 이상이고 끈 상태의 첫 해가 원래 정답인 경우는 0개. 첫 해까지 분기 노드는 켰을 때 1, 껐을 때 16~29로 변형 제약이 탐색을 오히려 줄인다. 노드당 시간 비율(켬/끔)은 0.91~1.03. 혼합 퍼즐에서는 대각선을 빼면 유일해가 1/75만 남아 정보를 가장 많이 준다(화살표 6/75, 온도계 33/75). 숫자는 `E3_full/E3_summary.md`.
- **E4 난이도 vs 탐색 비용**: 엔진 난이도 level과 분기 노드의 스피어만 ρ는 ac3 0.70~0.73, full 0.83, fc 0.20~0.23, none −0.02~0.15(E2 클래식·변형). 엔진 난이도는 전파가 있는 탐색의 비용을 잘 설명한다.
