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
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = ROOT / "engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from sudoku_engine import Solver, SolverConfig, count_solutions, solve  # noqa: E402
from sudoku_engine.spec import SpecError, load_spec  # noqa: E402
from sudoku_engine.techniques import next_hint, rate_difficulty  # noqa: E402

# LLM(FactChat) 연동은 별도 모듈. parser 폴더가 없거나 불러오기에 실패해도 GUI의 나머지 기능은 그대로 동작한다.
try:
    from gui import llm_panel  # noqa: E402
except ImportError:
    try:
        import llm_panel  # type: ignore  # noqa: E402  (python gui/app.py로 실행한 경우)
    except ImportError as _llm_exc:
        llm_panel = None
        LLM_IMPORT_ERROR = str(_llm_exc)


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
        # 화면이 허락하면 오른쪽 정보 패널이 잘리지 않도록 세로를 키운다.
        # 창을 화면 맨 위에 붙여, 제목 표시줄(약 31px)과 작업 표시줄(약 48px)에 가리지 않게 한다.
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        height = max(680, min(820, screen_h - 90))
        self.geometry(f"1120x{height}+{max(0, (screen_w - 1120) // 2)}+0")
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
        self.error_cells: set[tuple[int, int]] = set()  # 정답과 다른 사용자 입력(힌트 전 검사)
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

        # LLM(FactChat) 연동 상태. 키는 메모리에만 두고 파일·로그에 남기지 않는다.
        self.llm_key_var = tk.StringVar()
        self.llm_model_var = tk.StringVar()
        self.llm_status_var = tk.StringVar()
        self.llm_model_lookup: dict[str, str] = {}
        self.llm_connected_key: str | None = None
        self.llm_payload: dict[str, Any] | None = None
        self.llm_job: Any = None
        self.llm_status_extra = ""

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
        self._build_llm_bar(header)

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

        # 실행 버튼은 오른쪽 패널 하단에 고정한다. 설명이 길어져도 시연 버튼이
        # 화면 밖으로 밀려나지 않도록 정보 영역과 분리한 구조다.
        action_dock = tk.Frame(right, bg=COLORS["panel"])
        action_dock.pack(side="bottom", fill="x", padx=24, pady=(6, 16))

        # 정보 영역은 화면이 낮으면 스크롤된다. 예전에는 넘치는 부분(난이도 칸 아래, 규칙 요약)이
        # 말없이 잘려서 규칙 요약이 아예 보이지 않았다.
        inner = self._build_scroll_area(right)

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
        self.example_box.pack(fill="x", pady=(6, 6))
        self.example_box.bind("<<ComboboxSelected>>", lambda _event: self.load_selected_example())

        top_buttons = tk.Frame(inner, bg=COLORS["panel"])
        top_buttons.pack(fill="x", pady=(0, 12))
        self._button(top_buttons, "예제 불러오기", self.load_selected_example, primary=False).pack(
            side="left", fill="x", expand=True, padx=(0, 5)
        )
        self._button(top_buttons, "빈 보드", self.new_blank, primary=False).pack(
            side="left", fill="x", expand=True, padx=(5, 0)
        )
        if llm_panel is not None:
            # 세 버튼이 패널 폭(약 360px)에 들어가도록 좌우 여백을 줄인다.
            for button in top_buttons.winfo_children():
                button.configure(padx=4)
            self._button(top_buttons, "자연어 입력", self.open_llm_dialog, primary=False).pack(
                side="left", fill="x", expand=True, padx=(6, 0)
            )
            top_buttons.winfo_children()[-1].configure(padx=4)

        tk.Label(
            inner, textvariable=self.title_var, bg=COLORS["panel"], fg=COLORS["ink"],
            font=("Malgun Gothic", 15, "bold"), anchor="w", wraplength=335, justify="left",
        ).pack(fill="x")
        tk.Label(
            inner, textvariable=self.subtitle_var, bg=COLORS["panel"], fg=COLORS["muted"],
            font=("Malgun Gothic", 9), anchor="w", wraplength=335, justify="left",
        ).pack(fill="x", pady=(4, 10))

        meta = tk.Frame(inner, bg="#F8FAFC", highlightbackground="#E8EDF5", highlightthickness=1)
        meta.pack(fill="x", pady=(0, 8))
        self._meta_item(meta, "난이도", self.difficulty_var, 0)
        self._meta_item(meta, "유일해", self.unique_var, 1)
        self._meta_item(meta, "변형 제약", self.constraint_var, 2)

        self._section_label(inner, "RULE SUMMARY")
        self.rule_text = tk.Text(
            inner, height=3, wrap="word", bg="#F8FAFC", fg="#475569",
            relief="flat", font=("Malgun Gothic", 9), padx=10, pady=9,
            selectbackground=COLORS["selected"],
        )
        self.rule_text.pack(fill="x", pady=(6, 8))
        self.rule_text.configure(state="disabled")

        action_row = tk.Frame(action_dock, bg=COLORS["panel"])
        action_row.pack(fill="x", pady=(0, 7))
        self._button(action_row, "AI 힌트", self.show_hint, primary=False).pack(
            side="left", fill="x", expand=True, padx=(0, 5)
        )
        self._button(action_row, "현재 상태 검증", self.check_board, primary=False).pack(
            side="left", fill="x", expand=True, padx=(5, 0)
        )

        speed_row = tk.Frame(action_dock, bg=COLORS["panel"])
        speed_row.pack(fill="x", pady=(0, 6))
        tk.Label(
            speed_row, text="탐색 재생 속도", bg=COLORS["panel"], fg=COLORS["muted"],
            font=("Malgun Gothic", 9),
        ).pack(side="left")
        self.speed_box = ttk.Combobox(
            speed_row, textvariable=self.speed_var, state="readonly",
            values=("느리게", "보통", "빠르게"), width=8, style="Demo.TCombobox",
        )
        self.speed_box.pack(side="right")

        play_row = tk.Frame(action_dock, bg=COLORS["panel"])
        play_row.pack(fill="x", pady=(0, 7))
        self._button(play_row, "과정 보며 풀기", self.solve_board, primary=True).pack(
            side="left", fill="x", expand=True, padx=(0, 5)
        )
        self.pause_button = self._button(play_row, "일시정지", self.toggle_pause, primary=False)
        self.pause_button.pack(side="left", padx=(5, 0))
        reset_row = tk.Frame(action_dock, bg=COLORS["panel"])
        reset_row.pack(fill="x")
        self._button(reset_row, "처음 상태로 되돌리기", self.reset_board, primary=False).pack(
            side="left", fill="x", expand=True, padx=(0, 5)
        )
        # 독립 검사기(independent_checker)가 읽는 sudoku-result-v1 형식으로 저장한다.
        self._button(reset_row, "결과 JSON 저장", self.save_result_json, primary=False).pack(
            side="left", fill="x", expand=True, padx=(5, 0)
        )

        # 통계 칸은 늘 두 줄 높이로 둔다. 한 줄 ↔ 두 줄로 바뀌면 위 정보 영역 높이가 흔들려
        # 재생 중에 스크롤바가 생겼다 사라진다.
        self.stats_label = tk.Label(
            action_dock, textvariable=self.stats_var, bg=COLORS["success_bg"], fg="#047857",
            font=("Malgun Gothic", 9), anchor="w", justify="left", wraplength=340,
            padx=12, pady=6, height=2,
        )
        self.stats_label.pack(fill="x", pady=(8, 0))

        status = tk.Label(
            self, textvariable=self.status_var, bg="#172033", fg="#E5E7EB",
            font=("Malgun Gothic", 9), anchor="w", padx=24, pady=10,
        )
        status.pack(fill="x", side="bottom")

    # ------------------------------------------------------------ LLM(FactChat) 연동

    def _build_llm_bar(self, header: tk.Widget) -> None:
        """헤더 가운데 빈 공간에 FactChat 키·모델·연결 상태를 둔다(오른쪽 패널 높이는 그대로)."""
        bar = tk.Frame(header, bg=COLORS["panel"])
        bar.pack(side="right", padx=(0, 4), pady=6)
        if llm_panel is None:
            tk.Label(
                bar, text=f"LLM 연동을 불러오지 못했습니다: {globals().get('LLM_IMPORT_ERROR', '')}"[:80],
                bg=COLORS["panel"], fg=COLORS["danger"], font=("Malgun Gothic", 8),
            ).pack()
            return
        ttk.Style(self).configure("Llm.TCombobox", fieldbackground="#F8FAFC", background="#F8FAFC",
                                  foreground=COLORS["ink"], bordercolor=COLORS["line"], padding=3)

        row = tk.Frame(bar, bg=COLORS["panel"])
        row.pack(anchor="e")
        tk.Label(row, text="FactChat 키", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Malgun Gothic", 9)).pack(side="left", padx=(0, 5))
        self.llm_key_entry = tk.Entry(
            row, textvariable=self.llm_key_var, show="*", width=16, font=("Segoe UI", 10), bg="#F8FAFC",
            relief="flat", highlightthickness=1, highlightbackground=COLORS["line"],
            highlightcolor=COLORS["primary"],
        )
        self.llm_key_entry.pack(side="left", ipady=3)
        # Windows/Tk 환경에 따라 기본 Ctrl+V가 상위 키 바인딩에 먹히는 경우가 있어
        # API 키 입력칸에는 붙여넣기를 명시적으로 연결한다.
        for sequence in ("<Control-v>", "<Control-V>", "<Shift-Insert>", "<<Paste>>"):
            self.llm_key_entry.bind(sequence, self._paste_llm_key)
        self.llm_key_entry.bind("<Button-3>", self._show_llm_key_menu)
        self.llm_key_menu = tk.Menu(self, tearoff=False, font=("Malgun Gothic", 9))
        self.llm_key_menu.add_command(label="붙여넣기", command=self._paste_llm_key)
        self.llm_key_menu.add_command(label="키 지우기", command=self._clear_llm_key)
        tk.Button(
            row, text="붙여넣기", command=self._paste_llm_key, bg="#EEF2FF", fg=COLORS["primary_dark"],
            activebackground=COLORS["selected"], relief="flat", cursor="hand2",
            font=("Malgun Gothic", 8, "bold"), padx=5, pady=2,
        ).pack(side="left", padx=(4, 0))
        default_label = llm_panel.model_label(llm_panel.DEFAULT_MODEL)
        self.llm_model_lookup = {default_label: llm_panel.DEFAULT_MODEL}
        self.llm_model_box = ttk.Combobox(
            row, textvariable=self.llm_model_var, state="readonly", values=[default_label], width=24,
            style="Llm.TCombobox", font=("Malgun Gothic", 9),
        )
        self.llm_model_box.pack(side="left", padx=(6, 6))
        self.llm_model_var.set(default_label)
        self.llm_model_var.trace_add("write", lambda *_args: self._refresh_llm_status())
        tk.Button(
            row, text="연결 확인", command=self.connect_llm, bg="#F8FAFC", fg=COLORS["ink"],
            activebackground=COLORS["selected"], relief="flat", cursor="hand2",
            font=("Malgun Gothic", 9, "bold"), padx=8, pady=2,
            highlightthickness=1, highlightbackground=COLORS["line"],
        ).pack(side="left")

        status_row = tk.Frame(bar, bg=COLORS["panel"])
        status_row.pack(fill="x", pady=(3, 0))
        self.llm_spec_button = tk.Button(
            status_row, text="명세 보기", command=self.show_llm_spec, bg=COLORS["panel"],
            fg=COLORS["primary_dark"], activebackground=COLORS["panel"], relief="flat", bd=0,
            cursor="hand2", font=("Malgun Gothic", 8, "underline"), padx=2, pady=0, state="disabled",
        )
        self.llm_spec_button.pack(side="right")
        self.llm_status_label = tk.Label(
            status_row, textvariable=self.llm_status_var, bg=COLORS["panel"], fg=COLORS["muted"],
            font=("Malgun Gothic", 8), anchor="w",
        )
        self.llm_status_label.pack(side="left", fill="x", expand=True)
        self.llm_key_var.trace_add("write", lambda *_args: self._on_llm_key_change())
        self._refresh_llm_status()

    def _paste_llm_key(self, _event: tk.Event | None = None) -> str:
        """클립보드의 API 키를 메모리에만 넣는다. 키 값은 로그에 출력하지 않는다."""
        try:
            value = self.clipboard_get().strip()
        except tk.TclError:
            self._set_llm_status("클립보드에 붙여넣을 텍스트가 없습니다.", "danger")
            return "break"
        if not value:
            self._set_llm_status("클립보드가 비어 있습니다.", "danger")
            return "break"
        self.llm_key_var.set(value)
        self.llm_key_entry.focus_set()
        self.llm_key_entry.icursor("end")
        self._set_llm_status("API 키를 붙여넣었습니다 · ‘연결 확인’을 누르세요")
        return "break"

    def _clear_llm_key(self) -> None:
        self.llm_key_var.set("")
        self.llm_key_entry.focus_set()

    def _show_llm_key_menu(self, event: tk.Event) -> str:
        try:
            self.llm_key_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.llm_key_menu.grab_release()
        return "break"

    def _llm_key(self) -> str:
        return self.llm_key_var.get().strip() or llm_panel.env_key()

    def _llm_model(self) -> str:
        return self.llm_model_lookup.get(self.llm_model_var.get(), llm_panel.DEFAULT_MODEL)

    def _set_llm_status(self, text: str, color: str = "muted") -> None:
        self.llm_status_var.set(text)
        self.llm_status_label.configure(fg=COLORS.get(color, color))

    def _refresh_llm_status(self, extra: str | None = None) -> None:
        if extra is not None:
            self.llm_status_extra = extra
        extra = self.llm_status_extra
        model = self.llm_model_var.get()
        if self.llm_connected_key and self.llm_connected_key == self._llm_key():
            self._set_llm_status(f"✔ 연결됨 · {model}" + (f" · {extra}" if extra else ""), "solved")
        elif self.llm_key_var.get().strip():
            self._set_llm_status("키 입력됨 · ‘연결 확인’으로 키와 모델 목록을 확인하세요")
        elif llm_panel.env_key():
            self._set_llm_status("환경변수 키(FACTCHAT_API_KEY) 사용 중 · ‘연결 확인’으로 모델 목록 보기")
        else:
            self._set_llm_status("API 키를 붙여넣고 ‘연결 확인’을 누르세요 (화면에는 *로 표시)")

    def _on_llm_key_change(self) -> None:
        if self.llm_connected_key is not None and self.llm_connected_key != self._llm_key():
            self.llm_connected_key = None
            self.llm_status_extra = ""
        self._refresh_llm_status()

    def connect_llm(self) -> None:
        if self.llm_job is not None:
            return
        key = self._llm_key()
        if not key:
            self._set_llm_status("API 키를 먼저 입력하세요.", "danger")
            return
        self._set_llm_status("연결 확인 중… (키 확인 · 크레딧 · 모델 목록)", "primary_dark")
        self.llm_job = llm_panel.Background(
            self, lambda _progress: llm_panel.connect_job(key),
            on_done=lambda data: self._connected(key, data), on_error=self._llm_connect_failed,
        )

    def _connected(self, key: str, data: dict[str, Any]) -> None:
        self.llm_job = None
        current = self._llm_model()
        lookup = {llm_panel.model_label(m["id"], m["vendor"]): m["id"] for m in data["models"]}
        if not lookup:
            lookup = {llm_panel.model_label(llm_panel.DEFAULT_MODEL): llm_panel.DEFAULT_MODEL}
        self.llm_model_lookup = lookup
        self.llm_model_box.configure(values=list(lookup))
        ids = list(lookup.values())
        pick = current if current in ids else (llm_panel.DEFAULT_MODEL if llm_panel.DEFAULT_MODEL in ids else ids[0])
        self.llm_model_var.set(next(label for label, mid in lookup.items() if mid == pick))
        self.llm_connected_key = key
        self._refresh_llm_status(llm_panel.credits_text(data["credits"], short=True))
        self.status_var.set("FactChat 연결 확인 완료 · ‘자연어로 불러오기’로 퍼즐 설명을 LLM에 넘길 수 있습니다.")

    def _llm_connect_failed(self, exc: Exception) -> None:
        self.llm_job = None
        self.llm_connected_key = None
        message = llm_panel.friendly_error(exc)
        self._set_llm_status(f"연결 실패 · {message}"[:60], "danger")
        self.status_var.set(f"FactChat 연결 실패 · {message}")

    def open_llm_dialog(self) -> None:
        if llm_panel is None:
            return
        key = self._llm_key()
        if not key:
            self._set_llm_status("API 키를 먼저 입력하세요.", "danger")
            self.llm_key_entry.focus_set()
            return
        for child in self.winfo_children():
            if isinstance(child, llm_panel.NaturalLanguageDialog):
                child.lift()
                child.focus_set()
                return
        self._cancel_animation()
        llm_panel.NaturalLanguageDialog(
            self, key=key, model=self._llm_model(), model_text=self.llm_model_var.get(),
            on_success=self.apply_llm_result, colors=COLORS,
        )

    def apply_llm_result(self, payload: dict[str, Any]) -> None:
        result = payload["result"]
        demo = payload.get("demo")
        givens = payload.get("givens") or "." * 81
        spec = {
            "name": f"llm-{demo['id']}" if demo else "llm",
            "title": f"LLM · {demo['id']}" if demo else "LLM 파싱 결과",
            "note": "",
            "rules_text": llm_panel.rules_only(payload["text"]) or "추가 규칙 없음",
            "givens": givens,
            "constraints": result.spec.get("constraints", []),
            # 결과 JSON에 함께 저장해, 독립 검사기가 '퍼즐 전체를 검사하지 못함'을 알 수 있게 한다.
            "unsupported": list(result.unsupported or []),
        }
        notes = [f"{payload['model']} · 호출 {result.n_attempts}회 · {payload['elapsed']:.1f}초"]
        if payload.get("gold_match") is not None:
            notes.append("정답 명세 일치 ✔" if payload["gold_match"] else "정답 명세와 다름 ✘")
        if result.unsupported:
            notes.append(f"미적용 규칙 {len(result.unsupported)}개")
        spec["note"] = " · ".join(notes)
        self.llm_payload = payload
        self.llm_spec_button.configure(state="normal")
        self._apply_spec(spec, "LLM이 만든 명세를 보드에 올렸습니다 · ‘과정 보며 풀기’로 백트래킹 탐색을 확인하세요.")
        extra = ""
        if payload.get("credits_after") is not None:
            extra = llm_panel.credits_text(payload["credits_after"], short=True)
            if payload.get("used") is not None:
                extra += f" · 이번 파싱 {payload['used']:.1f}"
        self._refresh_llm_status(extra)
        if result.unsupported:
            messagebox.showinfo(
                "적용 안 된 규칙",
                "엔진이 지원하지 않거나 정보가 부족해 적용하지 않은 규칙입니다:\n\n"
                + "\n".join(f"· {u}" for u in result.unsupported),
            )

    def show_llm_spec(self) -> None:
        if self.llm_payload is not None and llm_panel is not None:
            llm_panel.SpecViewer(self, self.llm_payload, COLORS)

    def _build_scroll_area(self, parent: tk.Widget) -> tk.Frame:
        """세로 스크롤되는 정보 영역을 만들고, 내용을 담을 Frame을 돌려준다.

        내용이 영역보다 길 때만 스크롤바를 보이고 마우스 휠을 받는다.
        """
        holder = tk.Frame(parent, bg=COLORS["panel"])
        holder.pack(side="top", fill="both", expand=True, pady=(14, 4))
        canvas = tk.Canvas(holder, bg=COLORS["panel"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=COLORS["panel"])
        window = canvas.create_window((24, 0), window=inner, anchor="nw")
        self.info_canvas = canvas
        self.info_inner = inner
        self.info_scrollbar = scrollbar

        def refresh(_event: tk.Event | None = None) -> None:
            # 내용 폭은 스크롤바 유무와 상관없이 고정한다(오른쪽 여백에 스크롤바 자리를 미리 둔다).
            # 스크롤바가 생길 때 폭이 줄면 줄바꿈이 늘어 스크롤바가 사라지지 않는 순환이 생긴다.
            total = holder.winfo_width()
            if total > 1:
                canvas.itemconfigure(window, width=max(total - 24 - 24, 100))
            width = canvas.winfo_width()
            needed = inner.winfo_reqheight()
            canvas.configure(scrollregion=(0, 0, width, needed))
            overflow = needed > canvas.winfo_height() > 1
            if overflow and not scrollbar.winfo_ismapped():
                scrollbar.pack(side="right", fill="y", before=canvas)
            elif not overflow and scrollbar.winfo_ismapped():
                scrollbar.pack_forget()
                canvas.yview_moveto(0)

        def on_wheel(event: tk.Event) -> None:
            if scrollbar.winfo_ismapped():
                canvas.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")

        canvas.bind("<Configure>", refresh)
        inner.bind("<Configure>", refresh)
        holder.bind("<Configure>", refresh, add="+")
        # 휠은 포인터가 정보 영역 위에 있을 때만 받는다(콤보박스 목록 등 다른 곳과 겹치지 않게).
        holder.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", on_wheel))
        holder.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        return inner

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
        self._apply_spec(spec, "예제를 불러왔습니다 · 제약 도형을 확인한 뒤 힌트 또는 풀이를 눌러보세요.")

    def _apply_spec(self, spec: dict[str, Any], status: str) -> None:
        """명세(예제 파일 또는 LLM 파싱 결과)를 보드에 올린다."""
        self.current_spec = json.loads(json.dumps(spec, ensure_ascii=False))
        self.original_values = givens_to_values(spec.get("givens", ""))
        self.values = dict(self.original_values)
        self.value_source = {cell: "given" for cell in self.original_values}
        self.selected = None
        self.hint_cells.clear()
        self.error_cells.clear()
        self.solve_result = None
        if hasattr(self, "info_canvas"):
            self.info_canvas.yview_moveto(0)

        self.title_var.set(str(spec.get("title") or spec.get("name") or "변형 스도쿠"))
        self.subtitle_var.set(str(spec.get("note") or "변형 제약을 만족하도록 퍼즐을 풀어보세요."))
        self._set_rule_text(str(spec.get("rules_text") or "클래식 스도쿠 규칙"))
        self._update_constraint_summary()
        self.difficulty_var.set("분석 중…")
        self.unique_var.set("검증 중…")
        self.stats_var.set("풀이 후 탐색 통계가 표시됩니다.")
        self.status_var.set(status)
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
        self.error_cells.clear()
        self.solve_result = None
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
        self.error_cells.clear()
        self.solve_result = None
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
        shown = len(self.trace_events)
        if shown == self.trace_total:
            scope = f"전체 {self.trace_total}단계"
        else:
            # 아래 상태줄의 'x/650'과 헷갈리지 않게, 표본 재생이라는 사실을 처음부터 밝힌다.
            scope = f"전체 {self.trace_total}단계 중 {shown}단계 표본"
        self.stats_var.set(
            f"탐색 과정 재생 중 · {scope}\n"
            "주황색은 임시 값이며 백트래킹 때 바뀔 수 있습니다."
        )
        self._animate_trace()

    def _progress_text(self) -> str:
        """상태줄의 재생 위치. 표본 재생이면 그 사실과 전체 단계 수를 함께 적는다."""
        shown = len(self.trace_events)
        if shown == self.trace_total:
            return f"{self.trace_index}/{shown}"
        return f"{self.trace_index}/{shown} (전체 {self.trace_total}단계 중 표본)"

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
        self.status_var.set(f"탐색 {self._progress_text()} · {stage}{cell_text}")
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
            self.status_var.set(f"탐색 과정 일시정지 · {self._progress_text()}")
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
        sampled = (
            "" if self.trace_total == len(self.trace_events)
            else f" · {self.trace_total}단계 중 {len(self.trace_events)}단계 표본 재생"
        )
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

    # ------------------------------------------------------------ 결과 저장 (독립 검사기 연동)

    def result_payload(self) -> dict[str, Any]:
        """현재 보드를 독립 검사기가 읽는 sudoku-result-v1 형식으로 만든다.

        보드가 81칸 모두 채워져 있어야 한다. 그렇지 않으면 ValueError.
        """
        if len(self.values) != 81:
            raise ValueError(f"보드에 빈칸이 {81 - len(self.values)}개 있습니다. 풀이를 끝낸 뒤 저장하세요.")
        spec = self.current_spec
        actual = "".join(str(self.values[(r, c)]) for r in range(9) for c in range(9))
        sources = Counter(self.value_source.get(cell, "user") for cell in self.values)
        payload: dict[str, Any] = {
            "format": "sudoku-result-v1",
            "source": "Sudoku AI Studio GUI",
            "puzzle": str(spec.get("name") or spec.get("title") or "gui"),
            "title": str(spec.get("title") or spec.get("name") or ""),
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "givens": spec.get("givens", "." * 81),
            "constraints": spec.get("constraints", []),
        }
        if "unsupported" in spec:
            payload["unsupported"] = spec["unsupported"]
        if spec.get("solution"):
            payload["reference_source"] = "puzzle_json.solution"
            payload["expected_solution"] = spec["solution"]
        payload["actual_solution"] = actual
        payload["filled_by"] = {
            "given": sources.get("given", 0),
            "user": sources.get("user", 0),
            "solver": sources.get("solved", 0) + sources.get("trying", 0),
        }
        result = self.solve_result
        if result is not None and result.solution is not None and all(
            self.values.get(cell) == value for cell, value in result.solution.items()
        ):
            payload["solver"] = {
                "algorithm": "backtracking",
                "variable_order": result.config.var_order,
                "value_order": result.config.val_order,
                "propagation": result.config.propagation,
            }
            payload["stats"] = result.stats.as_dict()
        return payload

    def save_result_json(self) -> None:
        if self.animating:
            self.status_var.set("탐색 과정 재생이 끝난 뒤 저장하세요.")
            return
        try:
            payload = self.result_payload()
        except ValueError as exc:
            self.status_var.set(f"저장할 수 없습니다 · {exc}")
            messagebox.showwarning("결과 JSON 저장", str(exc))
            return
        name = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", payload["puzzle"]).strip("_") or "result"
        path = filedialog.asksaveasfilename(
            title="결과 JSON 저장", defaultextension=".json", filetypes=[("JSON", "*.json")],
            initialdir=str(ROOT), initialfile=f"{name}_result.json",
        )
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            self._show_error("저장 실패", str(exc))
            return
        self.status_var.set(f"결과를 저장했습니다 · 독립 검사기에서 열어 확인하세요: {Path(path).name}")
        messagebox.showinfo(
            "결과 JSON 저장",
            f"저장했습니다.\n{path}\n\n검사: python independent_checker/checker.py \"{path}\"",
        )

    # ------------------------------------------------------------ 힌트

    def find_wrong_inputs(self) -> list[tuple[int, int]] | None:
        """사용자가 넣은 숫자 중 정답과 다른 칸을 찾는다.

        입력이 아직 완성 가능한 상태면 빈 목록, 틀린 칸이 있으면 그 칸 목록을 돌려준다.
        입력으로는 완성할 수 없지만 어느 칸이 틀렸는지 정할 수 없으면(퍼즐 해가 없거나 여러 개)
        None을 돌려준다.
        """
        user = {cell: v for cell, v in self.values.items() if cell not in self.original_values}
        if not user:
            return []
        try:
            current = load_spec(self._current_spec_with_values())
            if solve(current, SolverConfig(time_limit=3.0)).solved:
                return []
        except SpecError:
            pass  # 입력이 단서·규칙과 이미 충돌: 아래에서 어느 칸이 틀렸는지 찾는다.
        base_model = load_spec(self.current_spec)
        # 정답이 하나로 정해질 때만 '정답과 다른 칸'을 말할 수 있다(빈 보드 등은 불가).
        if count_solutions(base_model, limit=2, config=SolverConfig(time_limit=5.0)) != 1:
            return None
        base = solve(base_model, SolverConfig(time_limit=5.0))
        if base.solution is None:
            return None
        return sorted(cell for cell, value in user.items() if base.solution.get(cell) != value)

    def show_hint(self) -> None:
        if self.animating:
            self.status_var.set("탐색 과정 재생이 끝난 뒤 힌트를 받으세요.")
            return
        try:
            wrong = self.find_wrong_inputs()
        except Exception as exc:
            self._show_error("힌트 오류", str(exc))
            return
        if wrong:
            # 틀린 입력을 전제로 추론하면 '확정'이라며 틀린 힌트를 내게 된다. 먼저 고치게 한다.
            self.error_cells = set(wrong)
            self.hint_cells.clear()
            self.draw_board()
            names = ", ".join(f"r{r + 1}c{c + 1}" for r, c in wrong)
            self.status_var.set(f"입력 오류 · 정답과 다른 칸: {names} (빨간 칸)")
            messagebox.showwarning(
                "AI 힌트",
                f"직접 입력한 숫자 중 정답과 다른 칸이 있습니다: {names}\n\n"
                "이 상태로는 올바른 힌트를 낼 수 없습니다. 빨간 칸을 지우거나 고친 뒤 다시 눌러 주세요.",
            )
            return
        if wrong is None:
            self._show_error(
                "AI 힌트",
                "현재 입력으로는 퍼즐을 완성할 수 없어 힌트를 낼 수 없습니다.\n"
                "직접 넣은 숫자를 확인하거나 ‘처음 상태로 되돌리기’를 눌러 주세요.",
            )
            return
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
        self.error_cells.clear()
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
        # API 키 입력칸 등에서 친 글자가 보드에 들어가지 않게 한다.
        if isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Text)):
            return
        if event.char and event.char in "123456789":
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
        self.error_cells.discard(self.selected)
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
                if (row, col) in self.error_cells:
                    fill = "#FEE2E2"
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
            if cell in self.error_cells:
                color = COLORS["danger"]
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
    if llm_panel is None:
        print(f"LLM 연동 불러오기 실패: {globals().get('LLM_IMPORT_ERROR', '')}")
        return 1
    demos = llm_panel.load_demo_texts()
    from llm_parser.checks import extract_givens
    found = sum(extract_givens(d["text"]) is not None for d in demos)
    print(f"LLM 연동 OK: 시연용 문장 {len(demos)}개, 단서 격자 추출 {found}/{len(demos)}")
    return 0 if solved == len(examples) and found == len(demos) else 1


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

