"""llm_parser — 자연어 변형 스도쿠 규칙을 spec.py JSON 명세로 바꾸는 ③ 파트."""

import os
import sys

# 저장소 구조(engine/ 와 parser/ 가 형제 폴더)에서 sudoku_engine을 찾을 수 있게 한다.
try:
    import sudoku_engine  # noqa: F401
except ImportError:  # pragma: no cover - 경로 설정 분기
    _engine_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "engine"))
    sys.path.insert(0, _engine_dir)

from .checks import plausibility_problems, safe_validate  # noqa: E402
from .clients import (  # noqa: E402
    AnthropicClient, GeminiClient, LLMAPIError, LLMClient, OpenAIClient, ScriptedClient,
)
from .parser import Attempt, ParseResult, parse_rules  # noqa: E402

__all__ = [
    "parse_rules", "ParseResult", "Attempt",
    "safe_validate", "plausibility_problems",
    "LLMClient", "LLMAPIError", "AnthropicClient", "OpenAIClient", "GeminiClient", "ScriptedClient",
]
