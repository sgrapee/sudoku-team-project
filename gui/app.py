"""변형 스도쿠 발표 시연용 데스크톱 GUI.

실행:
    python run_gui.py
    python gui/app.py

외부 GUI 패키지 없이 Python 기본 tkinter만 사용한다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import messagebox, ttk


ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = ROOT / "engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from sudoku_engine import Solver, SolverConfig, count_solutions, solve  # noqa: E402
from sudoku_engine.spec import SpecError, load_spec  # noqa: E402
from sudoku_engine.techniques import next_hint, rate_difficulty  # noqa: E402


COLORS = {
    "bg": "#F4F7FB",
    "panel": "#FFFFFF",
    "ink": "#172033",
    "muted": "#6B7280",
    "line": "#CBD5E1",
    "strong": "#334155",
    "primary": "#5B5BD6",
    "primary_dark": "#4747B8",
    "selected": "#DDE7FF",
    "peer": "#F0F4FF",
    "given": "#172033",
    "user": "#2563EB",
    "trying": "#F97316",
    "solved": "#059669",
    "danger": "#DC2626",
    "success_bg": "#ECFDF5",
    "warning": "#F59E0B",
    "thermo": "#A7D8F0",
    "arrow": "#9B8AFB",
    "killer": "#E879A9",
    "diagonal": "#C4B5FD",
    "parity": "#D1D5DB",
    "sandwich": "#F59E0B",
}


TYPE_LABELS = {
    "diagonal": "대각선",
    "killer": "킬러",
    "thermo": "온도계",
    "arrow": "화살표",
    "sandwich": "샌드위치",
    "even": "짝수",
    "odd": "홀수",
    "parity": "짝·홀",
    "lessthan": "부등호",
    "greaterthan": "부등호",
    "alldiff": "서로 다름",
}


def parse_cell(raw: Any) -> tuple[int, int] | None:
    """r1c1 또는 [0, 0] 표기를 0-index 셀로 바꾼다."""
    if isinstance(raw, str):
        match = re.fullmatch(r"\s*[rR](\d+)\s*[cC](\d+)\s*", raw)
        if match:
            return int(match.group(1)) - 1, int(match.group(2)) - 1
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            return int(raw[0]), int(raw[1])
        except (TypeError, ValueError):
            return None
    return None


def load_examples() -> list[tuple[Path, dict[str, Any]]]:
    examples: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((ROOT / "examples").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            load_spec(data)
        except (OSError, json.JSONDecodeError, SpecError):
            continue
        examples.append((path, data))
    return examples


def givens_to_values(raw: Any) -> dict[tuple[int, int], int]:
    values: dict[tuple[int, int], int] = {}
    if isinstance(raw, str):
        chars = [ch for ch in raw if ch in ".0" or ch.isdigit()]
        for idx, ch in enumerate(chars[:81]):
            if ch not in ".0":
                values[(idx // 9, idx % 9)] = int(ch)
    elif isinstance(raw, dict):
        for key, value in raw.items():
            cell = parse_cell(key)
            if cell and value:
                values[cell] = int(value)
    return values


class SudokuDemoApp(tk.Tk):
    CELL = 46
    MARGIN = 32
    BOARD = CELL * 9
    CANVAS = BOARD + MARGIN * 2

    def __init__(self) -> None:
        super().__init__()
        self.title("Sudoku AI Studio · 변형 스도쿠 시연")
        self.geometry("1120x720")
        self.minsize(1040, 680)
        self.configure(bg=COLORS["bg"])

        self.examples = load_examples()
        self.example_lookup: dict[str, dict[str, Any]] = {}
        self.current_spec: dict[str, Any] = {"givens": "." * 81, "constraints": []}
        self.original_values: dict[tuple[int, int], int] = {}
        self.values: dict[tuple[int, int], int] = {}
        self.value_source: dict[tuple[int, int], str] = {}
        self.selected: tuple[int, int] | None = None
        self.hint_cells: set[tuple[int, int]] = set()
        self.trace_events: list[Any] = []
        self.trace_index = 0
        self.trace_total = 0
        self.solve_result: Any = None
        self.animation_job: str | None = None
        self.animating = False
        self.paused = False
        self.locked_values: dict[tuple[int, int], int] = {}
        self.locked_sources: dict[tuple[int, int], str] = {}
        self.speed_var = tk.StringVar(value="보통")

        self.title_var = tk.StringVar(value="퍼즐을 선택하세요")
        self.subtitle_var = tk.StringVar(value="예제를 불러오거나 빈 보드에서 시작할 수 있습니다.")
        self.difficulty_var = tk.StringVar(value="분석 전")
        self.unique_var = tk.StringVar(value="검증 전")
        self.constraint_var = tk.StringVar(value="클래식")
        self.stats_var = tk.StringVar(value="풀이 후 탐색 통계가 표시됩니다.")
        self.status_var = tk.StringVar(value="준비 완료 · 보드를 클릭하고 숫자를 입력하세요.")

        self._configure_styles()
        self._build_header()
        self._build_content()
        self._bind_keys()

        if self.examples:
            display = next(iter(self.example_lookup))
            self.example_box.set(display)
            self.load_selected_example()
        else:
            self.new_blank()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Demo.TCombobox",
            fieldbackground="#F8FAFC",
            background="#F8FAFC",
            foreground=COLORS["ink"],
            bordercolor=COLORS["line"],
            lightcolor=COLORS["line"],
            darkcolor=COLORS["line"],
            padding=8,
            font=("Malgun Gothic", 10),
        )

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=COLORS["panel"], height=66)
        header.pack(fill="x")
        header.pack_propagate(False)

        brand = tk.Frame(header, bg=COLORS["panel"])
        brand.pack(side="left", padx=28, pady=9)
        logo = tk.Canvas(brand, width=44, height=44, bg=COLORS["panel"], highlightthickness=0)
        logo.pack(side="left", padx=(0, 12))
        logo.create_rectangle(3, 3, 41, 41, fill=COLORS["primary"], outline="", width=0)
        for i in (1, 2):
            logo.create_line(3 + i * 12.6, 7, 3 + i * 12.6, 37, fill="#FFFFFF", width=1)
            logo.create_line(7, 3 + i * 12.6, 37, 3 + i * 12.6, fill="#FFFFFF", width=1)
        logo.create_text(22, 22, text="9", fill="#FFFFFF", font=("Segoe UI", 16, "bold"))

        text = tk.Frame(brand, bg=COLORS["panel"])
        text.pack(side="left")
        tk.Label(
            text, text="Sudoku AI Studio", bg=COLORS["panel"], fg=COLORS["ink"],
            font=("Malgun Gothic", 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            text, text="CSP 탐색 · 인간 추론 · 변형 제약 시각화", bg=COLORS["panel"],
            fg=COLORS["muted"], font=("Malgun Gothic", 9),
        ).pack(anchor="w")

        badge = tk.Label(
            header, text="PRESENTATION MODE", bg="#EEF2FF", fg=COLORS["primary_dark"],
            font=("Segoe UI", 9, "bold"), padx=13, pady=7,
        )
        badge.pack(side="right", padx=28)

    def _build_content(self) -> None:
        shell = tk.Frame(self, bg=COLORS["bg"])
        shell.pack(fill="both", expand=True, padx=24, pady=10)

        left = tk.Frame(shell, bg=COLORS["bg"])
        left.pack(side="left", fill="both", expand=True)

        board_card = tk.Frame(left, bg=COLORS["panel"], highlightbackground="#E5EAF2", highlightthickness=1)
        board_card.pack(anchor="n", padx=(0, 20))
        self.canvas = tk.Canvas(
            board_card, width=self.CANVAS, height=self.CANVAS,
            bg=COLORS["panel"], highlightthickness=0, cursor="hand2",
        )
        self.canvas.pack(padx=14, pady=(14, 8))
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        pad = tk.Frame(board_card, bg=COLORS["panel"])
        pad.pack(pady=(0, 15))
        for value in range(1, 10):
            self._small_button(pad, str(value), lambda v=value: self.enter_value(v), 4).pack(
                side="left", padx=3
            )
        self._small_button(pad, "지우기", lambda: self.enter_value(0), 7).pack(side="left", padx=(10, 3))

        legend = tk.Frame(board_card, bg=COLORS["panel"])
        legend.pack(pady=(0, 12))
        for label, color in (
            ("처음 단서", COLORS["given"]),
            ("직접 입력", COLORS["user"]),
            ("탐색 중", COLORS["trying"]),
            ("최종 확정", COLORS["solved"]),
        ):
            item = tk.Frame(legend, bg=COLORS["panel"])
            item.pack(side="left", padx=9)
            tk.Label(item, text="●", bg=COLORS["panel"], fg=color, font=("Segoe UI", 9)).pack(side="left")
            tk.Label(item, text=label, bg=COLORS["panel"], fg=COLORS["muted"], font=("Malgun Gothic", 8)).pack(side="left", padx=(3, 0))

        right = tk.Frame(shell, bg=COLORS["panel"], width=410, highlightbackground="#E5EAF2", highlightthickness=1)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        inner = tk.Frame(right, bg=COLORS["panel"])
        inner.pack(fill="both", expand=True, padx=24, pady=22)

        self._section_label(inner, "DEMO PUZZLE")
        choices: list[str] = []
        for index, (_path, data) in enumerate(self.examples, 1):
            label = f"{index:02d}  {data.get('title', data.get('name', '예제'))}"
            choices.append(label)
            self.example_lookup[label] = data
        self.example_box = ttk.Combobox(
            inner, state="readonly", values=choices, style="Demo.TCombobox",
            font=("Malgun Gothic", 10),
        )
        self.example_box.pack(fill="x", pady=(7, 8))
        self.example_box.bind("<<ComboboxSelected>>", lambda _event: self.load_selected_example())

        top_buttons = tk.Frame(inner, bg=COLORS["panel"])
        top_buttons.pack(fill="x", pady=(0, 18))
        self._button(top_buttons, "예제 불러오기", self.load_selected_example, primary=False).pack(
            side="left", fill="x", expand=True, padx=(0, 5)
        )
        self._button(top_buttons, "빈 보드", self.new_blank, primary=False).pack(
            side="left", fill="x", expand=True, padx=(5, 0)
        )

        tk.Label(
            inner, textvariable=self.title_var, bg=COLORS["panel"], fg=COLORS["ink"],
            font=("Malgun Gothic", 15, "bold"), anchor="w", wraplength=350, justify="left",
        ).pack(fill="x")
        tk.Label(
            inner, textvariable=self.subtitle_var, bg=COLORS["panel"], fg=COLORS["muted"],
            font=("Malgun Gothic", 9), anchor="w", wraplength=350, justify="left",
        ).pack(fill="x", pady=(5, 14))

        meta = tk.Frame(inner, bg="#F8FAFC", highlightbackground="#E8EDF5", highlightthickness=1)
        meta.pack(fill="x", pady=(0, 16))
        self._meta_item(meta, "난이도", self.difficulty_var, 0)
        self._meta_item(meta, "유일해", self.unique_var, 1)
        self._meta_item(meta, "변형 제약", self.constraint_var, 2)

        self._section_label(inner, "RULE SUMMARY")
        self.rule_text = tk.Text(
            inner, height=6, wrap="word", bg="#F8FAFC", fg="#475569",
            relief="flat", font=("Malgun Gothic", 9), padx=10, pady=9,
            selectbackground=COLORS["selected"],
        )
        self.rule_text.pack(fill="x", pady=(7, 16))
        self.rule_text.configure(state="disabled")

        action_row = tk.Frame(inner, bg=COLORS["panel"])
        action_row.pack(fill="x", pady=(0, 9))
        self._button(action_row, "AI 힌트", self.show_hint, primary=False).pack(
            side="left", fill="x", expand=True, padx=(0, 5)
        )
        self._button(action_row, "현재 상태 검증", self.check_board, primary=False).pack(
            side="left", fill="x", expand=True, padx=(5, 0)
        )

        speed_row = tk.Frame(inner, bg=COLORS["panel"])
        speed_row.pack(fill="x", pady=(0, 8))
        tk.Label(
            speed_row, text="탐색 재생 속도", bg=COLORS["panel"], fg=COLORS["muted"],
            font=("Malgun Gothic", 9),
        ).pack(side="left")
        self.speed_box = ttk.Combobox(
            speed_row, textvariable=self.speed_var, state="readonly",
            values=("느리게", "보통", "빠르게"), width=8, style="Demo.TCombobox",
        )
        self.speed_box.pack(side="right")

        play_row = tk.Frame(inner, bg=COLORS["panel"])
        play_row.pack(fill="x", pady=(0, 9))
        self._button(play_row, "과정 보며 풀기", self.solve_board, primary=True).pack(
            side="left", fill="x", expand=True, padx=(0, 5)
        )
        self.pause_button = self._button(play_row, "일시정지", self.toggle_pause, primary=False)
        self.pause_button.pack(side="left", padx=(5, 0))
        self._button(inner, "처음 상태로 되돌리기", self.reset_board, primary=False).pack(fill="x")

        stats = tk.Label(
            inner, textvariable=self.stats_var, bg=COLORS["success_bg"], fg="#047857",
            font=("Malgun Gothic", 9), anchor="w", justify="left", wraplength=340,
            padx=12, pady=10,
        )
        stats.pack(fill="x", pady=(16, 0))

        status = tk.Label(
            self, textvariable=self.status_var, bg="#172033", fg="#E5E7EB",
            font=("Malgun Gothic", 9), anchor="w", padx=24, pady=10,
        )
        status.pack(fill="x", side="bottom")

    def _section_label(self, parent: tk.Widget, text: str) -> None:
        tk.Label(
            parent, text=text, bg=COLORS["panel"], fg="#94A3B8",
            font=("Segoe UI", 9, "bold"), anchor="w",
        ).pack(fill="x")

    def _button(self, parent: tk.Widget, text: str, command: Any, primary: bool) -> tk.Button:
        bg = COLORS["primary"] if primary else "#F8FAFC"
        fg = "#FFFFFF" if primary else COLORS["ink"]
        active = COLORS["primary_dark"] if primary else "#EEF2F7"
        return tk.Button(
            parent, text=text, command=command, bg=bg, fg=fg, activebackground=active,
            activeforeground=fg, relief="flat", bd=0, cursor="hand2",
            font=("Malgun Gothic", 10, "bold"), padx=12, pady=10,
            highlightthickness=1, highlightbackground=COLORS["line"],
        )

    def _small_button(self, parent: tk.Widget, text: str, command: Any, width: int) -> tk.Button:
        return tk.Button(
            parent, text=text, command=command, width=width, bg="#F8FAFC", fg=COLORS["ink"],
            activebackground=COLORS["selected"], relief="flat", cursor="hand2",
            font=("Segoe UI", 10, "bold"), pady=7,
            highlightthickness=1, highlightbackground=COLORS["line"],
        )

    def _meta_item(self, parent: tk.Widget, title: str, variable: tk.StringVar, column: int) -> None:
        box = tk.Frame(parent, bg="#F8FAFC")
        box.grid(row=0, column=column, sticky="nsew", padx=9, pady=10)
        parent.grid_columnconfigure(column, weight=1)
        tk.Label(box, text=title, bg="#F8FAFC", fg="#94A3B8", font=("Malgun Gothic", 8)).pack()
        tk.Label(
            box, textvariable=variable, bg="#F8FAFC", fg=COLORS["ink"],
            font=("Malgun Gothic", 9, "bold"), wraplength=100,
        ).pack(pady=(3, 0))

    def _bind_keys(self) -> None:
        self.bind("<Key>", self._on_key)
        self.bind("<Control-r>", lambda _event: self.reset_board())
        self.bind("<Control-h>", lambda _event: self.show_hint())
        self.bind("<F5>", lambda _event: self.solve_board())

    def load_selected_example(self) -> None:
        self._cancel_animation()
        spec = self.example_lookup.get(self.example_box.get())
        if spec is None:
            return
        self.current_spec = json.loads(json.dumps(spec, ensure_ascii=False))
        self.original_values = givens_to_values(spec.get("givens", ""))
        self.values = dict(self.original_values)
        self.value_source = {cell: "given" for cell in self.original_values}
        self.selected = None
        self.hint_cells.clear()

        self.title_var.set(str(spec.get("title") or spec.get("name") or "변형 스도쿠"))
        self.subtitle_var.set(str(spec.get("note") or "변형 제약을 만족하도록 퍼즐을 풀어보세요."))
        self._set_rule_text(str(spec.get("rules_text") or "클래식 스도쿠 규칙"))
        self._update_constraint_summary()
        self.difficulty_var.set("분석 중…")
        self.unique_var.set("검증 중…")
        self.stats_var.set("풀이 후 탐색 통계가 표시됩니다.")
        self.status_var.set("예제를 불러왔습니다 · 제약 도형을 확인한 뒤 힌트 또는 풀이를 눌러보세요.")
        self.draw_board()
        self.after(60, self._analyze_current)

    def new_blank(self) -> None:
        self._cancel_animation()
        self.current_spec = {
            "name": "blank",
            "title": "빈 클래식 스도쿠",
            "note": "숫자를 직접 입력한 뒤 현재 상태를 검증하거나 풀이할 수 있습니다.",
            "rules_text": "각 행, 열, 3×3 박스에는 1부터 9까지의 숫자가 한 번씩 들어갑니다.",
            "givens": "." * 81,
            "constraints": [],
        }
        self.original_values = {}
        self.values = {}
        self.value_source = {}
        self.selected = (0, 0)
        self.hint_cells.clear()
        self.title_var.set("빈 클래식 스도쿠")
        self.subtitle_var.set("숫자를 입력해 새로운 문제를 구성하세요.")
        self._set_rule_text(self.current_spec["rules_text"])
        self.difficulty_var.set("입력 대기")
        self.unique_var.set("검증 전")
        self.constraint_var.set("클래식")
        self.stats_var.set("단서를 입력한 뒤 ‘현재 상태 검증’을 눌러주세요.")
        self.status_var.set("빈 보드 · 숫자키 1~9 입력, Delete/Backspace 삭제")
        self.draw_board()

    def reset_board(self) -> None:
        self._cancel_animation()
        self.values = dict(self.original_values)
        self.value_source = {cell: "given" for cell in self.original_values}
        self.hint_cells.clear()
        self.stats_var.set("풀이 후 탐색 통계가 표시됩니다.")
        self.status_var.set("퍼즐을 처음 상태로 되돌렸습니다.")
        self.draw_board()

    def _set_rule_text(self, text: str) -> None:
        self.rule_text.configure(state="normal")
        self.rule_text.delete("1.0", "end")
        self.rule_text.insert("1.0", text)
        self.rule_text.configure(state="disabled")

    def _update_constraint_summary(self) -> None:
        kinds = [str(c.get("type", "")).lower() for c in self.current_spec.get("constraints", [])]
        counts = Counter(TYPE_LABELS.get(kind, kind or "기타") for kind in kinds)
        if not counts:
            self.constraint_var.set("클래식")
            return
        compact = ", ".join(f"{name} {count}" if count > 1 else name for name, count in counts.items())
        self.constraint_var.set(compact)

    def _analyze_current(self) -> None:
        try:
            model = load_spec(self.current_spec)
            difficulty = rate_difficulty(model)
            self.difficulty_var.set(difficulty["label"])
            config = SolverConfig(time_limit=4.0)
            solutions = count_solutions(model, limit=2, config=config)
            self.unique_var.set("유일해" if solutions == 1 else ("복수 해" if solutions > 1 else "해 없음"))
        except Exception as exc:  # GUI가 분석 실패로 종료되지 않도록 표시만 한다.
            self.difficulty_var.set("분석 실패")
            self.unique_var.set("확인 필요")
            self.status_var.set(f"분석 중 오류: {exc}")

    def _current_spec_with_values(self) -> dict[str, Any]:
        spec = json.loads(json.dumps(self.current_spec, ensure_ascii=False))
        chars = ["."] * 81
        for (row, col), value in self.values.items():
            chars[row * 9 + col] = str(value)
        spec["givens"] = "".join(chars)
        return spec

    def solve_board(self) -> None:
        if self.animating:
            return
        self.status_var.set("CSP 엔진이 실제 탐색 과정을 기록하고 있습니다…")
        self.update_idletasks()
        try:
            model = load_spec(self._current_spec_with_values())
            trace: list[Any] = []
            solver = Solver(
                model,
                SolverConfig(var_order="mrv_degree", val_order="lcv", propagation="ac3", time_limit=8.0),
                trace=trace,
            )
            result = solver.solve()
        except SpecError as exc:
            self._show_error("입력 오류", str(exc))
            return
        except Exception as exc:
            self._show_error("풀이 오류", str(exc))
            return

        if not result.solved or result.solution is None:
            self.status_var.set("해답을 찾지 못했습니다. 입력한 숫자와 변형 규칙을 확인하세요.")
            messagebox.showwarning("풀이 실패", "현재 입력으로는 해답을 찾지 못했습니다.")
            return

        self.locked_values = dict(self.values)
        self.locked_sources = dict(self.value_source)
        self.solve_result = result
        self.trace_total = len(trace)
        self.trace_events = self._trim_trace(trace, max_events=650)
        self.trace_index = 0
        self.animating = True
        self.paused = False
        self.pause_button.configure(text="일시정지")
        self.stats_var.set(
            f"탐색 과정 재생 중 · 전체 {self.trace_total}단계\n"
            "주황색은 임시 값이며 백트래킹 때 바뀔 수 있습니다."
        )
        self._animate_trace()

    def _trim_trace(self, trace: list[Any], max_events: int) -> list[Any]:
        """발표가 지나치게 길어지지 않도록 긴 추적은 앞·중간·끝을 균등 표본화한다."""
        if len(trace) <= max_events:
            return trace
        head = trace[:120]
        tail = trace[-30:]
        middle = trace[120:-30]
        slots = max_events - len(head) - len(tail)
        step = len(middle) / slots
        sampled = [middle[min(int(i * step), len(middle) - 1)] for i in range(slots)]
        return head + sampled + tail

    def _animation_delay(self) -> int:
        return {"느리게": 260, "보통": 110, "빠르게": 35}.get(self.speed_var.get(), 110)

    def _animate_trace(self) -> None:
        if not self.animating or self.paused:
            return
        if self.trace_index >= len(self.trace_events):
            self._finish_animation()
            return

        event = self.trace_events[self.trace_index]
        self.trace_index += 1
        self.values = dict(self.locked_values)
        self.value_source = dict(self.locked_sources)
        for cell, value in event.assignment.items():
            if cell not in self.locked_values:
                self.values[cell] = value
                self.value_source[cell] = "solved" if event.kind == "solution" else "trying"

        self.hint_cells = {event.cell} if event.cell is not None else set()
        if event.cell is not None:
            self.selected = event.cell
        stage = {
            "start": "초기 제약 전파",
            "try": "후보 시도",
            "propagate": "제약 전파",
            "backtrack": "모순 발견 → 이전 단계로 복귀",
            "solution": "해답 확정",
        }.get(event.kind, event.kind)
        cell_text = ""
        if event.cell is not None:
            cell_text = f" · r{event.cell[0] + 1}c{event.cell[1] + 1}={event.value}"
        shown = self.trace_index
        total = len(self.trace_events)
        self.status_var.set(f"탐색 {shown}/{total} · {stage}{cell_text}")
        self.draw_board()
        self.animation_job = self.after(self._animation_delay(), self._animate_trace)

    def toggle_pause(self) -> None:
        if not self.animating:
            self.status_var.set("현재 재생 중인 탐색 과정이 없습니다.")
            return
        self.paused = not self.paused
        self.pause_button.configure(text="계속" if self.paused else "일시정지")
        if self.paused:
            if self.animation_job is not None:
                self.after_cancel(self.animation_job)
                self.animation_job = None
            self.status_var.set(f"탐색 과정 일시정지 · {self.trace_index}/{len(self.trace_events)}")
        else:
            self._animate_trace()

    def _finish_animation(self) -> None:
        self.animating = False
        self.paused = False
        self.animation_job = None
        self.pause_button.configure(text="일시정지")
        result = self.solve_result
        if result is None or result.solution is None:
            return
        self.values = dict(self.locked_values)
        self.value_source = dict(self.locked_sources)
        for cell, value in result.solution.items():
            if cell not in self.locked_values:
                self.values[cell] = value
                self.value_source[cell] = "solved"
        stats = result.stats.as_dict()
        sampled = "" if self.trace_total == len(self.trace_events) else f" · {len(self.trace_events)}단계 표본 재생"
        self.stats_var.set(
            f"풀이 완료  ·  {stats['elapsed_ms']:.1f} ms{sampled}\n"
            f"탐색 노드 {stats['nodes']}  ·  분기 {stats['branch_nodes']}  ·  백트랙 {stats['backtracks']}"
        )
        self.status_var.set("풀이 완료 · 초록색은 최종 확정값, 파란색은 사용자가 직접 입력한 값입니다.")
        self.hint_cells.clear()
        self.draw_board()

    def _cancel_animation(self) -> None:
        if self.animation_job is not None:
            try:
                self.after_cancel(self.animation_job)
            except tk.TclError:
                pass
        self.animation_job = None
        self.animating = False
        self.paused = False
        if hasattr(self, "pause_button"):
            self.pause_button.configure(text="일시정지")

    def check_board(self) -> None:
        try:
            model = load_spec(self._current_spec_with_values())
        except SpecError as exc:
            self._show_error("검증 결과", str(exc))
            return
        if len(self.values) == 81:
            if model.is_valid(self.values):
                self.status_var.set("정답입니다! 모든 기본 규칙과 변형 제약을 만족합니다.")
                messagebox.showinfo("검증 성공", "정답입니다!\n모든 기본 규칙과 변형 제약을 만족합니다.")
            else:
                self._show_error("검증 실패", "완성된 보드가 일부 제약을 위반합니다.")
            return
        result = solve(model, SolverConfig(time_limit=5.0))
        if result.solved:
            self.status_var.set(f"현재 입력은 유효합니다 · 남은 칸 {81 - len(self.values)}개")
            messagebox.showinfo("검증 성공", "현재까지 입력한 숫자는 유효하며, 완성 가능한 상태입니다.")
        else:
            self._show_error("검증 실패", "현재 입력으로 완성 가능한 해답이 없습니다.")

    def show_hint(self) -> None:
        try:
            base_model = load_spec(self.current_spec)
            current = {
                cell: value for cell, value in self.values.items()
                if cell not in self.original_values
            }
            step = next_hint(base_model, current=current)
        except Exception as exc:
            self._show_error("힌트 오류", str(exc))
            return
        if step is None:
            self.status_var.set("현재 상태에서 논리 힌트를 찾지 못했습니다.")
            messagebox.showinfo("AI 힌트", "적용 가능한 논리 힌트를 찾지 못했습니다.\n입력을 검증해 보세요.")
            return
        self.hint_cells = set()
        if step.cell is not None:
            self.hint_cells.add(step.cell)
            self.selected = step.cell
        self.hint_cells.update(cell for cell, _value in step.eliminated[:8])
        technique = step.technique.replace("_", " ").title()
        self.status_var.set(f"힌트 · {technique}: {step.explanation}")
        self.draw_board()
        messagebox.showinfo(f"AI 힌트 · {technique}", step.explanation)

    def _show_error(self, title: str, message: str) -> None:
        self.status_var.set(f"{title}: {message}")
        messagebox.showerror(title, message)

    def _on_canvas_click(self, event: tk.Event) -> None:
        col = int((event.x - self.MARGIN) // self.CELL)
        row = int((event.y - self.MARGIN) // self.CELL)
        if 0 <= row < 9 and 0 <= col < 9:
            self.selected = (row, col)
            self.hint_cells.clear()
            self.focus_set()
            self.draw_board()

    def _on_key(self, event: tk.Event) -> None:
        if event.char in "123456789":
            self.enter_value(int(event.char))
            return
        if event.keysym in ("BackSpace", "Delete", "0"):
            self.enter_value(0)
            return
        if self.selected is None:
            return
        row, col = self.selected
        moves = {"Up": (-1, 0), "Down": (1, 0), "Left": (0, -1), "Right": (0, 1)}
        if event.keysym in moves:
            dr, dc = moves[event.keysym]
            self.selected = ((row + dr) % 9, (col + dc) % 9)
            self.draw_board()

    def enter_value(self, value: int) -> None:
        if self.animating:
            self.status_var.set("탐색 과정 재생을 일시정지하거나 초기화한 뒤 숫자를 입력하세요.")
            return
        if self.selected is None:
            self.status_var.set("먼저 숫자를 입력할 칸을 선택하세요.")
            return
        if self.selected in self.original_values:
            self.status_var.set("처음 주어진 단서는 수정할 수 없습니다.")
            return
        if value == 0:
            self.values.pop(self.selected, None)
            self.value_source.pop(self.selected, None)
        else:
            self.values[self.selected] = value
            self.value_source[self.selected] = "user"
        self.hint_cells.clear()
        row, col = self.selected
        self.selected = (row, (col + 1) % 9)
        self.draw_board()

    def _center(self, cell: tuple[int, int]) -> tuple[float, float]:
        row, col = cell
        return (
            self.MARGIN + col * self.CELL + self.CELL / 2,
            self.MARGIN + row * self.CELL + self.CELL / 2,
        )

    def draw_board(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        canvas.create_rectangle(0, 0, self.CANVAS, self.CANVAS, fill=COLORS["panel"], outline="")

        for row in range(9):
            for col in range(9):
                x1 = self.MARGIN + col * self.CELL
                y1 = self.MARGIN + row * self.CELL
                fill = "#FFFFFF"
                if self.selected:
                    sr, sc = self.selected
                    if row == sr or col == sc or (row // 3 == sr // 3 and col // 3 == sc // 3):
                        fill = COLORS["peer"]
                    if (row, col) == self.selected:
                        fill = COLORS["selected"]
                if (row, col) in self.hint_cells:
                    fill = "#FFF4D6"
                canvas.create_rectangle(x1, y1, x1 + self.CELL, y1 + self.CELL, fill=fill, outline="")

        self._draw_constraints()

        for i in range(10):
            width = 3 if i % 3 == 0 else 1
            color = COLORS["strong"] if width == 3 else COLORS["line"]
            x = self.MARGIN + i * self.CELL
            y = self.MARGIN + i * self.CELL
            canvas.create_line(x, self.MARGIN, x, self.MARGIN + self.BOARD, fill=color, width=width)
            canvas.create_line(self.MARGIN, y, self.MARGIN + self.BOARD, y, fill=color, width=width)

        for cell, value in self.values.items():
            x, y = self._center(cell)
            source = self.value_source.get(cell, "user")
            color = {
                "given": COLORS["given"],
                "user": COLORS["user"],
                "trying": COLORS["trying"],
                "solved": COLORS["solved"],
            }.get(source, COLORS["user"])
            weight = "bold" if source == "given" else "normal"
            canvas.create_text(x, y + 1, text=str(value), fill=color, font=("Segoe UI", 21, weight))

        if self.selected:
            row, col = self.selected
            x1 = self.MARGIN + col * self.CELL + 2
            y1 = self.MARGIN + row * self.CELL + 2
            canvas.create_rectangle(
                x1, y1, x1 + self.CELL - 4, y1 + self.CELL - 4,
                outline=COLORS["primary"], width=3,
            )

        canvas.create_text(self.MARGIN - 16, self.MARGIN - 19, text="R/C", fill="#94A3B8", font=("Segoe UI", 8, "bold"))
        for i in range(9):
            canvas.create_text(self.MARGIN + i * self.CELL + self.CELL / 2, self.MARGIN - 18, text=str(i + 1), fill="#94A3B8", font=("Segoe UI", 8))
            canvas.create_text(self.MARGIN - 17, self.MARGIN + i * self.CELL + self.CELL / 2, text=str(i + 1), fill="#94A3B8", font=("Segoe UI", 8))

    def _draw_constraints(self) -> None:
        constraints = self.current_spec.get("constraints", [])
        for con in constraints:
            if str(con.get("type", "")).lower() == "diagonal":
                start = self._center((0, 0))
                end = self._center((8, 8))
                self.canvas.create_line(*start, *end, fill=COLORS["diagonal"], width=6)
                start = self._center((0, 8))
                end = self._center((8, 0))
                self.canvas.create_line(*start, *end, fill=COLORS["diagonal"], width=6)

        for con in constraints:
            kind = str(con.get("type", "")).lower()
            if kind == "thermo":
                cells = [parse_cell(x) for x in con.get("path", con.get("cells", []))]
                cells = [x for x in cells if x is not None]
                if len(cells) >= 2:
                    points = [coord for cell in cells for coord in self._center(cell)]
                    self.canvas.create_line(*points, fill=COLORS["thermo"], width=14, capstyle="round", joinstyle="round")
                    x, y = self._center(cells[0])
                    self.canvas.create_oval(x - 16, y - 16, x + 16, y + 16, fill=COLORS["thermo"], outline="")
            elif kind == "arrow":
                circle = parse_cell(con.get("circle", con.get("head")))
                path = [parse_cell(x) for x in con.get("path", con.get("cells", []))]
                path = [x for x in path if x is not None]
                if circle and path:
                    cells = [circle] + path
                    points = [coord for cell in cells for coord in self._center(cell)]
                    self.canvas.create_line(*points, fill=COLORS["arrow"], width=5, capstyle="round", joinstyle="round")
                    x, y = self._center(circle)
                    self.canvas.create_oval(x - 17, y - 17, x + 17, y + 17, fill="#F4F0FF", outline=COLORS["arrow"], width=4)
            elif kind == "killer":
                cells = [parse_cell(x) for x in con.get("cells", con.get("cage", []))]
                cells = [x for x in cells if x is not None]
                for row, col in cells:
                    x1 = self.MARGIN + col * self.CELL + 5
                    y1 = self.MARGIN + row * self.CELL + 5
                    self.canvas.create_rectangle(
                        x1, y1, x1 + self.CELL - 10, y1 + self.CELL - 10,
                        outline=COLORS["killer"], width=2, dash=(4, 3),
                    )
                if cells:
                    row, col = min(cells)
                    x = self.MARGIN + col * self.CELL + 10
                    y = self.MARGIN + row * self.CELL + 10
                    self.canvas.create_text(x, y, text=str(con.get("sum", "")), fill="#BE185D", font=("Segoe UI", 8, "bold"))
            elif kind in ("even", "odd", "parity"):
                even = kind != "odd" and bool(con.get("even", True))
                for raw in con.get("cells", []):
                    cell = parse_cell(raw)
                    if not cell:
                        continue
                    x, y = self._center(cell)
                    if even:
                        self.canvas.create_rectangle(x - 12, y - 12, x + 12, y + 12, fill="#EEF0F3", outline="#9CA3AF")
                    else:
                        self.canvas.create_oval(x - 12, y - 12, x + 12, y + 12, fill="#EEF0F3", outline="#9CA3AF")
            elif kind in ("lessthan", "greaterthan"):
                a = parse_cell(con.get("smaller", con.get("left", con.get("a"))))
                b = parse_cell(con.get("larger", con.get("right", con.get("b"))))
                if kind == "greaterthan":
                    a, b = b, a
                if a and b:
                    ax, ay = self._center(a)
                    bx, by = self._center(b)
                    if a[0] == b[0]:
                        symbol = "<" if a[1] < b[1] else ">"
                    else:
                        symbol = "∨" if a[0] < b[0] else "∧"
                    self.canvas.create_text((ax + bx) / 2, (ay + by) / 2, text=symbol, fill="#E11D48", font=("Segoe UI Symbol", 14, "bold"))
            elif kind == "sandwich":
                line = str(con.get("line", con.get("orientation", "row"))).lower()
                try:
                    index = int(con.get("index", con.get("line_index", 0)))
                except (TypeError, ValueError):
                    continue
                label = f"Σ{con.get('sum', '')}"
                if line.startswith("row"):
                    x = self.MARGIN + self.BOARD + 22
                    y = self.MARGIN + index * self.CELL + self.CELL / 2
                else:
                    x = self.MARGIN + index * self.CELL + self.CELL / 2
                    y = self.MARGIN + self.BOARD + 20
                self.canvas.create_text(x, y, text=label, fill="#B45309", font=("Segoe UI", 8, "bold"))
            elif kind == "alldiff":
                cells = [parse_cell(x) for x in con.get("cells", [])]
                cells = [x for x in cells if x is not None]
                if len(cells) > 1:
                    points = [coord for cell in cells for coord in self._center(cell)]
                    self.canvas.create_line(*points, fill="#C084FC", width=3, dash=(6, 4))


def smoke_test() -> int:
    examples = load_examples()
    if not examples:
        print("GUI smoke test 실패: examples/*.json을 찾지 못했습니다.")
        return 1
    solved = 0
    for _path, spec in examples:
        model = load_spec(spec)
        if solve(model, SolverConfig(time_limit=5.0)).solved:
            solved += 1
    print(f"GUI smoke test OK: 예제 {len(examples)}개 로드, {solved}개 풀이 성공")
    return 0 if solved == len(examples) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="변형 스도쿠 발표 시연 GUI")
    parser.add_argument("--smoke-test", action="store_true", help="창을 띄우지 않고 예제와 엔진 연결을 확인")
    args = parser.parse_args()
    if args.smoke_test:
        return smoke_test()
    app = SudokuDemoApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

