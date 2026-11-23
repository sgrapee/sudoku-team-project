# 실험 결과 (E1·E2·E3·E4)

백트래킹 탐색 실험 결과를 모은 폴더다. 백트래킹 vs 로컬서치 비교는 [compare/README.md](compare/README.md)에 따로 있다.
실험 설계와 스크립트 사용법은 저장소 루트의 `README_4B.md`에 있다.

## 폴더

| 폴더 | 실험 | 실행일 | 만든 방법 |
|---|---|---|---|
| `E1_full/` | E1 탐색 휴리스틱: 전파 FC 고정, 변수 순서(static / mrv / mrv_degree) × 값 순서(asc / lcv) 6설정 | 2026-11-18 | `run_bench.py --experiment E1` |
| `E2_full/` | E2 전파 강도: mrv + asc 고정, 전파 none / fc / ac3_pure / ac3 / full 5설정 | 2026-11-11 (ac3_pure만 2026-11-18) | `run_bench.py --experiment E2` |
| `E3_full/` | E3 변형 제약 효과: 같은 단서에서 변형 제약을 켰을 때와 껐을 때 | 2026-11-18 | `datagen/variant_effect.py` |

E1·E2는 같은 퍼즐 499개를 세 묶음으로 나눠 돌렸다.

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

## 실행 조건 (해석 전에 읽을 것)

- 퍼즐·설정마다 제한 5초. 한 컴퓨터에서 프로세스 4개를 동시에 돌렸다(classic, variant 두 묶음, special).
- 그래서 **시간(`elapsed_ms`)에는 병렬 부하가 섞여 있다.** 시간은 보조 지표로 보고, 비교는 결정적인 `branch_nodes`(값을 2개 이상 시도한 분기 노드 수)로 한다.
- 제한 시간 근처에서 끝나는 실행(E2 none, E1 static)은 부하에 따라 시간 초과 여부가 바뀔 수 있다.
- E2의 `ac3`는 hidden single 검사를 포함한 AC-3다(엔진 `propagation.py`의 `ac3()`). 순수 AC-3는 `ac3_pure` 행이다.
- `ac3_pure` 행은 엔진에 이 단계를 더한 뒤(2026-11-18) 같은 퍼즐·같은 조건으로 그 설정만 돌려 덧붙였다(`run_bench.py --configs mrv_asc_ac3_pure`). 다른 설정과 다른 날 돌려서 **시간은 다른 행과 비교하지 않는다.** 분기 노드는 결정적이라 비교해도 된다.
- E3는 엔진 기본 설정(mrv_degree/lcv/ac3), 제한 10초, 프로세스 4개로 돌렸고, 해는 1000개까지 셌다.

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

variant는 시간을 줄이려고 diagonal·thermo·arrow와 killer·mixed 두 묶음으로 나눠 돌린 뒤 CSV를 합쳤다. 한 번에 돌려도 결과 형식은 같다.

지금 코드로 `--experiment E2`를 돌리면 `ac3_pure`까지 5설정이 한 번에 나온다(위 `E2_full/`은 4설정을 먼저 돌리고 `ac3_pure`를 나중에 덧붙인 것). 일부 설정만 돌리려면 `--configs`로 고른다.

```bash
# 예전 E2 4설정만
python run_bench.py --experiment E2 --configs mrv_asc_none mrv_asc_fc mrv_asc_ac3 mrv_asc_full ...
# ac3_pure만
python run_bench.py --experiment E2 --configs mrv_asc_ac3_pure ...
```

## 결과 요약

분기 노드는 모든 설정이 공통으로 푼 퍼즐 기준 중앙값이다(`E*_summary.csv`).

- **E1 탐색 휴리스틱**: static → MRV로 분기 노드가 약 100배 줄어든다(클래식 1561 → 15, 변형 3100 → 47). static은 변형 375개 중 36~40개가 시간 초과. degree 타이브레이크는 변형에서만 줄인다(47 → 37, Wilcoxon p = 3e-7, 클래식은 p = 0.41). LCV는 뚜렷한 차이가 없다.
- **E2 전파 강도**: 전파가 없으면 5초 안에 클래식 42/100, 변형 59/375만 푼다. 분기 노드는 클래식 none 7584 → fc 14 → ac3_pure 14 → ac3 1 → full 1, 변형 7536 → 23 → 9 → 1 → 1. 해 없음 12개는 fc·ac3_pure·ac3·full이 모두 증명하고 none은 6개만 증명한다.
- **순수 AC-3와 hidden single 나눠 보기**: 클래식에서는 `ac3_pure`와 fc의 분기 노드가 퍼즐 100개 모두 같다. 이진 != 아크만 있으면 순수 AC-3가 MRV + FC보다 더 줄이지 못하고, `ac3`의 14 → 1은 전부 hidden single 덕분이다. 변형에서는 순수 AC-3만으로도 크게 준다(중앙값 fc → ac3_pure: 온도계 64 → 17, 화살표 115 → 18, 킬러 213 → 12, 혼합 37 → 12, 대각선 16 → 16). 변형 제약의 전파를 고정점까지 돌리기 때문이다. 그 뒤 hidden single이 1~2까지 줄인다.
- **E3 변형 제약 효과**: 제약을 켜면 375개 모두 유일해, 끄면 93~100%가 해 1000개 이상이고 끈 상태의 첫 해가 원래 정답인 경우는 0개. 첫 해까지 분기 노드는 켰을 때 1, 껐을 때 16~29로 변형 제약이 탐색을 오히려 줄인다. 노드당 시간 비율(켬/끔)은 0.91~1.03. 혼합 퍼즐에서는 대각선을 빼면 유일해가 1/75만 남아 정보를 가장 많이 준다(화살표 6/75, 온도계 33/75). 숫자는 `E3_full/E3_summary.md`.
- **E4 난이도 vs 탐색 비용**: 엔진 난이도 level과 분기 노드의 스피어만 ρ는 ac3 0.70~0.73, full 0.83, ac3_pure 0.20~0.25, fc 0.20~0.23, none −0.02~0.15(E2 클래식·변형). 엔진 난이도는 hidden single이 들어간 전파(ac3·full)의 탐색 비용을 잘 설명한다. 순수 AC-3는 fc와 비슷한 수준이라, 상관을 만드는 것은 hidden single이다(엔진 난이도 자체가 hidden single 같은 인간 기법으로 매겨진다).
