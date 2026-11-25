"""엔진과 분리된 변형 스도쿠 결과 검사기 GUI/CLI."""

from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

try:
    from independent_checker.validator import (
        STATUS_CORRECT,
        STATUS_UNVERIFIABLE,
        STATUS_VIOLATION,
        validate_file,
        write_report,
    )
except ImportError:  # python independent_checker/checker.py 실행 시
    from validator import (  # type: ignore
        STATUS_CORRECT,
        STATUS_UNVERIFIABLE,
        STATUS_VIOLATION,
        validate_file,
        write_report,
    )


STATUS_COLORS = {
    STATUS_CORRECT: "#16803C",
    STATUS_VIOLATION: "#D92D20",
    STATUS_UNVERIFIABLE: "#B54708",
}


def _issue_line(issue: dict[str, Any]) -> str:
    cells = ", ".join(issue.get("cells") or [])
    location = f" [{cells}]" if cells else ""
    expected = issue.get("expected")
    actual = issue.get("actual")
    comparison = ""
    if expected is not None or actual is not None:
        comparison = f" · 기대 {expected!s}, 실제 {actual!s}"
    return f"• {issue.get('message', '알 수 없는 오류')}{location}{comparison}"


def _report_text(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"퍼즐: {report['puzzle']}",
        f"단서 검사: {summary['givens_checked']}개 · 변경 {summary['givens_changed']}개",
        f"추가 제약 검사: {summary['constraints_checked']}/{summary['constraints_declared']}",
        f"위반 수: {summary['violation_count']}개",
    ]
    sections = (
        ("위반 내역", report["violations"]),
        ("검사하지 못한 항목", report["unverifiable_reasons"]),
    )
    for heading, issues in sections:
        if not issues:
            continue
        lines.append("")
        lines.append(heading)
        lines.extend(_issue_line(issue) for issue in issues[:12])
        if len(issues) > 12:
            lines.append(f"• 그 밖의 내역 {len(issues) - 12}개")
    if report["status"] == STATUS_CORRECT:
        lines.extend(("", "모든 단서, 행·열·박스 및 변형 제약을 만족합니다."))
    return "\n".join(lines)


class CheckerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("독립 스도쿠 결과 검사기")
        self.geometry("720x620")
        self.minsize(660, 540)
        self.configure(bg="#F4F6FA")

        self.result_path = tk.StringVar()
        self.result_text = tk.StringVar(value="결과 JSON을 선택하세요")
        self.detail_text = tk.StringVar(value="검사 후 단서 및 규칙별 판정 내역이 표시됩니다.")
        self.last_report: dict[str, Any] | None = None

        tk.Label(
            self,
            text="스도쿠 결과 독립 검사기",
            font=("Malgun Gothic", 19, "bold"),
            bg="#F4F6FA",
            fg="#172033",
        ).pack(pady=(24, 6))
        tk.Label(
            self,
            text="엔진 코드를 사용하지 않고 결과 JSON의 명세를 직접 검사합니다.",
            font=("Malgun Gothic", 9),
            bg="#F4F6FA",
            fg="#667085",
        ).pack(pady=(0, 18))

        self._file_row("결과 JSON", self.result_path, self._choose_result)

        buttons = tk.Frame(self, bg="#F4F6FA")
        buttons.pack(pady=(18, 12))
        tk.Button(
            buttons,
            text="결과 검사",
            command=self._compare,
            font=("Malgun Gothic", 11, "bold"),
            bg="#315EFB",
            fg="white",
            activebackground="#244AC7",
            activeforeground="white",
            relief="flat",
            padx=28,
            pady=9,
            cursor="hand2",
        ).pack(side="left", padx=5)
        self.save_button = tk.Button(
            buttons,
            text="검사 보고서 JSON 저장",
            command=self._save_report,
            state="disabled",
            font=("Malgun Gothic", 10, "bold"),
            bg="#E8EDFF",
            fg="#244AC7",
            activebackground="#DDE5FF",
            relief="flat",
            padx=18,
            pady=9,
            cursor="hand2",
        )
        self.save_button.pack(side="left", padx=5)

        self.result_label = tk.Label(
            self,
            textvariable=self.result_text,
            font=("Malgun Gothic", 23, "bold"),
            bg="#F4F6FA",
            fg="#667085",
        )
        self.result_label.pack()

        detail_frame = tk.Frame(self, bg="white", highlightbackground="#D0D5DD", highlightthickness=1)
        detail_frame.pack(fill="both", expand=True, padx=34, pady=(14, 26))
        self.detail_label = tk.Label(
            detail_frame,
            textvariable=self.detail_text,
            font=("Malgun Gothic", 10),
            bg="white",
            fg="#344054",
            anchor="nw",
            justify="left",
            padx=16,
            pady=14,
            wraplength=620,
        )
        self.detail_label.pack(fill="both", expand=True)

    def _file_row(self, title: str, variable: tk.StringVar, command: Any) -> None:
        row = tk.Frame(self, bg="#F4F6FA")
        row.pack(fill="x", padx=34, pady=5)
        tk.Label(
            row,
            text=title,
            width=12,
            anchor="w",
            font=("Malgun Gothic", 10),
            bg="#F4F6FA",
            fg="#344054",
        ).pack(side="left")
        tk.Entry(
            row,
            textvariable=variable,
            state="readonly",
            readonlybackground="white",
            relief="solid",
            bd=1,
            font=("Malgun Gothic", 9),
        ).pack(side="left", fill="x", expand=True, ipady=6)
        tk.Button(
            row,
            text="선택",
            command=command,
            font=("Malgun Gothic", 9),
            relief="flat",
            bg="#E8EDFF",
            fg="#244AC7",
            padx=12,
            pady=5,
            cursor="hand2",
        ).pack(side="left", padx=(8, 0))

    def _choose_result(self) -> None:
        path = filedialog.askopenfilename(title="결과 JSON 선택", filetypes=[("JSON", "*.json")])
        if path:
            self.result_path.set(path)
            self.last_report = None
            self.result_text.set("결과 검사를 누르세요")
            self.result_label.configure(fg="#667085")
            self.detail_text.set("검사 후 단서 및 규칙별 판정 내역이 표시됩니다.")
            self.save_button.configure(state="disabled")

    def _compare(self) -> None:
        if not self.result_path.get():
            messagebox.showwarning("파일 필요", "검사할 결과 JSON을 선택하세요.")
            return
        report = validate_file(self.result_path.get())
        self.last_report = report
        self.result_text.set(report["status_label"])
        self.result_label.configure(fg=STATUS_COLORS[report["status"]])
        self.detail_text.set(_report_text(report))
        self.save_button.configure(state="normal")

    def _save_report(self) -> None:
        if self.last_report is None:
            return
        source = Path(self.result_path.get())
        path = filedialog.asksaveasfilename(
            title="검사 보고서 JSON 저장",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=f"{source.stem}_validation.json",
        )
        if not path:
            return
        try:
            write_report(self.last_report, path)
        except OSError as exc:
            messagebox.showerror("저장 실패", str(exc))
            return
        messagebox.showinfo("저장 완료", "독립 검사 보고서를 저장했습니다.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="엔진 독립 변형 스도쿠 결과 검사")
    parser.add_argument("result", nargs="?", help="검사할 결과 JSON")
    parser.add_argument("--report", type=Path, help="검사 보고서 JSON 저장 경로")
    args = parser.parse_args(argv)

    if args.result is None:
        CheckerApp().mainloop()
        return 0

    # Windows 콘솔(cp949)은 '•' 같은 문자를 못 써서 내역 출력 중에 죽는다. 못 쓰는 문자는 대체한다.
    try:
        sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    report = validate_file(args.result)
    print(report["status_label"])
    print(_report_text(report))
    if args.report:
        write_report(report, args.report)
    return {
        STATUS_CORRECT: 0,
        STATUS_VIOLATION: 1,
        STATUS_UNVERIFIABLE: 2,
    }[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
