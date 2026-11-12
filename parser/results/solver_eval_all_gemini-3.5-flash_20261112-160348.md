# LLM 연동 풀이 평가 — factchat:gemini-3.5-flash

퍼즐 50개 · 풀이 제한 5.0초 · 지역 탐색 seed 3회

## 1. 파싱 (LLM, 퍼즐당 1회)

| 퍼즐 | 파싱 사용 가능(ok+unsupported) | 명세 완전일치 | 실패(failed) | API 오류 | 단서 추출 정확 | 평균 호출 수 | 사용 크레딧(응답 기준) |
|---|---|---|---|---|---|---|---|
| 50 | 50 | 50 | 0 | 0 | 50 | 1 | - |

## 2. LLM 명세 → 풀이 (파싱 실패는 실패로 셈)

| method | kind | 정답 | 정답률 | 풀이 성공률 | 시간 초과 | 중앙값 ms(정답만) | 평균 ms(실패=제한) |
|---|---|---|---|---|---|---|---|
| backtracking/mrv_degree/lcv/ac3 | backtracking | 50/50 | 100% | 100% | 0 | 46.6 | 70.1 |
| backtracking/static/asc/none | backtracking | 3/50 | 6% | 6% | 47 | 2037.0 | 4854.8 |
| min-conflicts/random/noise0.05 | local_search | 0/150 | 0% | 0% | 150 | - | 5000.0 |
| min-conflicts/row/noise0.05 | local_search | 0/150 | 0% | 0% | 150 | - | 5000.0 |

## 3. 정답 명세 → 풀이 (LLM 없음, 알고리즘 자체의 한계)

| method | kind | 정답 | 정답률 | 풀이 성공률 | 시간 초과 | 중앙값 ms(정답만) | 평균 ms(실패=제한) |
|---|---|---|---|---|---|---|---|
| backtracking/mrv_degree/lcv/ac3 | backtracking | 50/50 | 100% | 100% | 0 | 46.6 | 70.1 |
| backtracking/static/asc/none | backtracking | 3/50 | 6% | 6% | 47 | 2037.0 | 4854.8 |
| min-conflicts/random/noise0.05 | local_search | 0/150 | 0% | 0% | 150 | - | 5000.0 |
| min-conflicts/row/noise0.05 | local_search | 0/150 | 0% | 0% | 150 | - | 5000.0 |

## 4. 난이도별 정답률 (LLM 명세)

| tier | backtracking/mrv_degree/lcv/ac3 | backtracking/static/asc/none | min-conflicts/random/noise0.05 | min-conflicts/row/noise0.05 |
|---|---|---|---|---|
| - | 100% | 40% | 0% | 0% |
| easy | 100% | 0% | 0% | 0% |
| expert | 100% | 8% | 0% | 0% |
| hard | 100% | 0% | 0% | 0% |
| medium | 100% | 0% | 0% | 0% |

## 5. 변형별 정답률 (LLM 명세)

| variant | backtracking/mrv_degree/lcv/ac3 | backtracking/static/asc/none | min-conflicts/random/noise0.05 | min-conflicts/row/noise0.05 |
|---|---|---|---|---|
| arrow | 100% | 0% | 0% | 0% |
| arrow+diagonal+thermo | 100% | 0% | 0% | 0% |
| arrow+lessthan | 100% | 0% | 0% | 0% |
| classic | 100% | 0% | 0% | 0% |
| diagonal | 100% | 0% | 0% | 0% |
| diagonal+killer+sandwich | 100% | 100% | 0% | 0% |
| diagonal+thermo+arrow | 100% | 0% | 0% | 0% |
| even+odd+thermo | 100% | 0% | 0% | 0% |
| killer | 100% | 50% | 0% | 0% |
| thermo | 100% | 9% | 0% | 0% |
