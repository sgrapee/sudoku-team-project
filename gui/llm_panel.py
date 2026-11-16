"""GUI의 LLM 연동 부분 (③ AI 연동) — 숭실대 FactChat API Gateway로 자연어 퍼즐을 명세로 바꾼다.

app.py는 이 모듈의 함수·창만 불러 쓴다. 파싱 로직은 parser/llm_parser를 그대로 사용하므로
GUI에서 파싱한 결과는 평가(solver_eval)와 같은 프롬프트·검증·재시도를 거친다.

- API 키: 입력칸(화면에는 *****) → 없으면 환경변수 FACTCHAT_API_KEY. 키는 메모리에만 두고 파일·로그에 남기지 않는다.
- 모든 모델(GPT·Claude·Gemini 등)은 FactChat을 통해 호출한다. 기본 모델은 평가에 쓴 gemini-3.5-flash.
- LLM 호출은 백그라운드 스레드에서 하고, 결과는 큐로 받아 화면을 멈추지 않는다.
"""

from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parents[1]
for _sub in ("engine", "parser"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from llm_parser.canonical import canonical_items, safe_canonical  # noqa: E402
from llm_parser.checks import extract_givens  # noqa: E402
from llm_parser.clients import FactChatClient, LLMAPIError, vendor_label  # noqa: E402
from llm_parser.parser import parse_rules  # noqa: E402

DEFAULT_MODEL = "gemini-3.5-flash"
MAX_ATTEMPTS = 3
GRID_LINE = re.compile(r"^[\s|]*(?:[0-9.][\s|]*){9}$|^[\s|]*(?:[0-9.][\s|]*){81}$")


# ---------------------------------------------------------------- 화면과 무관한 도우미 (테스트 가능)

def env_key() -> str:
    return (os.environ.get("FACTCHAT_API_KEY") or "").strip()


def model_label(model_id: str, vendor: str | None = None) -> str:
    return f"{model_id} ({vendor or vendor_label(None, model_id)})"


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def remaining_credits(data: Any) -> float | None:
    """GET credits/ 응답에서 남은 크레딧. 문서 형식: total.remaining (없으면 monthly_allocated.remaining)."""
    if not isinstance(data, dict):
        return None
    for section in ("total", "monthly_allocated"):
        part = data.get(section)
        if isinstance(part, dict) and _num(part.get("remaining")) is not None:
            return _num(part["remaining"])
    for key in ("remaining", "balance", "credit", "credits"):
        if _num(data.get(key)) is not None:
            return _num(data[key])
    return None


def credits_text(data: Any, short: bool = False) -> str:
    rem = remaining_credits(data)
    if rem is None:
        return "크레딧 정보 확인 불가"
    if short:
        return f"남은 크레딧 {rem:,.1f}"
    monthly = data.get("monthly_allocated") if isinstance(data, dict) else None
    used = _num(monthly.get("used")) if isinstance(monthly, dict) else None
    return f"남은 크레딧 {rem:,.1f}" + (f" (이번 달 사용 {used:,.1f})" if used is not None else "")


_KIND_MESSAGES = {
    "auth": "API 키가 올바르지 않습니다(401). 키를 다시 붙여넣어 주세요.",
    "billing": "크레딧이 부족합니다(402). 학교 FactChat 사이트에서 잔액을 확인하세요.",
    "permission": "이 모델은 게이트웨이에서 쓸 수 없습니다(403). 다른 모델을 고르세요.",
    "model": "모델을 찾을 수 없습니다(404). 연결 확인으로 모델 목록을 다시 불러오세요.",
    "rate_limit": "요청이 너무 많습니다(429). 잠시 뒤 다시 시도하세요.",
    "network": "네트워크에 연결할 수 없습니다. 인터넷 연결을 확인하세요.",
    "server": "FactChat 서버 오류입니다. 잠시 뒤 다시 시도하세요.",
    "refusal": "모델이 응답을 거부했습니다.",
}
_STATUS_KIND = {401: "auth", 402: "billing", 403: "permission", 404: "model", 429: "rate_limit"}


def friendly_error(exc: Exception | dict) -> str:
    """오류를 한국어 한 줄로. 키 값은 메시지에 넣지 않는다."""
    if isinstance(exc, dict):  # ParseResult.error
        kind, detail = exc.get("kind", "unknown"), exc.get("message", "")
    elif isinstance(exc, LLMAPIError):
        kind, detail = exc.kind, exc.detail
    else:
        code = getattr(exc, "status_code", None)
        kind = _STATUS_KIND.get(code, "server" if code and code >= 500 else "unknown")
        detail = str(exc)
    if kind == "config":
        return " ".join(str(detail).split())
    return _KIND_MESSAGES.get(kind, f"LLM 호출 실패: {' '.join(str(detail).split())[:160]}")


def rules_only(text: str) -> str:
    """규칙 요약 칸에 보여줄 글: 단서 격자 줄은 뺀다."""
    lines = [ln for ln in text.splitlines() if not GRID_LINE.match(ln)]
    return "\n".join(lines).strip()


def load_demo_texts() -> list[dict]:
    """시연용 자연어 퍼즐 50개: ④-A nl_prompts 40개 + examples 10개(규칙 + 단서 격자).

    평가(solver_eval)에 쓴 것과 같은 문장이다. gold는 '정답 명세와 일치' 표시에만 쓴다.
    """
    items: list[dict] = []
    nl = ROOT / "puzzles" / "nl_prompts.jsonl"
    if nl.exists():
        with open(nl, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    variant = "+".join(r.get("variant", [])) or "classic"
                    items.append({"label": f"{r['id']} · {variant} · {r.get('tier', '')}", "id": r["id"],
                                  "text": r["text"], "gold": r["spec"]["constraints"]})
    for path in sorted((ROOT / "examples").glob("*.json")):
        try:
            ex = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not ex.get("rules_text") or not ex.get("givens"):
            continue
        rows = "\n".join(ex["givens"][i * 9:(i + 1) * 9] for i in range(9))
        text = f"{ex['rules_text']}\n처음 주어진 숫자 (빈칸은 .):\n{rows}"
        items.append({"label": f"{ex['name']} · {ex.get('title', '')}", "id": ex["name"],
                      "text": text, "gold": ex.get("constraints", [])})
    return items


def matches_gold(spec: dict | None, gold: list) -> bool:
    return safe_canonical(spec) == canonical_items({"constraints": gold})


class _CountingClient:
    """LLM 호출 횟수를 진행 표시로 알려 주는 감싸개(파서는 그대로)."""

    def __init__(self, inner, on_call: Callable[[int], None]) -> None:
        self.inner, self.on_call, self.n = inner, on_call, 0
        self.name = inner.name

    @property
    def last_meta(self) -> dict:
        return getattr(self.inner, "last_meta", {}) or {}

    def complete(self, system: str, messages: list[dict]) -> str:
        self.n += 1
        self.on_call(self.n)
        return self.inner.complete(system, messages)


def make_client(key: str, model: str | None = None, *, transport=None) -> FactChatClient:
    client = FactChatClient(model or None, api_key=key or None, transport=transport,
                            require_model=bool(model))
    client.max_retries = 1  # GUI에서는 긴 백오프(최대 60초)로 화면이 오래 기다리지 않게 한 번만 재시도
    return client


def connect_job(key: str, transport=None) -> dict:
    """연결 확인: 키 검증(크레딧 조회, 무료) + 모델 목록."""
    client = make_client(key, transport=transport)
    credits = client.credits()
    return {"credits": credits, "models": client.model_infos()}


def parse_job(text: str, key: str, model: str, progress: Callable[[int], None], transport=None) -> dict:
    """자연어 → 명세. 평가와 같은 parse_rules(검증·재시도·풀이 가능성 검사)를 쓴다."""
    client = make_client(key, model, transport=transport)
    before = None
    try:
        before = remaining_credits(client.credits())
    except Exception:  # noqa: BLE001 — 크레딧 조회 실패는 파싱을 막지 않는다
        pass
    givens = extract_givens(text)
    counting = _CountingClient(client, progress)
    t0 = time.perf_counter()
    result = parse_rules(text, counting, max_attempts=MAX_ATTEMPTS, givens=givens, check_solvable=bool(givens))
    elapsed = time.perf_counter() - t0
    after = None
    try:
        after = client.credits()
    except Exception:  # noqa: BLE001
        pass
    rem_after = remaining_credits(after)
    used = (before - rem_after) if before is not None and rem_after is not None else None
    return {"result": result, "givens": givens, "elapsed": elapsed, "credits_after": after, "used": used}


class Background:
    """함수를 스레드에서 돌리고, 결과·진행을 tk 메인 루프에서 받는다(위젯은 메인 스레드에서만 만진다)."""

    def __init__(self, widget: tk.Misc, func: Callable[..., Any], on_done: Callable[[Any], None],
                 on_error: Callable[[Exception], None], on_progress: Callable[[Any], None] | None = None) -> None:
        self.widget, self.on_done, self.on_error, self.on_progress = widget, on_done, on_error, on_progress
        self.q: queue.Queue = queue.Queue()
        self.cancelled = False
        threading.Thread(target=self._run, args=(func,), daemon=True).start()
        widget.after(80, self._poll)

    def _run(self, func: Callable[..., Any]) -> None:
        try:
            self.q.put(("done", func(lambda value: self.q.put(("progress", value)))))
        except Exception as exc:  # noqa: BLE001
            self.q.put(("error", exc))

    def _poll(self) -> None:
        if self.cancelled:
            return
        try:
            if not self.widget.winfo_exists():
                return
        except tk.TclError:
            return
        while True:
            try:
                kind, value = self.q.get_nowait()
            except queue.Empty:
                break
            if kind == "progress" and self.on_progress:
                self.on_progress(value)
            elif kind == "done":
                self.on_done(value)
                return
            elif kind == "error":
                self.on_error(value)
                return
        self.widget.after(80, self._poll)


# ---------------------------------------------------------------- 창

FONT = ("Malgun Gothic", 10)


class NaturalLanguageDialog(tk.Toplevel):
    """자연어 퍼즐 입력 → LLM 파싱. 성공하면 on_success(payload)로 보드에 넘긴다."""

    def __init__(self, master: tk.Misc, *, key: str, model: str, model_text: str,
                 on_success: Callable[[dict], None], colors: dict[str, str]) -> None:
        super().__init__(master)
        self.title("자연어로 퍼즐 불러오기 · LLM 파싱")
        self.geometry("720x600")
        self.minsize(600, 460)
        self.configure(bg=colors["panel"])
        self.transient(master)
        self.key, self.model, self.on_success, self.colors = key, model, on_success, colors
        self.demos = load_demo_texts()
        self.demo_by_label = {d["label"]: d for d in self.demos}
        self.selected_demo: dict | None = None
        self.job: Background | None = None
        self.started = 0.0

        body = tk.Frame(self, bg=colors["panel"])
        body.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(body, text="시연용 문장 (평가에 쓴 50개 중 선택, 고른 뒤 수정해도 됩니다)", bg=colors["panel"],
                 fg=colors["muted"], font=("Malgun Gothic", 9), anchor="w").pack(fill="x")
        self.demo_box = ttk.Combobox(body, state="readonly", values=[d["label"] for d in self.demos],
                                     font=FONT, style="Demo.TCombobox")
        self.demo_box.pack(fill="x", pady=(4, 10))
        self.demo_box.bind("<<ComboboxSelected>>", lambda _e: self._fill_demo())

        # 아래쪽 정보·버튼을 먼저 배치해, 창이 작아져도 버튼이 잘리지 않고 입력칸이 줄어든다.
        buttons = tk.Frame(body, bg=colors["panel"])
        buttons.pack(side="bottom", fill="x")
        self.parse_button = tk.Button(
            buttons, text="LLM으로 파싱", command=self.start, bg=colors["primary"], fg="#FFFFFF",
            activebackground=colors["primary_dark"], activeforeground="#FFFFFF", relief="flat", bd=0,
            cursor="hand2", font=("Malgun Gothic", 10, "bold"), padx=16, pady=9)
        self.parse_button.pack(side="right")
        tk.Button(buttons, text="닫기", command=self.close, bg="#F8FAFC", fg=colors["ink"], relief="flat",
                  cursor="hand2", font=("Malgun Gothic", 10, "bold"), padx=16, pady=9, highlightthickness=1,
                  highlightbackground=colors["line"]).pack(side="right", padx=(0, 8))
        self.progress_var = tk.StringVar(value="")
        self.progress_label = tk.Label(body, textvariable=self.progress_var, bg=colors["panel"],
                                       fg=colors["primary_dark"], font=("Malgun Gothic", 10, "bold"), anchor="w",
                                       justify="left", wraplength=660)
        self.progress_label.pack(side="bottom", fill="x", pady=(6, 8))
        tk.Label(body, text=f"모델: {model_text}  ·  파싱 1회에 약 16 크레딧 (gemini-3.5-flash 기준)",
                 bg=colors["panel"], fg=colors["muted"], font=("Malgun Gothic", 9), anchor="w").pack(
                     side="bottom", fill="x")
        self.info_var = tk.StringVar()
        tk.Label(body, textvariable=self.info_var, bg=colors["panel"], fg=colors["ink"], font=("Malgun Gothic", 9),
                 anchor="w").pack(side="bottom", fill="x", pady=(6, 0))

        tk.Label(body, text="퍼즐 설명 (규칙 문장 + 단서 격자 9줄). 지원 규칙: 대각선·킬러·온도계·화살표·샌드위치·"
                            "서로 다름·짝수/홀수·부등호", bg=colors["panel"], fg=colors["muted"],
                 font=("Malgun Gothic", 9), anchor="w", justify="left", wraplength=660).pack(fill="x")
        frame = tk.Frame(body, bg=colors["panel"])
        frame.pack(fill="both", expand=True, pady=(4, 0))
        self.text = tk.Text(frame, wrap="word", font=("Malgun Gothic", 10), bg="#F8FAFC", relief="flat", height=10,
                            padx=10, pady=8, undo=True, highlightthickness=1, highlightbackground=colors["line"])
        scroll = ttk.Scrollbar(frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.bind("<KeyRelease>", lambda _e: self._update_info())

        self.protocol("WM_DELETE_WINDOW", self.close)

        if self.demos:
            self.demo_box.set(self.demos[0]["label"])
            self._fill_demo()
        self._update_info()
        self.text.focus_set()

    def _fill_demo(self) -> None:
        demo = self.demo_by_label.get(self.demo_box.get())
        if demo is None:
            return
        self.selected_demo = demo
        self.text.delete("1.0", "end")
        self.text.insert("1.0", demo["text"])
        self._update_info()

    def current_text(self) -> str:
        return self.text.get("1.0", "end").strip()

    def _update_info(self) -> None:
        givens = extract_givens(self.current_text())
        if givens:
            self.info_var.set(f"단서 격자: 인식됨 · 단서 {sum(ch != '.' for ch in givens)}개 (코드가 추출, LLM에 맡기지 않음)")
        else:
            self.info_var.set("단서 격자: 찾지 못함 — 9칸씩 9줄(빈칸은 .) 또는 81자 한 줄을 넣어 주세요")

    def start(self) -> None:
        if self.job is not None:
            return
        text = self.current_text()
        if not text:
            messagebox.showwarning("입력 필요", "퍼즐 설명을 입력하세요.", parent=self)
            return
        if extract_givens(text) is None and not messagebox.askyesno(
                "단서 격자 없음", "단서 격자를 찾지 못했습니다.\n빈 보드에 규칙만 적용할까요?", parent=self):
            return
        self.parse_button.configure(state="disabled")
        self.started = time.perf_counter()
        self._set_progress("LLM 파싱 준비 중…", "primary_dark")
        demo = self.selected_demo if self.selected_demo and self.selected_demo["text"].strip() == text else None
        self.job = Background(
            self, lambda progress: parse_job(text, self.key, self.model, progress),
            on_done=lambda payload: self._done(payload, text, demo), on_error=self._error,
            on_progress=lambda n: self._set_progress(
                f"LLM 파싱 중… 호출 {n}회째 (최대 {MAX_ATTEMPTS}회, 거부되면 사유를 알려 주고 다시 요청)", "primary_dark"),
        )

    def _set_progress(self, message: str, color: str) -> None:
        self.progress_var.set(message)
        self.progress_label.configure(fg=self.colors.get(color, color))

    def _done(self, payload: dict, text: str, demo: dict | None) -> None:
        self.job = None
        self.parse_button.configure(state="normal")
        result = payload["result"]
        if result.status in ("ok", "unsupported"):
            payload.update(text=text, demo=demo, model=self.model,
                           gold_match=matches_gold(result.spec, demo["gold"]) if demo else None)
            self.on_success(payload)
            self.destroy()
            return
        if result.status == "api_error":
            msg = friendly_error(result.error or {})
        else:
            last = result.attempts[-1] if result.attempts else None
            reason = " ".join(str(getattr(last, "feedback", "") or "").split())[:200]
            msg = f"{result.n_attempts}번 시도했지만 검증을 통과하지 못했습니다." + (f"\n마지막 사유: {reason}" if reason else "")
        self._set_progress(f"파싱 실패 · {msg}", "danger")
        messagebox.showerror("LLM 파싱 실패", msg, parent=self)

    def _error(self, exc: Exception) -> None:
        self.job = None
        self.parse_button.configure(state="normal")
        msg = friendly_error(exc)
        self._set_progress(f"오류 · {msg}", "danger")
        messagebox.showerror("LLM 오류", msg, parent=self)

    def close(self) -> None:
        if self.job is not None:
            if not messagebox.askyesno("파싱 중", "LLM 파싱이 진행 중입니다. 닫으면 결과를 버립니다.\n닫을까요?", parent=self):
                return
            self.job.cancelled = True
        self.destroy()


class SpecViewer(tk.Toplevel):
    """마지막 LLM 파싱 결과: 시도별 단계, 적용 안 된 규칙, 명세 JSON."""

    def __init__(self, master: tk.Misc, payload: dict, colors: dict[str, str]) -> None:
        super().__init__(master)
        self.title("LLM 파싱 결과 · 명세 보기")
        self.geometry("640x560")
        self.configure(bg=colors["panel"])
        self.transient(master)
        result = payload["result"]
        lines = [f"모델: {model_label(payload['model'])}",
                 f"상태: {result.status}  ·  LLM 호출 {result.n_attempts}회  ·  {payload['elapsed']:.1f}초"]
        if payload.get("used") is not None:
            lines.append(f"이번 파싱 사용 크레딧: 약 {payload['used']:.1f}")
        if payload.get("gold_match") is not None:
            lines.append("정답 명세와 비교: " + ("일치 ✔" if payload["gold_match"] else "다름 ✘"))
        for i, a in enumerate(result.attempts, 1):
            stage = "통과" if not a.stage else f"거부({a.stage})"
            fb = " ".join(str(a.feedback or "").split())[:160]
            lines.append(f"  시도 {i}: {stage}" + (f" — {fb}" if fb and a.stage else ""))
        if result.unsupported:
            lines.append("적용 안 된 규칙(엔진 미지원·정보 부족):")
            lines += [f"  · {u}" for u in result.unsupported]
        cons = (result.spec or {}).get("constraints", [])
        body = "\n".join("  " + json.dumps(c, ensure_ascii=False) for c in cons) or "  (추가 제약 없음 · 일반 스도쿠)"
        text = "\n".join(lines) + f"\n\n명세 constraints {len(cons)}개 (엔진 명세 형식, 단서 격자는 코드가 붙임):\n" + body
        box = tk.Text(self, wrap="word", font=("Consolas", 10), bg="#F8FAFC", relief="flat", padx=12, pady=10)
        box.pack(fill="both", expand=True, padx=14, pady=14)
        box.insert("1.0", text)
        box.configure(state="disabled")
