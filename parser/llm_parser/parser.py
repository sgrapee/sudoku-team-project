"""재시도 루프: LLM 출력 → 검증 → 실패 사유를 LLM에 되먹임 → 재시도.

    from llm_parser import parse_rules, GeminiClient
    result = parse_rules("r1c1, r1c2 케이지 합 10", GeminiClient())
    result.status        # ok / unsupported / failed / api_error
    result.spec          # 엔진에 넘길 명세 (givens를 주면 코드가 붙임)
    result.attempts      # 시도별 원문 출력·거부 단계·사유·토큰·지연 (실패 케이스 수집용)
    result.error         # api_error일 때 {"kind": ..., "message": ...}

각 시도의 거부 단계(stage)
  api          LLM 호출 실패(빈 응답·길이 초과는 재시도, 인증·크레딧·거부·재시도 소진은 즉시 api_error)
  format       JSON 추출 실패, constraints 배열 아님
  engine       spec.py validate_spec 거부 (안전 래퍼로 감쌈)
  plausibility 케이지 겹침·끊긴 경로·의미 중복 등 (strict=True일 때)
  solvable     해가 없음 (givens가 있고 check_solvable=True일 때, 시간 초과는 거부하지 않음)
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from .checks import OutputFormatError, extract_json, plausibility_problems, safe_validate, split_output
from .clients import LLMAPIError, LLMClient
from .prompt import SYSTEM_PROMPT, build_messages

STATUSES = ("ok", "unsupported", "failed", "api_error")
STAGES = ("api", "format", "engine", "plausibility", "solvable")


@dataclass
class Attempt:
    raw_output: str
    stage: str                 # 거부된 단계(STAGES) 또는 "" (통과)
    feedback: str              # LLM에 되먹인 거부 사유 ("" = 통과)
    elapsed: float
    error_kind: str = ""       # stage == "api"일 때 오류 종류(clients.ERROR_KINDS)
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None


@dataclass
class ParseResult:
    status: str                       # STATUSES
    spec: dict | None                 # failed면 마지막으로 형식이 맞았던 명세라도 남김
    unsupported: list[str] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    solvability: str = ""
    error: dict | None = None         # api_error일 때 {"kind", "message"}

    @property
    def n_attempts(self) -> int:
        return len(self.attempts)

    def to_dict(self) -> dict:
        return asdict(self)


def _validate_givens(givens: str | None) -> None:
    """givens는 LLM이 아니라 호출자가 주는 값이므로, 형식이 틀리면 바로 알린다."""
    if givens is None:
        return
    if not isinstance(givens, str) or len(givens) != 81 or any(ch not in ".0123456789" for ch in givens):
        raise ValueError("givens는 81자 문자열이어야 합니다(빈칸은 '.' 또는 '0').")


def _solvability(spec: dict, givens: str, time_limit: float) -> tuple[bool, str]:
    """(거부해야 하는가, 메시지).

    엔진의 spec_to_model_or_reason은 시간 초과도 '해 없음'으로 보고하므로(엔진 결함 C)
    Solver를 직접 돌려 시간 초과와 해 없음을 구분한다. 시간 초과는 거부하지 않는다.
    """
    from sudoku_engine.solver import Solver, SolverConfig
    from sudoku_engine.spec import load_spec

    solver = Solver(load_spec({**spec, "givens": givens}), SolverConfig(time_limit=time_limit))
    n = len(solver.solve_all(limit=2))
    if n == 0 and solver.stats.timed_out:
        return False, "판정 불가: 제한 시간 안에 해 존재 여부를 확정하지 못했습니다."
    if n == 0:
        return True, "명세는 문법적으로 맞지만 해가 존재하지 않습니다"
    return False, "해가 둘 이상" if n > 1 else "유일해"


def _check(
    spec: dict, strict: bool, givens: str | None, check_solvable: bool, solve_time_limit: float
) -> tuple[str, str, str]:
    """(거부 단계, 사유, 풀이가능성 메시지). 통과하면 단계가 ""."""
    ok, msg = safe_validate(spec)
    if not ok:
        return "engine", msg, ""
    if strict:
        problems = plausibility_problems(spec)
        if problems:
            return "plausibility", " / ".join(problems), ""
    if check_solvable and givens:
        try:
            reject, reason = _solvability(spec, givens, solve_time_limit)
        except Exception as exc:  # noqa: BLE001 — givens와 명세가 충돌하는 경우 등
            return "engine", f"단서와 함께 불러오지 못했습니다: {exc}", ""
        if reject:
            return "solvable", reason + ". 규칙을 잘못 읽었거나 빠뜨린 제약이 없는지 확인하세요", reason
        return "", "", reason
    return "", "", ""


def parse_rules(
    rule_text: str,
    client: LLMClient,
    *,
    max_attempts: int = 3,
    givens: str | None = None,
    strict: bool = True,
    check_solvable: bool = False,
    solve_time_limit: float = 10.0,
) -> ParseResult:
    if not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_attempts는 1 이상의 정수여야 합니다.")
    _validate_givens(givens)

    history: list[tuple[str, str]] = []
    attempts: list[Attempt] = []
    last_spec: dict | None = None
    last_unsupported: list[str] = []

    for _ in range(max_attempts):
        t0 = time.perf_counter()
        raw, solv = "", ""
        try:
            raw = client.complete(SYSTEM_PROMPT, build_messages(rule_text, history))
        except LLMAPIError as exc:
            stage, feedback = "api", str(exc)
            meta = getattr(client, "last_meta", {}) or {}
            attempts.append(Attempt(exc.detail or "", stage, feedback, time.perf_counter() - t0, exc.kind,
                                    meta.get("input_tokens"), meta.get("output_tokens"), meta.get("stop_reason")))
            if exc.kind in ("length", "empty"):
                # 잘리거나 빈 응답은 짧게 다시 쓰라고 되먹여 재시도
                history.append((exc.detail or "", feedback + " JSON 객체 하나만 짧게 출력하세요."))
                continue
            return ParseResult("api_error", last_spec, last_unsupported, attempts,
                               error={"kind": exc.kind, "message": str(exc), "detail": exc.detail})
        except Exception as exc:  # noqa: BLE001 — 분류되지 않은 클라이언트 예외도 프로그램을 멈추지 않게
            attempts.append(Attempt("", "api", f"{type(exc).__name__}: {exc}", time.perf_counter() - t0, "unknown"))
            return ParseResult("api_error", last_spec, last_unsupported, attempts,
                               error={"kind": "unknown", "message": f"{type(exc).__name__}: {exc}"})

        try:
            spec, unsupported = split_output(extract_json(raw))
        except OutputFormatError as exc:
            stage, feedback = "format", str(exc)
        else:
            last_spec, last_unsupported = spec, unsupported
            stage, feedback, solv = _check(spec, strict, givens, check_solvable, solve_time_limit)

        meta = getattr(client, "last_meta", {}) or {}
        attempts.append(Attempt(raw, stage, feedback, time.perf_counter() - t0, "",
                                meta.get("input_tokens"), meta.get("output_tokens"), meta.get("stop_reason")))
        if not stage:
            final = {**spec, "givens": givens} if givens else spec
            status = "unsupported" if unsupported else "ok"
            return ParseResult(status, final, unsupported, attempts, solv)
        history.append((raw, feedback))

    if all(a.stage == "api" for a in attempts):
        # 한 번도 제대로 된 응답을 못 받았다면(빈 응답·잘림 반복) 파싱 실패가 아니라 API 오류
        last = attempts[-1]
        return ParseResult("api_error", None, [], attempts,
                           error={"kind": last.error_kind, "message": last.feedback})
    return ParseResult("failed", last_spec, last_unsupported, attempts)
