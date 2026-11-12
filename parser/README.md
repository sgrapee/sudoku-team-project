# llm_parser — 자연어 규칙 → JSON 명세 (③ AI 연동 파트)

변형 스도쿠 규칙 문장을 `engine/sudoku_engine/spec.py` 형식의 JSON 명세로 바꾸고,
엔진 검증을 통과할 때까지 실패 사유를 LLM에게 되먹여 재시도한다. 엔진 코드는 수정하지 않는다.

```bash
cd parser
pip install pytest                  # FactChat 연결은 표준 라이브러리만 사용 (추가 설치 불필요)
python -m pytest -q tests/          # 159개 통과 + 실제 API 테스트 1개 skip (API 키 불필요)

python -m llm_parser.evaluate --client oracle      # 채점기 점검 (100%여야 정상)
python -m llm_parser.evaluate --client noisy       # 재시도 루프 점검 (가짜 LLM이 일부러 틀림)

python -m llm_parser.baseline --client noisy       # LLM 단독 풀이 vs 파서+엔진 비교 (가짜 LLM)
python -m llm_parser.solver_eval --client oracle --limit 5   # LLM 파싱 → 백트래킹 / 지역 탐색 풀이 평가 (가짜 LLM)
python -m llm_parser.failures results/<결과>.jsonl # 파싱 실패 케이스 유형별 리포트
python -m llm_parser.datacheck 내문장.jsonl         # 팀원이 쓴 평가 문장 검사 (--append test 로 추가)
```

| 모듈 | 하는 일 |
|---|---|
| `parser.py` | 재시도 루프 `parse_rules` |
| `prompt.py` | 시스템 프롬프트, few-shot 5개 |
| `checks.py` | JSON 추출, 안전 검증, 그럴듯함 검사 |
| `clients.py` | LLM 연결(팀 기본: 숭실대 FactChat), API 오류 분류·백오프 |
| `canonical.py` | 표기가 달라도 의미가 같으면 같게 보는 정규화 |
| `evaluate.py` | 파싱 정확도 측정 |
| `baseline.py` | **LLM 단독 풀이 baseline** — 같은 퍼즐을 LLM이 혼자 풀 때와 파서+엔진으로 풀 때 비교 |
| `solver_eval.py` | **LLM 연동 풀이 평가** — LLM 명세로 백트래킹 vs 지역 탐색 비교 |
| `failures.py` | **파싱 실패 케이스 분류** — 결과 JSONL을 오류 유형별 리포트(마크다운·CSV)로 |
| `datacheck.py` | **평가 문장 추가 도구** — 팀원 기여 문장 검사 후 dev/test에 추가 |

## 실제 LLM으로 측정 — 숭실대 FactChat API Gateway

팀 LLM은 학교가 제공하는 **FactChat API Gateway**의 `gemini-3.5-flash`로 통일한다(`--client factchat`).
추가 설치가 필요 없다(표준 라이브러리만 사용). 공식 문서: https://docs.mindlogic.ai/docs/ssu/api-gateway/getting-started/overview

API 키는 **환경변수로만** 넣는다. 코드·테스트·README·커밋·단톡에 붙여넣지 말 것.

```powershell
# Windows PowerShell (키는 그 창에서만 유효, 창을 닫으면 다시 입력)
$env:FACTCHAT_API_KEY="본인 키"            # 학교 FactChat 사이트 → API 키 메뉴에서 발급. 다시 볼 수 없으니 따로 보관
$env:SUDOKU_LLM_MODEL="gemini-3.5-flash"   # 또는 명령마다 --model gemini-3.5-flash
python -m llm_parser.evaluate --client factchat --diagnose      # 키·크레딧·모델 목록·짧은 요청 확인
python -m llm_parser.evaluate --client factchat --split dev     # 규칙 문장 파싱 정확도
python -m llm_parser.solver_eval --client factchat              # 퍼즐 50개: 파싱 → 백트래킹 / 지역 탐색 (6-1절)
```

| 항목 | 내용 |
|---|---|
| 주소 | `https://factchat-cloud.mindlogic.ai/v1/gateway` (기본값. 바꿀 때만 `FACTCHAT_BASE_URL`) |
| 호출 | `POST /chat/completions/` (OpenAI 형식), 인증 `Authorization: Bearer <키>` |
| 모델 | 팀 기준 `gemini-3.5-flash`. 쓸 수 있는 모델은 `--list-models`로 확인 |
| 한도 | 회원당 60초 120회(초과 시 429 → 자동 재시도). 크레딧 소진 402, 모델 미허용 403 → 즉시 중단 |
| 크레딧 | 계정당 월 3,000, 매월 1일 갱신. **키를 만든 계정에서 차감**되므로 키를 팀원과 공유하지 말 것 |
| 사용량 확인 | 이 게이트웨이 응답에는 호출별 차감액이 오지 않았다. 측정 전후 `--diagnose`의 크레딧 값(또는 학교 사이트) 차이로 계산한다 |

실측 비용(gemini-3.5-flash): 규칙 문장 1개 약 12 크레딧, 퍼즐 설명 1개(단서 격자 포함) 약 16.6 크레딧.

| 옵션 (`evaluate`) | 의미 |
|---|---|
| `--split test/dev/all/nl` | 평가 데이터 선택 (기본 test). `nl`은 ④-A가 만든 자연어 퍼즐 설명 40개 |
| `--repeat N` | 같은 데이터로 N회 반복, 평균 ± 표준편차 출력 |
| `--sleep 초` | 호출 사이 최소 간격 |
| `--model 이름` / `--list-models` | 모델 지정 / 내 키로 쓸 수 있는 모델 목록 |
| `--resume 파일` | 중간에 멈춘 `*_partial_*.jsonl`부터 이어서 측정(끝난 문장은 다시 호출하지 않음) |
| `--no-strict` | 그럴듯함 검사 끄기(비교 실험용) |

- `temperature`·`response_format`은 보내지 않는다(GPT-5 계열은 temperature 1만 허용, JSON 모드는 문서에 없음). 형식은 프롬프트 + 재시도로 맞춘다
- 추론형 모델은 생각 토큰이 `max_tokens`에 포함된다. baseline처럼 긴 답이 필요하면 `--max-tokens 16000` 이상 권장(문서 권고)
- 키·크레딧 문제는 즉시 한국어 한 줄로 알리고 멈춘다. 중간에 멈추면 그때까지 결과를 `results/*_partial_*.jsonl`로 저장
- 결과: `results/<split>_<모델>_<시각>.jsonl`(문장별 원문 출력, 시도별 단계·사유·토큰·지연, API 오류) + `_summary.json`
- `clients.py`에는 예전에 시험한 Gemini 직접 연결·OpenAI·Anthropic 클라이언트도 남아 있지만 팀에서는 쓰지 않는다

---

## 1. 다른 파트에서 호출할 때

```python
from llm_parser import parse_rules
from llm_parser.checks import extract_givens
from llm_parser.clients import make_client

client = make_client("factchat", "gemini-3.5-flash")      # FACTCHAT_API_KEY 환경변수 필요
result = parse_rules(rule_text, client, givens=extract_givens(puzzle_text), check_solvable=True)
result.status       # "ok" | "unsupported" | "failed" | "api_error"
result.spec         # load_spec()에 바로 넣을 수 있는 명세 (givens는 코드가 붙임)
result.unsupported  # 지원하지 않거나 정보가 부족해 빠진 규칙 원문
result.attempts     # 시도별 원문 출력, 거부 단계, 사유, 토큰, 지연
result.error        # api_error일 때 {"kind": "auth" | "billing" | "refusal" | ..., "message": ...}
```

| status | 의미 |
|---|---|
| `ok` | 모든 규칙을 명세로 변환, 검증 통과 |
| `unsupported` | 검증 통과. 단, 지원하지 않거나 정보가 부족한 규칙이 `unsupported`에 있음 |
| `failed` | `max_attempts`번 시도했지만 검증을 통과하지 못함 |
| `api_error` | LLM 호출 자체가 실패(인증·크레딧·거부·재시도 소진·빈 응답 반복 등) |

## 2. 설계

### 범위를 좁히는 설계 제약
에이전트가 사람 없이 혼자 푸는 게임이므로 LLM이 틀릴 수 있는 지점을 줄였다.

| 제약 | 이유 |
|---|---|
| 9×9 표준 격자만 | size·box 필드 오류 원천 차단 |
| 지원 제약은 spec.py의 9종, 나머지는 `unsupported` | 비슷한 제약으로 억지 매핑하는 환각 방지 |
| 좌표는 1-indexed `"r1c1"`로 출력, 0-indexed 변환은 엔진 코드 | "해석은 LLM, 변환은 코드" |
| givens(81자 단서)는 코드가 붙이고 형식을 미리 검사 | 81칸 옮겨 적기는 LLM이 가장 잘 틀리는 작업 |
| 정보가 부족하면 추측하지 않고 `unsupported`에 "정보 부족: ..." | 좌표·합을 지어내면 조용한 오답이 됨 |

### 검증 단계 (거부되면 사유를 다음 프롬프트에 넣어 재시도, 최대 `max_attempts`회)

| 단계 | 내용 |
|---|---|
| `api` | 호출 실패. 네트워크·429·서버 오류는 클라이언트가 5→10→20→40→60초 백오프로 재시도. 빈 응답·길이 초과는 "짧게 다시"로 재시도. 인증·크레딧·모델 거부는 즉시 `api_error` |
| `format` | 응답에서 JSON 객체 추출(코드펜스·잡담 허용), `constraints` 배열 확인 |
| `engine` | `validate_spec`. 엔진이 크래시하는 입력이 있어 `safe_validate`로 감쌈 |
| `plausibility` | 엔진은 통과시키지만 파싱 실수일 가능성이 높은 패턴: 케이지 겹침·떨어진 케이지, 끊긴 온도계·화살표, 떨어진 부등호, 의미가 같은 제약의 중복 |
| `solvable` | `check_solvable=True`일 때 해가 없으면 거부. **시간 초과는 거부하지 않음**(엔진 결함 C 방어) |

### 프롬프트 (`prompt.py`)
- 규칙 문장은 `<rule>...</rule>`로 감싸 **데이터**로 전달하고, 그 안의 지시는 따르지 않도록 명시(프롬프트 인젝션 방어). 문장 안의 `</rule>`은 무력화
- 퍼즐을 풀지 말 것, 추측하지 말 것, givens를 출력하지 말 것, 억지 변환 금지, JSON만 출력
- few-shot 5개: 단일 규칙 / 여러 규칙 조합 + 대각선 두 개 / 대각선 하나(alldiff) + 샌드위치 index / 부등호 방향 + 미지원 혼합 / 정보 부족 + 지원 규칙

## 3. 평가 데이터 (`data/`)

| 파일 | 문장 | 용도 |
|---|---|---|
| `rules_dev.jsonl` | 18 | 프롬프트를 고칠 때만 사용 |
| `rules_test.jsonl` | 36 | 최종 보고용. few-shot과 겹치지 않음(테스트로 보장) |

한 줄 = `{"id", "text", "gold": {"constraints": [...], "unsupported": bool}, "tags": [...]}`.
기존 42문장(R01–R42)에 아래 12문장(N01–N12)을 추가했다.

| 태그 | 의미 | test / dev |
|---|---|---|
| `typo` | 좌표 표기 오타·변형 (`R3C4`, `r6 c2`) | 1 / 1 |
| `ambiguous` | 좌표·합이 없는 애매한 지시 → `unsupported` 기대 | 2 / 1 |
| `injection` | 규칙 문장 안의 지시문 ("이전 지시를 무시하고…") | 1 / 1 |
| `direction_trap` | 부등호 방향 ("크다", "작지 않다") | 2 / 1 |
| `row_col_trap` | 가로줄/세로줄 샌드위치 | 1 / 1 |
| `partial_support` | 지원 + 미지원이 섞인 복합 문장 | 3 / 0 |
| `duplicate` | 같은 제약을 두 번 설명 | 1 / 0 |
| `index_trap` | 샌드위치 index(유일하게 0부터) | 3 / 4 |
| `diagonal_trap` | 대각선 하나 → alldiff | 1 / 1 |

"합이 1 틀린 조용한 오류"는 문장이 아니라 LLM 출력의 실수라서 `noisy` 클라이언트(`silent_flip`)로 재현한다.

**dev·test는 ③ 한 사람이 써서 표현이 치우쳐 있다.** 이를 보완하는 독립 세트로 ④-A의 자연어 퍼즐 설명을 쓴다.

### `--split nl` — ④-A 자연어 퍼즐 설명 40개 (`puzzles/nl_prompts.jsonl`)

`datagen/nl_prompts.py`가 ④의 퍼즐에서 만든 "문제 설명 전체 + 정답 명세" 쌍. ③이 쓰지 않은 문장이다.

- 변형: thermo 10, arrow 10, 대각선+온도계+화살표 혼합 10, diagonal 6, classic 4
- 좌표 표기 3종(`r3c2` / `3행 2열` / `(3, 2)`) × 단서 격자 2종(9줄 / 81자 한 줄)을 번갈아 사용
- 문장 안에 단서 격자가 들어 있지만 LLM이 옮겨 적지 않는다. **`checks.extract_givens`가 코드로 꺼내고**,
  그 정확도를 "단서 격자 추출(코드)" 지표로 따로 보인다(40/40 확인)
- 정답 명세는 엔진 검증·그럴듯함 검사를 모두 통과한다(테스트로 보장). few-shot과 겹치지 않는다
- 태그: 변형 이름, `coord_rc/korean/paren`, `grid_rows/string`, `nl4a` — 표기별 정확도를 바로 볼 수 있다

```powershell
python -m llm_parser.evaluate --client factchat --split nl
```

## 4. 지표

| 지표 | 정의 |
|---|---|
| 최종 정답률 | 문장 완전일치(제약 멀티셋 + unsupported 여부) |
| 첫 시도 정답률 | 첫 응답만으로 정답이었던 비율. 최종 정답률과의 차이 = 재시도의 실제 효과 |
| 제약 P / R / F1 | 제약 단위 micro |
| 첫 시도 / 최종 검증 통과율 | 엔진·그럴듯함 검사 통과 비율. **정답률이 아님**(조용한 오류도 통과함) |
| unsupported 판별 정확도 | 미지원·정보 부족 여부를 맞힌 비율 |
| 평균 API 호출 / 응답 시간 | 문장당 |
| API 오류 | 건수와 종류 |
| 토큰 / 예상 비용 | 실제 클라이언트만 기록. 비용은 `--price-in/--price-out`을 줄 때만 |

비교는 `canonical.py`로 정규화한 뒤 한다. `"r1c1"`과 `[0,0]`, `greaterthan`과 뒤집힌 `lessthan`,
짝수 칸 묶음과 칸별 짝수는 같게 보고, **부등호 방향과 온도계 순서는 다르게** 본다.

**가짜 LLM 결과 (test 36문장, 2026-11-03)**

| | oracle | noisy |
|---|---|---|
| 최종 정답률 | 100% | 94.4% |
| 첫 시도 정답률 | 100% | 25.0% |
| 첫 시도 → 최종 검증 통과율 | 100% → 100% | 30.6% → 100% |
| 평균 호출 | 1.00 | 1.69 |

noisy에서 틀린 2문장은 모두 검증을 통과해 버린 조용한 오류(부등호 방향 반전, 합 +1)다.

**실제 LLM 결과 (FactChat `gemini-3.5-flash`)**

| 데이터 | 결과 | 날짜 |
|---|---|---|
| dev 규칙 문장 18개 | 18/18 정답 | 2026-11-11 |
| 퍼즐 설명 50개 (nl 40 + examples 10) | 50/50 명세 완전일치, 전부 첫 시도, 단서 추출 50/50 | 2026-11-12 (6-1절) |
| test 규칙 문장 36개 | 아직 측정 안 함 | |

## 5. 피드백 반영 범위 (2026-11-03)

| 항목 | 반영 |
|---|---|
| 2-3 API 예외 처리 | ✅ `api_error` 상태, `api` 단계, 오류 종류 구분, 백오프, `max_attempts` 검사, 결과 JSONL 기록 |
| 2-4 프롬프트 보강 | ✅ 원칙 명시, `<rule>` 데이터 경계, few-shot 5개 재구성 |
| 3-1 데이터 분리 | ✅ dev 18 / test 36, 새 평가 사례 12개 |
| 3-2 지표 정리 | ✅ `final_pass` → `final_validation_pass`, 첫 시도/최종 정답률, 응답 시간, API 오류, 토큰·비용 |
| 3-3 실제 LLM 평가 준비 | ✅ `--repeat`, 모델명·실행 시각·반복 번호·지연·원문·오류 저장, 키 없으면 실제 API 테스트 skip |
| 4-3 저장소 정리 | ✅ 배포 zip에서 캐시 제거, `parser/.gitignore`에 `results/` (보고용 결과만 `git add -f`로 올림) |
| 공통 요청 | ✅ 저장소 루트 `examples/`에 명세 5개 (`examples/README.md`) |
| 1-x 엔진 수정 | ⛔ ② 담당. PR #5에서 해결(③이 검증), `engine_fixes/`에 처리 현황 기록 |
| 2-1 Structured Outputs, 2-2 needs_clarification | ⏸ 이번 범위에서 제외 (정보 부족은 `unsupported`의 "정보 부족:"으로 기록) |
| 4-1 루트 README, 4-2 패키징, 4-4 CI | ⏸ ① 결정 사항이라 제외 |

## 6. LLM 단독 풀이 baseline (`baseline.py`)

역할표의 ③ 업무 "LLM 단독 풀이 baseline". 같은 퍼즐을 두 방식으로 풀어 **탐색 엔진이 왜 필요한지**를 수치로 보인다.

| 방식 | 내용 |
|---|---|
| LLM 단독 | 규칙 문장 + 단서 격자를 주고 LLM이 81자 정답 격자를 직접 출력(풀이 과정 서술 허용, 마지막에 JSON) |
| 파서 + 엔진 | 같은 LLM으로 규칙 → JSON 명세(③), ② 엔진이 탐색으로 풀이 |

- 퍼즐: `examples/` 변형 전부(현재 10개) + `engine/puzzles_easy·hard.txt` 앞 5개씩(일반 스도쿠) = 20개
- 지표: 정답률, 제약 만족률, 칸 정확도·단서 유지율(격자를 얻은 경우), 위반 제약 수(기본 27개 / 변형), 격자를 못 얻은 건수, 호출 수, 시간, 토큰
- 실제 LLM: `python -m llm_parser.baseline --client factchat --model gemini-3.5-flash --max-tokens 16000` (아직 실행 안 함)
- 가짜 LLM 결과(noisy, 20퍼즐): LLM 단독 정답률 0%(칸 정확도 92.0%, 기본 제약 평균 10.67개 위반, 형식 실패 5건) vs 파서+엔진 100%.
  **noisy는 일부러 칸을 틀리게 만든 가짜 LLM이라 실제 LLM 성능이 아니다.** 채점기가 차이를 제대로 잡는지 확인하는 용도

## 6-1. LLM 연동 풀이 평가: 백트래킹 vs 지역 탐색 (`solver_eval.py`)

자연어 퍼즐 50개(nl_prompts 40 + examples 10)를 LLM이 **퍼즐당 한 번** 파싱하고, 같은 명세를
② 백트래킹(`solve`)과 ② 지역 탐색(`solve_local_search`)에 그대로 넣는다. 정답 격자와 비교해 채점한다.

```bash
python -m llm_parser.solver_eval --client oracle --limit 5                      # 점검 (LLM 호출 없음)
python -m llm_parser.solver_eval --client factchat --model gemini-3.5-flash     # 실제 (약 50회 호출 + 재시도)
python -m llm_parser.solver_eval --specs results/solver_specs_<...>.jsonl       # 파싱 결과 재사용 (크레딧 0)
```

- 방법: 백트래킹 2종(mrv_degree/lcv/ac3, static/asc/none), min-conflicts 2종(init random/row, `--trials`회 seed 반복). ② 벤치마크 기본값과 같다.
- 파싱 실패는 모든 방법에서 실패로 센다. 실패 시도의 시간은 `--time-limit`으로 센다.
- 같은 퍼즐을 정답 명세(LLM 없음)로도 풀어 "LLM 탓"과 "알고리즘 탓"을 나눈다.
- 결과: `results/solver_eval_*.md`(보고서용 표), `_summary.json`, `.jsonl`(시도별).

**결과 (2026-11-12, FactChat `gemini-3.5-flash`, 풀이 제한 5초, 지역 탐색 seed 3회)** — `results/solver_eval_all_gemini-3.5-flash_20261112-160348.md`

| 방법 | 정답률 | 평균 시간 (실패 = 5초) |
|---|---|---|
| 백트래킹 mrv_degree/lcv/ac3 | 100% (50/50) | 70ms |
| 백트래킹 static/asc/none | 6% (3/50) | 4.9초 |
| min-conflicts random | 0% (0/150) | 5초 (전부 시간 초과) |
| min-conflicts row | 0% (0/150) | 5초 (전부 시간 초과) |

- 파싱이 50/50 완전일치라 LLM 명세 결과와 정답 명세 결과가 같다 → 차이는 전부 알고리즘에서 나온다
- 지역 탐색 점검: 정답 격자에서 빈칸 35개 이하는 모두 풀지만(3초, seed 3회) 실제 퍼즐(빈칸 50~60개)은 30초에도 못 푼다. 결함이 아니라 min-conflicts가 지역 최솟값에 갇히는 특성
- 크레딧 없이 다시 돌리기: `--specs results/solver_specs_gemini-3.5-flash_20261112-160348.jsonl` (사용 약 830 크레딧)

## 7. 파싱 실패 케이스 분류 (`failures.py`)

역할표의 ③ 업무 "파싱 실패 케이스 수집". `evaluate` 결과 JSONL을 넣으면 오답 문장마다 원인을 붙인다.

| 유형 | 판별 기준 |
|---|---|
| 부등호 방향 반전 / 온도계 방향 반전 / 짝·홀 반전 | 같은 칸, 방향·성질만 반대 |
| 합 오류 | 킬러·샌드위치의 칸(줄)은 같고 합만 다름 |
| 좌표 1칸 밀림 | 같은 모양이 행·열로 ±1 이동 (0/1 인덱스 혼동의 흔적) |
| 샌드위치 줄 번호 ±1 / 행·열 혼동 | 합은 같고 줄만 다름 |
| 대각선 하나·둘 혼동 | diagonal ↔ 9칸 alldiff |
| 내용 오류 / 제약 누락 / 제약 추가(환각) | 위에 해당하지 않는 차이 |
| 미지원·정보 부족을 놓침 / 지원 규칙을 미지원 처리 | unsupported 판별 오류 |
| 검증 실패: 단계 / API 오류: 종류 | 끝내 검증을 통과하지 못함 / 호출 실패 |

재시도로 결국 맞힌 문장의 중간 거부도 "복구된 오류"로 집계한다. CSV는 엑셀에서 바로 열리도록 UTF-8 BOM을 붙인다(④ 실패 사례 분석용).

## 8. 팀원이 평가 문장을 추가하는 방법 (`datacheck.py`)

test 세트를 한 사람이 쓰면 표현이 치우친다. 다른 팀원이 쓴 문장을 넣는 것을 권장한다.

1. 아래 형식으로 한 줄에 한 문장씩 `내문장.jsonl`을 만든다 (좌표는 1부터, 샌드위치 index만 0부터)

```json
{"id": "K01", "text": "r2c2, r2c3 케이지의 합은 5이다.", "gold": {"constraints": [{"type": "killer", "cells": ["r2c2", "r2c3"], "sum": 5}], "unsupported": false}, "tags": ["killer", "rc"], "author": "④"}
{"id": "K02", "text": "가운데 어딘가에 화살표가 있다.", "gold": {"constraints": [], "unsupported": true}, "tags": ["ambiguous", "unsupported"], "author": "④"}
```

2. `python -m llm_parser.datacheck 내문장.jsonl` — 오류(✗)가 없을 때까지 고친다
   - 오류: id·문장 중복, few-shot과 같은 문장, 정답 명세가 엔진 검증 실패, unsupported가 true/false가 아님
   - 경고(△): 그럴듯함 검사, 처음 보는 태그 — 의도한 것이면 그대로 둬도 된다
3. `python -m llm_parser.datacheck 내문장.jsonl --append test` — 모두 통과하면 `rules_test.jsonl`에 추가

**프롬프트를 고친 뒤 test 결과를 보고 다시 고치면 test가 dev가 된다.** 새 문장은 프롬프트를 확정한 뒤 평가에만 쓰는 것이 좋다.

## 9. 2026-11-10 main 기준 변경 사항

| 변경 | 내용 |
|---|---|
| 결과 파일 이름 | `<split>_<모델>_<시각>.jsonl` — dev·test·nl 결과가 이름으로 구분된다 |
| `--split nl` | ④-A 자연어 퍼즐 설명 40개를 독립 평가 세트로 사용, 단서 격자는 코드로 추출 |
| `checks.extract_givens` | 문장 속 단서 격자(9줄 / 81자)를 코드로 추출 — GUI·파이프라인에서 재사용 가능 |
| noisy 가짜 LLM | `[0, 0]` 형식 좌표에서도 "좌표 오타" 흉내가 동작하도록 수정(④ 명세 형식 대응) |
| `engine_fixes/` | PR #5(②)가 결함 A·B·C와 입력 크래시를 모두 고친 것을 확인. 겹치는 패치는 삭제하고 처리 현황·검증 결과만 기록 |
| 결함 A 회피 | PR #5 머지 전에도 동작하도록 풀이 가능성 검사·baseline 풀이에 `fc` 전파 사용 |

### 2026-11-12 변경 사항

| 변경 | 내용 |
|---|---|
| FactChat 클라이언트 | `--client factchat` — 숭실대 API Gateway 연결, `--diagnose`(키·크레딧·모델·짧은 요청) |
| `solver_eval.py` | LLM 파싱 1회 → 같은 명세로 백트래킹 / 지역 탐색 비교, 파싱 결과 재사용(`--specs`) |
| 결과 | `results/`에 11-12 평가 결과 4개만 남기고 무료 Gemini 시절 결과는 삭제 |

## 10. 알려진 한계

- 실제 LLM 측정은 모델 1개(`gemini-3.5-flash`), 1회 실행이다. test 36문장과 baseline은 아직 실제 LLM으로 돌리지 않았다
- 퍼즐 설명 50개는 ④ 생성기가 만든 정형화된 문장이라 50/50이 나왔다. 사람이 자유롭게 쓴 문장에서는 더 낮을 수 있다
- 지역 탐색 비교는 제한 5초 기준이다. 시간(ms)은 컴퓨터마다 달라 상대 비교만 의미가 있다
- 샌드위치 index만 0부터 세서 LLM이 틀리기 쉽다(엔진이 1-indexed 키를 받아주면 해결 → ② 협의)
- FactChat에는 temperature·JSON 모드를 보내지 않아 반복마다 결과가 다를 수 있다 → 필요하면 `--repeat`으로 편차 보고
- 그럴듯함 검사는 표준 퍼즐 관례를 가정한다. 비표준 퍼즐은 `strict=False`
- 의미 단위 비교라, 엔진에서 동치인 다른 표현(9칸 alldiff 두 개 vs diagonal)은 오답으로 잡힌다
- `injection` 문장의 정답은 "지시문은 무시, unsupported 아님"으로 정했다. 지시문을 unsupported에 적는 모델은 오답 처리된다
- 데이터가 54문장이라 test에서 1문장이 약 2.8%p다
- baseline 퍼즐은 20개뿐이다(examples 10 + 일반 10). ④ 생성기 퍼즐을 `examples/` 형식(rules_text·solution 포함)으로 추가하면 자동으로 늘어난다
- 실패 유형 분류는 규칙 기반이라, 여러 실수가 겹친 문장은 "내용 오류"나 "누락/추가"로 뭉뚱그려질 수 있다
- `datacheck`는 정답 명세가 문장과 실제로 일치하는지까지는 확인하지 못한다. 문장과 정답은 작성자가 직접 대조해야 한다
