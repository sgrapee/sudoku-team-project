"""독립 Validator의 정상/변조 입력 테스트. pytest 없이 실행 가능하다."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from independent_checker.validator import (
    STATUS_CORRECT,
    STATUS_UNVERIFIABLE,
    STATUS_VIOLATION,
    validate_payload,
)


ROOT = Path(__file__).resolve().parents[1]

# 클래식 규칙만 만족하는 완성 격자 (1행: 5 3 4 6 7 8 9 1 2)
SOLUTION = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"
# 대각선까지 만족하는 완성 격자 (examples/01_x_sudoku.json의 정답)
X_SOLUTION = "786421539594673281312985647823147965465239718179568324931856472648792153257314896"


def load_example(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


def payload(example: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": example.get("title", example.get("name", "test")),
        "givens": example["givens"],
        "constraints": example.get("constraints", []),
        "actual_solution": example["solution"],
    }


def cell(raw: Any) -> tuple[int, int]:
    if isinstance(raw, str):
        row_text, col_text = raw.lower().split("c")
        return int(row_text[1:]) - 1, int(col_text) - 1
    return int(raw[0]), int(raw[1])


def value(solution: str, raw: Any) -> int:
    row, col = cell(raw)
    return int(solution[row * 9 + col])


def set_value(solution: str, raw: Any, new_value: int) -> str:
    row, col = cell(raw)
    index = row * 9 + col
    return solution[:index] + str(new_value) + solution[index + 1:]


def swap_values(solution: str, first: Any, second: Any) -> str:
    a, b = cell(first), cell(second)
    ia, ib = a[0] * 9 + a[1], b[0] * 9 + b[1]
    chars = list(solution)
    chars[ia], chars[ib] = chars[ib], chars[ia]
    return "".join(chars)


def rules(report: dict[str, Any]) -> set[str]:
    return {issue["rule"] for issue in report["violations"]}


class IndependentValidatorTests(unittest.TestCase):
    def test_all_saved_example_solutions_pass(self) -> None:
        paths = sorted((ROOT / "examples").glob("*.json"))
        self.assertGreaterEqual(len(paths), 10)
        for path in paths:
            example = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                self.assertEqual(validate_payload(payload(example))["status"], STATUS_CORRECT)

    def test_given_change_is_reported(self) -> None:
        example = load_example("01_x_sudoku.json")
        case = payload(example)
        given_index = next(i for i, ch in enumerate(example["givens"]) if ch not in ".0")
        original = int(case["actual_solution"][given_index])
        changed = 1 if original != 1 else 2
        case["actual_solution"] = (
            case["actual_solution"][:given_index] + str(changed) + case["actual_solution"][given_index + 1:]
        )
        report = validate_payload(case)
        self.assertEqual(report["status"], STATUS_VIOLATION)
        self.assertIn("given", rules(report))

    def test_diagonal_mutation_fails(self) -> None:
        example = load_example("01_x_sudoku.json")
        case = payload(example)
        case["actual_solution"] = set_value(example["solution"], "r1c1", value(example["solution"], "r2c2"))
        self.assertIn("diagonal", rules(validate_payload(case)))

    def test_killer_sum_and_distinct_mutation_fail(self) -> None:
        example = load_example("02_killer.json")
        constraint = next(c for c in example["constraints"] if c["type"] == "killer")
        first, second = constraint["cells"][:2]
        case = payload(example)
        case["actual_solution"] = set_value(example["solution"], first, value(example["solution"], second))
        found = rules(validate_payload(case))
        self.assertIn("killer.sum", found)
        self.assertIn("killer.distinct", found)

    def test_thermo_requires_strict_increase(self) -> None:
        example = load_example("03_thermo_parity.json")
        constraint = next(c for c in example["constraints"] if c["type"] == "thermo")
        first, second = constraint["path"][:2]
        case = payload(example)
        # 같은 값도 실패해야 한다(비감소가 아니라 엄격 증가).
        case["actual_solution"] = set_value(example["solution"], second, value(example["solution"], first))
        self.assertIn("thermo", rules(validate_payload(case)))

    def test_even_and_odd_mutations_fail(self) -> None:
        example = load_example("03_thermo_parity.json")
        for kind, wrong_value, expected_rule in (("even", 1, "parity.even"), ("odd", 2, "parity.odd")):
            constraint = next(c for c in example["constraints"] if c["type"] == kind)
            case = payload(example)
            case["actual_solution"] = set_value(example["solution"], constraint["cells"][0], wrong_value)
            with self.subTest(kind=kind):
                self.assertIn(expected_rule, rules(validate_payload(case)))

    def test_arrow_mutation_fails(self) -> None:
        example = load_example("04_arrow_inequality.json")
        constraint = next(c for c in example["constraints"] if c["type"] == "arrow")
        original = value(example["solution"], constraint["circle"])
        case = payload(example)
        case["actual_solution"] = set_value(example["solution"], constraint["circle"], 1 if original != 1 else 2)
        self.assertIn("arrow", rules(validate_payload(case)))

    def test_lessthan_direction_mutation_fails(self) -> None:
        example = load_example("04_arrow_inequality.json")
        constraint = next(c for c in example["constraints"] if c["type"] == "lessthan")
        case = payload(example)
        case["actual_solution"] = swap_values(
            example["solution"], constraint["smaller"], constraint["larger"]
        )
        self.assertIn("lessthan", rules(validate_payload(case)))

    def test_sandwich_mutation_fails(self) -> None:
        example = load_example("05_sandwich_mix.json")
        constraint = next(c for c in example["constraints"] if c["type"] == "sandwich")
        index = constraint["index"]  # 명세대로 0-based
        line_cells = (
            [(index, col) for col in range(9)]
            if constraint["line"] == "row"
            else [(row, index) for row in range(9)]
        )
        values = [value(example["solution"], c) for c in line_cells]
        left, right = sorted((values.index(1), values.index(9)))
        self.assertGreater(right - left, 1)
        target_cell = line_cells[left + 1]
        original = values[left + 1]
        replacement = next(v for v in range(2, 9) if v != original)
        case = payload(example)
        case["actual_solution"] = set_value(example["solution"], target_cell, replacement)
        self.assertIn("sandwich", rules(validate_payload(case)))

    def test_adjacent_sandwich_sum_is_zero(self) -> None:
        solution = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"
        case = {
            "title": "adjacent sandwich",
            "givens": "." * 81,
            "constraints": [{"type": "sandwich", "line": "row", "index": 0, "sum": 0}],
            "actual_solution": solution,
        }
        self.assertEqual(validate_payload(case)["status"], STATUS_CORRECT)

    def test_alldiff_and_zero_based_coordinates(self) -> None:
        solution = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"
        case = {
            "givens": "." * 81,
            "constraints": [{"type": "alldiff", "cells": [[0, 0], [0, 1], [0, 2]]}],
            "actual_solution": set_value(solution, [0, 0], value(solution, [0, 1])),
        }
        self.assertIn("alldiff", rules(validate_payload(case)))

    def test_parity_and_greaterthan(self) -> None:
        solution = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"
        parity_case = {
            "givens": "." * 81,
            "constraints": [{"type": "parity", "cells": ["r1c1"], "even": True}],
            "actual_solution": solution,
        }
        self.assertIn("parity.even", rules(validate_payload(parity_case)))

        greater_case = {
            "givens": "." * 81,
            "constraints": [{"type": "greaterthan", "left": "r1c2", "right": "r1c1"}],
            "actual_solution": solution,  # 3 > 5는 거짓
        }
        self.assertIn("greaterthan", rules(validate_payload(greater_case)))

    def test_unknown_type_is_unverifiable(self) -> None:
        example = load_example("01_x_sudoku.json")
        case = payload(example)
        case["constraints"] = [{"type": "unknown_rule"}]
        report = validate_payload(case)
        self.assertEqual(report["status"], STATUS_UNVERIFIABLE)
        self.assertTrue(report["unverifiable_reasons"])

    def test_invalid_grid_is_unverifiable(self) -> None:
        report = validate_payload({"givens": "." * 81, "constraints": [], "actual_solution": "123"})
        self.assertEqual(report["status"], STATUS_UNVERIFIABLE)

    # ---- 리뷰 후 추가: 조용히 "정답"이 되던 경우 -------------------------------

    def test_missing_constraints_key_is_unverifiable(self) -> None:
        report = validate_payload({"givens": "." * 81, "actual_solution": SOLUTION})
        self.assertEqual(report["status"], STATUS_UNVERIFIABLE)
        # 클래식만인 퍼즐은 빈 배열을 명시하면 정답이다.
        report = validate_payload({"givens": "." * 81, "constraints": [], "actual_solution": SOLUTION})
        self.assertEqual(report["status"], STATUS_CORRECT)

    def test_unsupported_rules_make_result_unverifiable(self) -> None:
        for unsupported in (["흰 점: r1c1-r1c2"], "정보 부족: 화살표 위치", True):
            with self.subTest(unsupported=unsupported):
                report = validate_payload({
                    "givens": "." * 81,
                    "constraints": [],
                    "unsupported": unsupported,
                    "actual_solution": SOLUTION,
                })
                self.assertEqual(report["status"], STATUS_UNVERIFIABLE)
                self.assertIn("unsupported", {i["rule"] for i in report["unverifiable_reasons"]})
        for empty in ([], False, None, ""):
            with self.subTest(unsupported=empty):
                report = validate_payload({
                    "givens": "." * 81, "constraints": [], "unsupported": empty, "actual_solution": SOLUTION,
                })
                self.assertEqual(report["status"], STATUS_CORRECT)

    # ---- 판정 우선순위: 위반이 확인되면 판정 불가보다 우선 -------------------------

    def test_violation_wins_over_unknown_rule(self) -> None:
        broken = set_value(SOLUTION, "r1c1", value(SOLUTION, "r1c2"))  # 1행 중복
        report = validate_payload({
            "givens": "." * 81,
            "constraints": [{"type": "white_dot", "cells": ["r1c1", "r1c2"]}],
            "actual_solution": broken,
        })
        self.assertEqual(report["status"], STATUS_VIOLATION)
        self.assertTrue(report["unverifiable_reasons"], "검사 못 한 규칙도 함께 보고해야 한다")

    def test_sandwich_without_single_bounds_is_violation(self) -> None:
        # 1행에 1이 두 번: 형식 오류가 아니라 격자의 위반이다.
        row1_one = SOLUTION[:9].index("1")
        broken = set_value(SOLUTION, [0, (row1_one + 1) % 9], 1)
        report = validate_payload({
            "givens": "." * 81,
            "constraints": [{"type": "sandwich", "line": "row", "index": 0, "sum": 0}],
            "actual_solution": broken,
        })
        self.assertEqual(report["status"], STATUS_VIOLATION)
        self.assertIn("sandwich.bounds", rules(report))
        self.assertFalse(report["unverifiable_reasons"])

    # ---- 값 해석: 추측하지 않기 ------------------------------------------------

    def test_parity_string_false_means_odd(self) -> None:
        # r1c1 = 5(홀수). bool("false")는 True라서 예전에는 '짝수'로 검사했다.
        for raw in ("false", "odd", False, 0):
            with self.subTest(even=raw):
                report = validate_payload({
                    "givens": "." * 81,
                    "constraints": [{"type": "parity", "cells": ["r1c1"], "even": raw}],
                    "actual_solution": SOLUTION,
                })
                self.assertEqual(report["status"], STATUS_CORRECT)

    def test_parity_without_value_or_with_garbage_is_unverifiable(self) -> None:
        for constraint in (
            {"type": "parity", "cells": ["r1c1"]},
            {"type": "parity", "cells": ["r1c1"], "even": "maybe"},
        ):
            with self.subTest(constraint=constraint):
                report = validate_payload({
                    "givens": "." * 81, "constraints": [constraint], "actual_solution": SOLUTION,
                })
                self.assertEqual(report["status"], STATUS_UNVERIFIABLE)

    def test_non_integer_sum_is_unverifiable(self) -> None:
        # 1행 앞 세 칸 합은 5+3+4 = 12. 예전에는 12.9를 12로 잘라 정답이 됐다.
        for raw_sum in (12.9, "12.9", "열둘", True):
            with self.subTest(sum=raw_sum):
                report = validate_payload({
                    "givens": "." * 81,
                    "constraints": [{"type": "killer", "cells": ["r1c1", "r1c2", "r1c3"], "sum": raw_sum}],
                    "actual_solution": SOLUTION,
                })
                self.assertEqual(report["status"], STATUS_UNVERIFIABLE)
        for raw_sum in (12, 12.0, "12"):
            with self.subTest(sum=raw_sum):
                report = validate_payload({
                    "givens": "." * 81,
                    "constraints": [{"type": "killer", "cells": ["r1c1", "r1c2", "r1c3"], "sum": raw_sum}],
                    "actual_solution": SOLUTION,
                })
                self.assertEqual(report["status"], STATUS_CORRECT)

    def test_degenerate_constraints_are_unverifiable(self) -> None:
        for constraint in (
            {"type": "arrow", "circle": "r1c1", "path": ["r1c1"]},
            {"type": "thermo", "path": ["r1c1"]},
            {"type": "lessthan", "smaller": "r1c1", "larger": "r1c1"},
            {"type": "sandwich", "line": "row", "index": 0, "sum": 0, "low": 5, "high": 5},
        ):
            with self.subTest(constraint=constraint):
                report = validate_payload({
                    "givens": "." * 81, "constraints": [constraint], "actual_solution": SOLUTION,
                })
                self.assertEqual(report["status"], STATUS_UNVERIFIABLE)

    # ---- 명세 형식 호환: 엔진이 받는 표기는 검사기도 받는다 ----------------------------

    def test_type_aliases_and_kind_key(self) -> None:
        for constraint in (
            {"type": "thermometer", "path": ["r1c2", "r1c1"]},  # 3 < 5
            {"type": "x_sudoku"},
            {"kind": "cage", "cells": ["r1c1", "r1c2"], "sum": 8},
            {"name": "less_than", "smaller": "r1c2", "larger": "r1c1"},
        ):
            with self.subTest(constraint=constraint):
                report = validate_payload({
                    "givens": "." * 81, "constraints": [constraint], "actual_solution": X_SOLUTION
                    if constraint.get("type") == "x_sudoku" else SOLUTION,
                })
                self.assertEqual(report["status"], STATUS_CORRECT, report)

    def test_nested_givens_and_sandwich_orientation(self) -> None:
        givens = [[0] * 9 for _ in range(9)]
        givens[0][0] = 5
        report = validate_payload({
            "givens": givens,
            "constraints": [{"type": "sandwich", "orientation": "row", "index": 0, "sum": 0}],
            "actual_solution": SOLUTION,  # 1행 ...912: 9와 1이 붙어 있어 합 0
        })
        self.assertEqual(report["status"], STATUS_CORRECT, report)
        givens[0][0] = 6
        report = validate_payload({"givens": givens, "constraints": [], "actual_solution": SOLUTION})
        self.assertIn("given", rules(report))


if __name__ == "__main__":
    unittest.main(verbosity=2)
