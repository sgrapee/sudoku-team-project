"""LLM 호출 어댑터. 파서 로직은 complete()만 알면 되므로 제공자를 바꿔도 코드가 그대로다.

API 키는 환경변수로만 받는다. 코드·테스트·README에 넣지 말 것.
  anthropic : ANTHROPIC_API_KEY  (선불 크레딧 필요)
  openai    : OPENAI_API_KEY     (선불 크레딧 필요)
  gemini    : GEMINI_API_KEY     (Google AI Studio 무료 등급 사용 가능, 호출 제한 있음.
                                  새 'AQ.' 키·기존 'AIza' 키 모두 Gemini 기본 REST API로 호출)

오류 처리 (2-3)
  - 일시적 오류(네트워크, 429, 500/502/503/529)는 지수 백오프로 제한 횟수만 재시도
  - 인증·크레딧·모델 이름 오류는 재시도 없이 즉시 LLMAPIError
  - 모델 거부(refusal)·응답 길이 초과·빈 응답도 종류를 구분해 LLMAPIError로 올린다
  - 각 호출의 토큰 사용량·종료 사유·지연 시간은 client.last_meta에 남는다
"""

from __future__ import annotations

import os
import time
from typing import Callable, Protocol

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

_RETRYABLE_STATUS = {429, 500, 502, 503, 529}

# kind → (재시도 가능 여부, 안내 문구)
ERROR_KINDS = {
    "auth": (False, "API 키가 잘못되었습니다. 환경변수에 넣은 키를 확인하세요(예시 문구·공백·일부만 복사)."),
    "billing": (False, "API 키는 맞지만 크레딧(잔액)이나 사용 한도가 부족합니다. 충전·한도를 확인하거나 다른 제공자를 쓰세요."),
    "config": (False, "실행 설정이 빠졌습니다."),
    "permission": (False, "이 키로는 접근 권한이 없습니다(403)."),
    "model": (False, "모델 이름을 찾을 수 없습니다. --list-models로 확인하고 --model로 지정하세요."),
    "refusal": (False, "모델이 응답을 거부했습니다."),
    "length": (True, "응답이 최대 길이에서 잘렸습니다."),
    "empty": (True, "모델이 빈 응답을 돌려줬습니다."),
    "rate_limit": (True, "호출 한도를 초과했습니다(429)."),
    "quota_daily": (False, "오늘 이 모델에 쓸 수 있는 무료 호출 수(일일 한도)를 다 썼습니다. "
                           "한도는 미국 태평양 시간 자정(한국 시간 오후 4~5시경)에 초기화됩니다. "
                           "이어서 측정하려면 --resume <결과 파일>을 쓰세요."),
    "server": (True, "LLM 서버 오류입니다."),
    "network": (True, "네트워크 연결 오류입니다."),
    "unknown": (False, "알 수 없는 API 오류입니다."),
}


class LLMAPIError(RuntimeError):
    """LLM 호출 자체가 실패한 경우. kind는 ERROR_KINDS의 키."""

    def __init__(self, kind: str, detail: str = "") -> None:
        self.kind = kind
        self.retryable, hint = ERROR_KINDS.get(kind, ERROR_KINDS["unknown"])
        self.detail = detail
        super().__init__(f"[{kind}] {hint}" + (f" ({detail[:200]})" if detail else ""))


# 이전 버전 호환: 설정 오류(키·크레딧·모델)
LLMSetupError = LLMAPIError
SETUP_KINDS = {"auth", "billing", "permission", "model", "config"}
# 다음 문장에서도 똑같이 실패할 것이 확실해 측정을 멈춰야 하는 오류
STOP_KINDS = SETUP_KINDS | {"quota_daily", "rate_limit"}


def classify_error(exc: Exception) -> str:
    """SDK 예외 → 오류 종류. SDK마다 예외 클래스가 달라 상태 코드·이름·메시지로 판별한다."""
    if isinstance(exc, LLMAPIError):
        return exc.kind
    code = getattr(exc, "status_code", None)
    low = str(exc).lower()
    cls = type(exc).__name__.lower()
    if code == 401 or "invalid x-api-key" in low or "api key not valid" in low or "incorrect api key" in low:
        return "auth"
    # Gemini 무료 한도 초과 메시지에도 "billing"이라는 단어가 들어가므로 단어만으로 판단하지 않는다
    if code == 402 or "credit balance" in low or "insufficient_quota" in low:
        return "billing"
    if code == 403:
        return "permission"
    if code == 404 or "not_found" in low or ("model" in low and code == 400):
        return "model"
    if code == 429:
        quota = (getattr(exc, "quota_id", "") or "").lower()
        if "perday" in quota or "per_day" in quota or "daily" in quota:
            return "quota_daily"
        return "rate_limit"
    if code in _RETRYABLE_STATUS:
        return "server"
    if code is None and ("connection" in cls or "timeout" in cls or "connect" in low):
        return "network"
    return "unknown"


def call_with_retry(fn: Callable[[], str], max_retries: int = 5, sleep=None) -> str:
    """일시적 오류만 지수 백오프(5, 10, 20, 40, 60초)로 재시도한다."""
    sleep = sleep or time.sleep  # 호출 시점에 찾아야 테스트에서 대기를 생략할 수 있다
    for i in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            kind = classify_error(exc)
            retryable = ERROR_KINDS.get(kind, ERROR_KINDS["unknown"])[0]
            # length/empty는 같은 요청을 다시 보내기보다 파서의 재시도 루프에서 피드백과 함께 다룬다
            if retryable and kind not in ("length", "empty") and i < max_retries:
                hinted = getattr(exc, "retry_delay", None)
                wait = min(120, max(1, round(hinted + 1))) if hinted else min(60, 5 * 2**i)
                code = getattr(exc, "status_code", "")
                detail = " ".join(str(exc).split())[:160]
                print(f"  [{kind} {code}] {detail}", flush=True)
                print(f"    → {wait}초 기다렸다가 다시 시도합니다 ({i + 1}/{max_retries}). 멈추려면 Ctrl+C", flush=True)
                sleep(wait)
                continue
            if isinstance(exc, LLMAPIError):
                raise
            raise LLMAPIError(kind, str(exc)) from exc
    raise RuntimeError("unreachable")  # pragma: no cover


class LLMClient(Protocol):
    name: str
    last_meta: dict

    def complete(self, system: str, messages: list[dict]) -> str:
        """시스템 프롬프트와 대화 목록을 받아 assistant 응답 텍스트를 돌려준다."""
        ...


def _meta(t0: float, input_tokens=None, output_tokens=None, stop_reason=None) -> dict:
    return {
        "latency": round(time.perf_counter() - t0, 3),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "stop_reason": stop_reason,
    }


class AnthropicClient:
    """Anthropic Messages API.

    현재 SDK(2.x)의 messages.create에는 temperature 인자가 없어 실행마다 결과가 조금
    달라질 수 있다. 평가는 --repeat 2~3으로 반복해 평균과 편차를 보고할 것.
    """

    def __init__(self, model: str | None = None, max_tokens: int = 1024, http_client=None) -> None:
        import anthropic  # pip install anthropic

        self.model = model or os.environ.get("SUDOKU_LLM_MODEL", "claude-haiku-5-5")
        self.max_tokens = max_tokens
        self.name = f"anthropic:{self.model}"
        self.last_meta: dict = {}
        kwargs = {"http_client": http_client} if http_client is not None else {}
        self._client = anthropic.Anthropic(**kwargs)

    def complete(self, system: str, messages: list[dict]) -> str:
        def call() -> str:
            t0 = time.perf_counter()
            resp = self._client.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=system, messages=messages,
            )
            usage = getattr(resp, "usage", None)
            self.last_meta = _meta(t0, getattr(usage, "input_tokens", None),
                                   getattr(usage, "output_tokens", None), resp.stop_reason)
            text = "".join(b.text for b in resp.content if b.type == "text")
            if resp.stop_reason == "refusal":
                raise LLMAPIError("refusal", text)
            if resp.stop_reason == "max_tokens":
                raise LLMAPIError("length", text[-200:])
            if not text.strip():
                raise LLMAPIError("empty")
            return text

        return call_with_retry(call, getattr(self, "max_retries", 5))


class OpenAIClient:
    """OpenAI Chat Completions 형식. base_url을 바꾸면 Gemini 등 호환 서버에도 쓴다."""

    def __init__(
        self,
        model: str | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        json_mode: bool = True,
        provider: str = "openai",
        http_client=None,
        temperature: float | None = 0,
    ) -> None:
        import openai  # pip install openai

        self.model = model or os.environ.get("SUDOKU_LLM_MODEL", "gpt-4o-mini")
        self.name = f"{provider}:{self.model}"
        self.json_mode = json_mode
        self.temperature = temperature
        self.last_meta: dict = {}
        kwargs: dict = {}
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key
        if http_client is not None:
            kwargs["http_client"] = http_client
        self._client = openai.OpenAI(**kwargs)

    def complete(self, system: str, messages: list[dict]) -> str:
        extra = {"response_format": {"type": "json_object"}} if self.json_mode else {}
        if self.temperature is not None:
            extra["temperature"] = self.temperature

        def call() -> str:
            t0 = time.perf_counter()
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, *messages],
                **extra,
            )
            choice = resp.choices[0]
            usage = getattr(resp, "usage", None)
            self.last_meta = _meta(t0, getattr(usage, "prompt_tokens", None),
                                   getattr(usage, "completion_tokens", None), choice.finish_reason)
            refusal = getattr(choice.message, "refusal", None)
            if refusal or choice.finish_reason == "content_filter":
                raise LLMAPIError("refusal", refusal or "content_filter")
            text = choice.message.content or ""
            if choice.finish_reason == "length":
                raise LLMAPIError("length", text[-200:])
            if not text.strip():
                raise LLMAPIError("empty")
            return text

        return call_with_retry(call, getattr(self, "max_retries", 5))


GEMINI_NATIVE_URL = "https://generativelanguage.googleapis.com/v1beta"
_GEMINI_BLOCK = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"}


class _HTTPStatusError(Exception):
    """urllib 응답의 상태 코드를 classify_error가 읽을 수 있게 담는다."""

    def __init__(self, status_code: int, message: str, quota_id: str = "", retry_delay: float | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.quota_id = quota_id
        self.retry_delay = retry_delay


def _parse_google_error(err: dict) -> tuple[str, float | None]:
    """Google 오류의 details에서 (한도 ID, 재시도 대기 초)를 꺼낸다."""
    quota_id, delay = "", None
    for d in err.get("details", []) or []:
        kind = str(d.get("@type", ""))
        if kind.endswith("QuotaFailure"):
            for v in d.get("violations", []) or []:
                if not quota_id:
                    quota_id = str(v.get("quotaId") or v.get("quotaMetric") or "")
                    if v.get("quotaValue"):
                        quota_id += f" (한도 {v['quotaValue']}회)"
        elif kind.endswith("RetryInfo"):
            raw = str(d.get("retryDelay", "")).rstrip("s")
            try:
                delay = float(raw)
            except ValueError:
                pass
    return quota_id, delay


def _urllib_transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> tuple[int, bytes]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        raise LLMAPIError("network", str(exc)) from exc


class GeminiNativeClient:
    """Google Gemini 기본 REST API (generateContent). 표준 라이브러리만 사용, 추가 설치 불필요.

    키는 GEMINI_API_KEY 환경변수 → x-goog-api-key 헤더로 보낸다.
    2026년 5월 이후 AI Studio가 발급하는 'AQ.'로 시작하는 새 키(auth key)는 OpenAI 호환 주소에서
    401/400이 난다는 보고가 있어, 기본 주소를 쓴다. 기존 'AIza' 키도 같은 방식으로 동작한다.

    json_mode=True면 responseMimeType=application/json으로 JSON 출력을 요청한다(파서용).
    temperature는 지정하지 않는다(모델 기본값). 반복 측정(--repeat)으로 편차를 보고할 것.
    """

    def __init__(self, model: str | None = None, *, api_key: str | None = None, json_mode: bool = True,
                 max_tokens: int | None = None, timeout: float = 120.0, transport=None) -> None:
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise LLMAPIError("config", "GEMINI_API_KEY 환경변수가 없습니다. Google AI Studio에서 키를 만들어 설정하세요.")
        self._key = key.strip()
        self.model = (model or os.environ.get("SUDOKU_LLM_MODEL", "gemini-3.8-flash")).removeprefix("models/")
        self.name = f"gemini:{self.model}"
        self.json_mode = json_mode
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.last_meta: dict = {}
        self._transport = transport or _urllib_transport

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        import json as _json

        headers = {"x-goog-api-key": self._key, "Content-Type": "application/json"}
        body = _json.dumps(payload).encode("utf-8") if payload is not None else None
        status, raw = self._transport(method, f"{GEMINI_NATIVE_URL}/{path}", headers, body, self.timeout)
        try:
            data = _json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            data = {}
        if status >= 400:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            quota_id, delay = _parse_google_error(err)
            # 한도 정보는 Google의 긴 안내문 뒤에 붙이면 화면에서 잘리므로 앞에 둔다
            prefix = (f"[한도: {quota_id}] " if quota_id else "") + (f"[권장 대기: {delay:g}초] " if delay else "")
            msg = prefix + f"{err.get('status', '')} {err.get('message', raw[:200])}".strip()
            raise _HTTPStatusError(status, msg, quota_id, delay)
        return data

    def complete(self, system: str, messages: list[dict]) -> str:
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                    for m in messages]
        payload: dict = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents}
        cfg: dict = {}
        if self.json_mode:
            cfg["responseMimeType"] = "application/json"
        if self.max_tokens:
            cfg["maxOutputTokens"] = self.max_tokens
        if cfg:
            payload["generationConfig"] = cfg

        def call() -> str:
            t0 = time.perf_counter()
            data = self._request("POST", f"models/{self.model}:generateContent", payload)
            usage = data.get("usageMetadata", {})
            cand = (data.get("candidates") or [{}])[0]
            finish = cand.get("finishReason")
            self.last_meta = _meta(t0, usage.get("promptTokenCount"), usage.get("candidatesTokenCount"), finish)
            block = (data.get("promptFeedback") or {}).get("blockReason")
            if block or finish in _GEMINI_BLOCK:
                raise LLMAPIError("refusal", block or finish)
            # 생각(thought) 파트는 빼고 실제 답변만 이어 붙인다
            text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", [])
                           if not p.get("thought"))
            if finish == "MAX_TOKENS":
                raise LLMAPIError("length", text[-200:])
            if not text.strip():
                raise LLMAPIError("empty", str(finish or ""))
            return text

        return call_with_retry(call, getattr(self, "max_retries", 5))

    def list_models(self) -> list[str]:
        data = self._request("GET", "models?pageSize=1000")
        return sorted(m["name"].removeprefix("models/") for m in data.get("models", [])
                      if "generateContent" in m.get("supportedGenerationMethods", ["generateContent"]))


def GeminiClient(model: str | None = None, http_client=None, *, via: str = "native",
                 json_mode: bool = True, max_tokens: int | None = None, transport=None):
    """Google Gemini. 키: https://aistudio.google.com 에서 무료 발급(신용카드 불필요).

    via="native"(기본): Gemini 기본 REST API — 새 'AQ.' 키와 기존 'AIza' 키 모두 지원
    via="openai": OpenAI 호환 주소 — 'AIza' 키에서만 확인됨, 'AQ.' 키는 실패 보고가 있음
    """
    if via == "openai":
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise LLMAPIError("config", "GEMINI_API_KEY 환경변수가 없습니다. Google AI Studio에서 키를 만들어 설정하세요.")
        return OpenAIClient(
            model or os.environ.get("SUDOKU_LLM_MODEL", "gemini-3.8-flash"),
            base_url=GEMINI_BASE_URL, api_key=key, json_mode=False, provider="gemini-openai",
            http_client=http_client,
        )
    return GeminiNativeClient(model, json_mode=json_mode, max_tokens=max_tokens, transport=transport)


class ScriptedClient:
    """테스트·오프라인 검증용 가짜 LLM.

    responder(rule_text, attempt_index) -> 응답 문자열. 예외를 던지면 API 오류를 흉내 낸다.
    """

    def __init__(self, responder: Callable[[str, int], str], name: str = "scripted") -> None:
        self.responder = responder
        self.name = name
        self.calls = 0
        self.last_meta: dict = {}

    def complete(self, system: str, messages: list[dict]) -> str:
        from .prompt import extract_rule_text

        self.calls += 1
        t0 = time.perf_counter()
        rule_idx = max(i for i, m in enumerate(messages) if m["role"] == "user" and extract_rule_text(m["content"]) is not None)
        rule_text = extract_rule_text(messages[rule_idx]["content"])
        attempt = (len(messages) - 1 - rule_idx) // 2
        try:
            return self.responder(rule_text, attempt)
        finally:
            self.last_meta = _meta(t0)


class Throttled:
    """호출 사이에 최소 간격을 둔다(무료 등급의 분당 호출 제한 대비)."""

    def __init__(self, inner: LLMClient, min_interval: float) -> None:
        self.inner = inner
        self.name = inner.name
        self.min_interval = min_interval
        self._last = 0.0

    @property
    def last_meta(self) -> dict:
        return self.inner.last_meta

    def complete(self, system: str, messages: list[dict]) -> str:
        wait = self._last + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return self.inner.complete(system, messages)
        finally:
            self._last = time.monotonic()


FACTCHAT_BASE_URL = "https://factchat-cloud.mindlogic.ai/v1/gateway"


class FactChatClient:
    """숭실대 FactChat API Gateway (Mindlogic). 표준 라이브러리만 사용, 추가 설치 불필요.

    공식 문서: https://docs.mindlogic.ai/docs/ssu/api-gateway/getting-started/overview
      - OpenAI 호환 채팅: POST {base}/chat/completions/   (문서 표기대로 끝 슬래시 포함)
      - 모델 목록: GET {base}/models/?type=llm, 잔여 크레딧: GET {base}/credits/
      - 인증: Authorization: Bearer <키>  (키는 학교 사이트 > API Gateway에서 발급, 생성한 계정의 크레딧 차감)
      - 제한: 회원당 60초 120회(초과 429), 크레딧 소진 402, 모델 미허용 403, 모델 없음 404

    환경변수: FACTCHAT_API_KEY(필수), FACTCHAT_BASE_URL(선택, 기본은 위 주소), SUDOKU_LLM_MODEL(모델 ID)
    temperature·response_format은 보내지 않는다(GPT-5 계열은 temperature=1만 허용, json_object는 문서에 없음).
    응답의 billing.deducted_credit(실제 차감 크레딧)을 last_meta["credit"]에 남긴다.
    """

    def __init__(self, model: str | None = None, *, max_tokens: int | None = None,
                 timeout: float = 180.0, transport=None, require_model: bool = True) -> None:
        key = (os.environ.get("FACTCHAT_API_KEY") or "").strip()
        if not key:
            raise LLMAPIError("config", "FACTCHAT_API_KEY 환경변수를 설정하세요(학교 사이트 > API Gateway에서 발급).")
        self._key = key
        self.base = (os.environ.get("FACTCHAT_BASE_URL") or FACTCHAT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("SUDOKU_LLM_MODEL") or ""
        if require_model and not self.model:
            raise LLMAPIError("config", "모델 ID를 지정하세요(--model 또는 SUDOKU_LLM_MODEL). "
                                        "--list-models로 목록을 볼 수 있습니다.")
        self.name = f"factchat:{self.model}"
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.last_meta: dict = {}
        self._transport = transport or _urllib_transport

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        import json as _json

        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json",
                   # User-Agent가 비어 있으면 Cloudflare가 403(error code: 1010)으로 막는다
                   "User-Agent": "sudoku-team-project-llm-parser/1.0"}
        body = _json.dumps(payload).encode("utf-8") if payload is not None else None
        status, raw = self._transport(method, f"{self.base}/{path}", headers, body, self.timeout)
        text = raw.decode("utf-8", "replace")
        try:
            data = _json.loads(text or "{}")
        except ValueError:
            data = {}
        if status >= 400:
            err = data.get("error", data) if isinstance(data, dict) else {}
            msg = err.get("message") if isinstance(err, dict) else None
            msg = msg or (data.get("detail") if isinstance(data, dict) else None) or text[:200]
            raise _HTTPStatusError(status, str(msg))
        return data

    def complete(self, system: str, messages: list[dict]) -> str:
        payload: dict = {"model": self.model,
                         "messages": [{"role": "system", "content": system}, *messages]}
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        def call() -> str:
            t0 = time.perf_counter()
            data = self._request("POST", "chat/completions/", payload)
            choice = (data.get("choices") or [{}])[0]
            usage = data.get("usage") or {}
            finish = choice.get("finish_reason")
            self.last_meta = _meta(t0, usage.get("prompt_tokens"), usage.get("completion_tokens"), finish)
            billing = data.get("billing") or {}
            if billing.get("deducted_credit") is not None:
                self.last_meta["credit"] = billing.get("deducted_credit")
            msg = choice.get("message") or {}
            if msg.get("refusal") or finish == "content_filter":
                raise LLMAPIError("refusal", str(msg.get("refusal") or finish))
            content = msg.get("content") or ""
            if isinstance(content, list):  # 일부 모델은 파트 배열로 돌려준다
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            if finish == "length":
                raise LLMAPIError("length", content[-200:])
            if not content.strip():
                raise LLMAPIError("empty", str(finish or ""))
            return content

        return call_with_retry(call, getattr(self, "max_retries", 5))

    def list_models(self) -> list[str]:
        data = self._request("GET", "models/?type=llm")
        items = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
        return sorted(str(m.get("id", m.get("name", ""))) for m in items if isinstance(m, dict))

    def credits(self) -> dict:
        return self._request("GET", "credits/")


def make_client(kind: str, model: str | None = None, max_tokens: int | None = None,
                json_mode: bool = True) -> LLMClient:
    """max_tokens: 응답 길이 상한(Anthropic은 필수). json_mode=False면 풀이 과정 같은 자유 텍스트 허용."""
    if kind == "anthropic":
        return AnthropicClient(model, max_tokens=max_tokens or 1024)
    if kind == "openai":
        return OpenAIClient(model, json_mode=json_mode)
    if kind == "gemini":
        return GeminiClient(model, json_mode=json_mode, max_tokens=max_tokens)
    if kind == "gemini-openai":
        return GeminiClient(model, via="openai")
    if kind == "factchat":
        return FactChatClient(model, max_tokens=max_tokens,
                              require_model=model != "(목록 조회)")
    raise ValueError(f"알 수 없는 클라이언트: {kind} (anthropic / openai / gemini / gemini-openai / factchat)")
