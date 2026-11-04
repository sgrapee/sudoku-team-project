# ② 엔진 결함 보고 (③ 파서 연동 중 발견)

적용: 저장소 루트에서 `patch -p0 < parser/engine_fixes/engine_fixes.patch`
(또는 `git apply parser/engine_fixes/engine_fixes.patch`)

적용 후 `engine/` 테스트 **84개 통과**(기존 77 + 회귀 7). demo.py 출력과 일반 스도쿠 벤치마크는 변화 없음.

---

## A. 9칸 미만 alldiff에 hidden single을 적용 → 해가 있는데 "해 없음"

`model.units`가 모든 `AllDifferent`를 유닛으로 등록하고, AC-3의 `_hidden_singles_unit`이
"값 1~9가 유닛 안에 반드시 한 번 나온다"고 가정한다. 이 가정은 9칸 묶음(행·열·박스·대각선)에서만 맞다.

- 재현: 빈 격자 + `AllDifferent([(0,0),(0,1)])` → `propagation="ac3"`·`"full"`에서 `solved=False`
- spec.py의 `"alldiff"`(사용자 정의 영역)는 거의 항상 9칸 미만이라 이 경로를 탄다
- 수정: 유닛은 `len(scope) == grid.size`인 AllDifferent만. `AllDifferent.propagate`의 hidden single에도 같은 조건 추가

## B. 킬러 케이지의 합 전파가 FC/AC-3에서 호출되지 않음

`global_constraints = [con for con in constraints if not con.binary_arcs()]`인데,
`KillerCage(distinct=True)`는 케이지 내부 != 아크를 반환하므로 전역 제약에서 빠진다.
그 결과 `_propagate_exact`(완전 필터)·`_propagate_bounds`가 **탐색 중 한 번도 호출되지 않고**,
합은 `check()`로만 검사된다. README의 "킬러 완전 필터링"이 실제로는 동작하지 않는 상태.

- 재현: 빈 격자 + `KillerCage([(7,7),(7,8),(8,7),(8,8)], 30)` → ac3에서 10초 시간 초과
- 수정 후: 같은 문제 0.02초. `KillerCage([(0,0),(0,1)], 3)` 초기 전파 후 두 칸 도메인이 `{1,2}`로 축소
- 수정: 전역 제약 = `AllDifferent`가 아닌 모든 제약 (아크와 별도 전파를 둘 다 갖는 제약도 propagate 호출)

## C. 시간 초과를 "해가 존재하지 않습니다"로 보고

`spec_to_model_or_reason`이 `count_solutions(...) == 0`만 보고 판정하는데,
`count_solutions`는 시간 초과 시에도 찾은 해 개수(0)를 돌려준다.
③ 파서는 이 메시지를 받으면 멀쩡한 명세를 "해 없음"으로 거부하고 재시도하게 된다.

- 수정: `Solver`를 직접 만들어 `stats.timed_out`을 확인하고 "판정 불가" 메시지를 따로 반환

## 영향 측정

정답 격자에서 뽑은 (서로 다른 숫자의) 킬러 케이지 + 부분 alldiff를 30단서 퍼즐 15개에 걸고
fc / ac3 / full로 푼 168회:

| | 정답 도출 | "해 없음" 오판 |
|---|---|---|
| 기존 엔진 | 98 | **70** |
| 수정 엔진 | 168 | 0 |

README §3의 "전파 건전성 60회 오제거 0건" 시험은 9칸 미만 alldiff와 ac3 조합,
그리고 단서가 적은 킬러 퍼즐을 포함하지 않아 이 결함들이 드러나지 않았던 것으로 보인다.

## 추가 발견 (2026-11-03, 팀원 피드백 검증 중) — 패치에 아직 미포함

- **크기가 9×9가 아닌 중첩 배열 givens가 오류 없이 통과한다.** `{"givens": [[5,3,0],[6,0,0]]}` →
  `validate_spec`이 `True`를 반환. `_parse_givens`의 list 분기에서 행·열 개수를 검사하지 않는다.
  ③은 givens를 81자 문자열로만 받도록 막아 두었다(`parse_rules`의 `_validate_givens`).
- 팀원 피드백 1-4에서 지적한 크래시 입력 재확인: `"R1-C1"`, `"sum": "열둘"`, 1칸 온도계, 80자 givens,
  잘못된 sandwich 방향(`"line": "diag"`), 숫자가 아닌 index → 모두 `ValueError`로 크래시.
  `constraints: null`·문자열은 이미 정상 거부된다.

## 협의 요청 (결함 아님)

- `load_spec`에서 `ValueError`/`TypeError`도 `SpecError`로 감싸기 (현재 `"R1-C1"`, `"sum": "열둘"`, 1칸 온도계, 80자 givens에서 크래시). ③은 안전 래퍼로 대응 중
- 샌드위치에 1-indexed 키(예: `"number": 3`) 허용 — LLM 출력의 유일한 0-indexed 필드라 오류가 몰린다
