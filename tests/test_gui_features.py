"""GUI(gui/app.py) 기능 테스트: 힌트 전 입력 검사, 결과 JSON 저장, 재생 단계 표시, 정보 패널 크기.

창을 띄우지 않고(withdraw) 메서드를 직접 부른다. 대화상자는 가로채서 기록만 한다.
Tk를 쓸 수 없는 환경(디스플레이 없음)에서는 건너뛴다.

    python -m pytest -q tests/test_gui_features.py
"""
from __future__ import annotations

import json
import tkinter as tk

import pytest

from conftest import ROOT

app_module = pytest.importorskip("gui.app")
from independent_checker.validator import validate_payload  # noqa: E402


@pytest.fixture
def dialogs(monkeypatch):
    calls: list[tuple[str, str, str]] = []
    for kind in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(
            app_module.messagebox, kind, lambda title, message, _k=kind, **_kw: calls.append((_k, title, message))
        )
    return calls


@pytest.fixture(scope="module")
def _shared_app():
    # Tk()를 한 프로세스에서 여러 번 만들면 Windows에서 간헐적으로 초기화에 실패하므로 한 번만 만든다.
    try:
        instance = app_module.SudokuDemoApp()
    except tk.TclError as exc:  # 디스플레이가 없는 환경
        pytest.skip(f"Tk를 쓸 수 없습니다: {exc}")
    instance.withdraw()
    instance.update()
    yield instance
    instance.destroy()


@pytest.fixture
def app(_shared_app, dialogs):
    _shared_app._cancel_animation()
    _shared_app.withdraw()
    _shared_app.new_blank()
    _shared_app.update()
    return _shared_app


def _load(app, prefix: str) -> dict:
    example = json.loads(next((ROOT / "examples").glob(f"{prefix}_*.json")).read_text(encoding="utf-8"))
    app._apply_spec(example, "test")
    return example


def _cell(solution: str, row: int, col: int) -> int:
    return int(solution[row * 9 + col])


def _set_user(app, cell: tuple[int, int], value: int) -> None:
    app.values[cell] = value
    app.value_source[cell] = "user"


# ---------------------------------------------------------------- 힌트 전 입력 검사

def test_hint_refuses_wrong_input_and_marks_cell(app, dialogs):
    example = _load(app, "05")
    solution = example["solution"]
    right = (0, 7)  # 정답과 같은 입력은 표시하지 않는다
    _set_user(app, right, _cell(solution, *right))
    wrong_value = 1 if _cell(solution, 0, 0) != 1 else 2
    _set_user(app, (0, 0), wrong_value)

    app.show_hint()

    assert app.error_cells == {(0, 0)}
    assert dialogs and dialogs[-1][0] == "showwarning"
    assert "r1c1" in dialogs[-1][2]
    assert "입력 오류" in app.status_var.get()


def test_hint_still_works_with_correct_input(app, dialogs):
    example = _load(app, "05")
    _set_user(app, (0, 7), _cell(example["solution"], 0, 7))
    app.show_hint()
    assert not app.error_cells
    assert app.status_var.get().startswith("힌트")
    assert dialogs[-1][0] == "showinfo"


def test_editing_a_wrong_cell_clears_its_mark(app):
    example = _load(app, "05")
    _set_user(app, (0, 0), 1 if _cell(example["solution"], 0, 0) != 1 else 2)
    app.show_hint()
    app.selected = (0, 0)
    app.enter_value(0)
    assert (0, 0) not in app.error_cells


def test_hint_on_non_unique_board_does_not_name_cells(app, dialogs):
    app.new_blank()
    # 같은 행에 같은 숫자 → 완성 불가. 빈 보드는 정답이 하나가 아니므로 칸을 지목하지 않는다.
    _set_user(app, (0, 0), 5)
    _set_user(app, (0, 1), 5)
    app.show_hint()
    assert not app.error_cells
    assert dialogs[-1][0] == "showerror"


# ---------------------------------------------------------------- 결과 JSON

def test_result_payload_is_accepted_by_independent_checker(app):
    example = _load(app, "08")
    for i, ch in enumerate(example["solution"]):
        cell = (i // 9, i % 9)
        if cell not in app.original_values:
            app.values[cell] = int(ch)
            app.value_source[cell] = "solved"
    payload = app.result_payload()
    assert payload["format"] == "sudoku-result-v1"
    assert payload["expected_solution"] == example["solution"]
    assert validate_payload(payload)["status"] == "correct"

    # 한 칸을 바꾸면 검사기가 위반으로 잡는다.
    broken = dict(payload)
    first_free = next(i for i in range(81) if (i // 9, i % 9) not in app.original_values)
    swap_with = next(
        j for j in range(first_free + 1, first_free // 9 * 9 + 9)
        if (j // 9, j % 9) not in app.original_values
    )
    chars = list(payload["actual_solution"])
    chars[first_free], chars[swap_with] = chars[swap_with], chars[first_free]
    broken["actual_solution"] = "".join(chars)
    assert validate_payload(broken)["status"] == "violation"


def test_result_payload_requires_full_board(app):
    _load(app, "05")
    with pytest.raises(ValueError):
        app.result_payload()


def test_result_payload_carries_llm_unsupported_rules(app):
    example = _load(app, "06")
    spec = dict(example, unsupported=["흰 점: r1c1-r1c2"])
    app._apply_spec(spec, "test")
    for i, ch in enumerate(example["solution"]):
        app.values[(i // 9, i % 9)] = int(ch)
    payload = app.result_payload()
    assert payload["unsupported"] == ["흰 점: r1c1-r1c2"]
    assert validate_payload(payload)["status"] == "unverifiable"


def test_solver_stats_included_only_for_solver_result(app):
    _load(app, "06")
    app.solve_board()
    app._cancel_animation()  # 재생은 건너뛰고 엔진 해를 바로 올린다
    for cell, value in app.solve_result.solution.items():
        app.values[cell] = value
    payload = app.result_payload()
    assert payload["solver"]["propagation"] == "ac3"
    assert "branch_nodes" in payload["stats"]


# ---------------------------------------------------------------- 재생 단계 표시

def test_stats_box_height_does_not_change_during_playback(app):
    """통계 칸 높이가 재생 중에 바뀌면 정보 영역이 줄어 스크롤바가 생겼다 사라진다."""
    app.deiconify()
    app.geometry("1120x810")
    _load(app, "08")
    app.update()
    idle = app.stats_label.winfo_height()
    app.solve_board()  # 08은 781단계 중 650단계 표본 재생
    app.update()
    playing = app.stats_label.winfo_height()
    assert "650단계 표본" in app.stats_var.get()
    app._cancel_animation()
    app.trace_index = len(app.trace_events)
    app.animating = True
    app._animate_trace()  # 마지막 단계 → 재생 완료 문구
    app.update()
    done = app.stats_label.winfo_height()
    assert app.stats_var.get().startswith("풀이 완료")
    assert idle == playing == done
    assert not app.info_scrollbar.winfo_ismapped()


def test_progress_text_mentions_sampling(app):
    app.trace_total = 781
    app.trace_events = [object()] * 650
    app.trace_index = 31
    assert app._progress_text() == "31/650 (전체 781단계 중 표본)"
    app.trace_total = 116
    app.trace_events = [object()] * 116
    assert app._progress_text() == "31/116"


# ---------------------------------------------------------------- 정보 패널

def test_info_panel_scrolls_when_window_is_short(app):
    app.deiconify()
    app.geometry("1120x700")
    _load(app, "08")
    app.difficulty_var.set("논리 불가(추측 필요)")
    app.update()
    overflow = app.info_inner.winfo_reqheight() > app.info_canvas.winfo_height()
    assert overflow, "700px 창에서는 정보 영역이 넘쳐야 이 테스트가 의미 있다"
    assert app.info_scrollbar.winfo_ismapped()
    top, bottom = app.info_canvas.yview()
    assert bottom < 1.0  # 아래쪽 내용(규칙 요약)으로 스크롤할 수 있다
    app.info_canvas.yview_moveto(1.0)
    assert app.info_canvas.yview()[1] == pytest.approx(1.0)


def test_info_panel_fits_at_default_tall_window(app):
    app.deiconify()
    # 먼저 낮은 창에서 스크롤바를 띄운 뒤 키운다: 스크롤바가 생기며 줄바꿈이 늘어
    # 창을 키워도 스크롤바가 남는 순환이 없어야 한다.
    app.geometry("1120x700")
    _load(app, "08")
    app.difficulty_var.set("논리 불가(추측 필요)")
    app.update()
    assert app.info_scrollbar.winfo_ismapped()
    app.geometry("1120x810")
    for path in sorted((ROOT / "examples").glob("*.json")):
        app._apply_spec(json.loads(path.read_text(encoding="utf-8")), "test")
        app.difficulty_var.set("논리 불가(추측 필요)")
        app.update()
        assert app.info_inner.winfo_reqheight() <= app.info_canvas.winfo_height(), path.name
        assert not app.info_scrollbar.winfo_ismapped(), path.name
