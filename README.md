# 변형 스도쿠 AI 프로젝트

자연어로 설명한 변형 스도쿠 규칙을 LLM이 JSON 제약 명세로 변환하고,
직접 구현한 제약 충족 문제(CSP) 엔진이 퍼즐을 검증하고 풀이하는 프로젝트입니다.

## 무엇을 보면 되나요?

| 목적 | 위치 |
|---|---|
| 스도쿠 풀이 알고리즘 확인 | `engine/sudoku_engine/` |
| 자연어를 JSON으로 바꾸는 AI 코드 확인 | `parser/llm_parser/` |
| 바로 실행해 보기 | `engine/demo.py` |
| 변형 스도쿠 예제 확인 | `examples/` |
| 엔진 테스트 | `engine/tests/` |
| AI 파서 테스트 | `parser/tests/` |
| AI 평가 문장과 결과 확인 | `parser/data/`, `parser/results/` |
| 생성된 난이도별 퍼즐 데이터 | `puzzles/` |
| 퍼즐 생성·검증 코드 | `datagen/` |
| 알고리즘 성능 비교 | `python run_bench.py` |
| 발표 시연용 화면 실행 | `python run_gui.py` |

## 폴더 구조

```text
sudoku-team-project/
├─ engine/                 # 스도쿠 풀이·생성·난이도 판정 엔진
│  ├─ sudoku_engine/       # 엔진 소스 코드
│  ├─ tests/               # 엔진 테스트
│  ├─ demo.py              # 엔진 실행 예제
│  └─ README.md            # 엔진 상세 설명
├─ parser/                 # 자연어 규칙 → JSON 명세 LLM 파서
│  ├─ llm_parser/          # 파서 소스 코드
│  ├─ data/                # 개발·평가 문장 데이터
│  ├─ tests/               # 파서 테스트
│  ├─ results/             # LLM 평가 결과
│  ├─ engine_fixes/        # 발견된 엔진 문제와 수정 패치
│  ├─ requirements.txt
│  └─ README.md            # 파서 상세 설명
├─ examples/               # 공용 변형 스도쿠 JSON 예제
├─ puzzles/                # 종류·난이도별 생성 퍼즐 데이터셋
├─ datagen/                # 퍼즐 생성 및 데이터 검증 도구
├─ gui/                    # 발표 시연용 데스크톱 GUI
├─ run_gui.py              # GUI 바로 실행
├─ run_bench.py            # 탐색 알고리즘 벤치마크
├─ .gitignore
└─ README.md
```

## 발표 시연용 GUI

외부 GUI 패키지 없이 Python 기본 `tkinter`로 실행됩니다.

```powershell
python run_gui.py
```

예제 선택, 숫자 입력, 변형 제약 시각화, 논리 힌트, 자동 풀이, 난이도·유일해·탐색 통계를 한 화면에서 확인할 수 있습니다.
상세한 시연 순서는 [GUI 문서](gui/README.md)를 참고하세요.

## 빠른 실행

### 1. 엔진 데모

```powershell
cd engine
python demo.py
```

### 2. 테스트

```powershell
python -m pip install pytest

cd engine
python -m pytest -q tests

cd ../parser
python -m pip install -r requirements.txt
python -m pytest -q tests
```

### 3. LLM 파서 평가

```powershell
cd parser

# API 키가 필요 없는 모의 평가
python -m llm_parser.evaluate --client oracle
python -m llm_parser.evaluate --client noisy

# Gemini 실제 평가
$env:GEMINI_API_KEY="여기에_API_키"
python -m llm_parser.evaluate --client gemini --split test --sleep 6
```

API 키는 코드나 Git에 올리지 말고 환경변수로만 설정합니다.
세부 사용법은 [엔진 문서](engine/README.md), [LLM 파서 문서](parser/README.md),
[예제 명세 문서](examples/README.md)를 참고하세요.

## 전체 처리 흐름

```text
자연어 규칙
   ↓
LLM 파서 (parser)
   ↓
JSON 제약 명세
   ↓
명세 검증 및 재시도
   ↓
CSP 스도쿠 엔진 (engine)
   ↓
해답·유일해 여부·난이도·힌트
```
