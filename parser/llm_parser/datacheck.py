"""팀원이 쓴 평가 문장(JSONL)을 검사하고, 문제가 없으면 dev/test 세트에 추가한다.

    cd parser
    python -m llm_parser.datacheck my_rules.jsonl                  # 검사만
    python -m llm_parser.datacheck my_rules.jsonl --append test    # 모두 통과하면 data/rules_test.jsonl 끝에 추가

한 줄 = 문장 하나:
  {"id": "K01", "text": "r2c2, r2c3 케이지의 합은 5이다.",
   "gold": {"constraints": [{"type": "killer", "cells": ["r2c2", "r2c3"], "sum": 5}], "unsupported": false},
   "tags": ["killer", "rc"], "author": "④"}

검사 항목
  오류(추가 불가): JSON 형식, 필수 키, id 중복, 같은 문장 중복, few-shot 문장과 동일,
                   정답 명세가 엔진 검증 실패, unsupported가 true/false가 아님
  경고(추가 가능): 그럴듯함 검사 경고(케이지 겹침 등), 처음 보는 태그, 제약도 unsupported도 없는데 일반 스도쿠 태그 없음
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .checks import plausibility_problems, safe_validate
from .evaluate import DATA_DIR, SPLITS, load_dataset
from .prompt import FEW_SHOTS

KNOWN_TAGS = {
    "killer", "thermo", "arrow", "sandwich", "alldiff", "parity", "inequality", "diagonal", "classic",
    "rc", "korean", "paren", "ordinal", "terse", "jargon", "multi", "unsupported", "partial_support",
    "ambiguous", "injection", "typo", "duplicate", "index_trap", "direction_trap", "diagonal_trap", "row_col_trap",
}


def check_items(items: list[dict], existing: list[dict]) -> list[tuple[str, list[str], list[str]]]:
    """[(id, 오류 목록, 경고 목록)]"""
    seen_ids = {d["id"] for d in existing}
    seen_texts = {d["text"].strip() for d in existing}
    shot_texts = {t.strip() for t, _ in FEW_SHOTS}
    out = []
    for n, d in enumerate(items, 1):
        errs: list[str] = []
        warns: list[str] = []
        did = str(d.get("id", f"(줄 {n})"))
        for key in ("id", "text", "gold", "tags"):
            if key not in d:
                errs.append(f"'{key}' 키가 없습니다")
        if errs:
            out.append((did, errs, warns))
            continue
        text = str(d["text"]).strip()
        if did in seen_ids:
            errs.append("id가 이미 있습니다")
        if text in seen_texts:
            errs.append("같은 문장이 이미 있습니다")
        if text in shot_texts:
            errs.append("few-shot 예시와 같은 문장입니다(평가가 부풀려짐)")
        gold = d["gold"]
        if not isinstance(gold, dict) or "constraints" not in gold:
            errs.append("gold에 constraints가 없습니다")
        else:
            if not isinstance(gold.get("unsupported"), bool):
                errs.append("gold.unsupported는 true 또는 false여야 합니다")
            ok, msg = safe_validate({"constraints": gold["constraints"]})
            if not ok:
                errs.append(f"정답 명세가 엔진 검증에 실패: {msg}")
            else:
                warns += [f"그럴듯함 검사: {p}" for p in plausibility_problems({"constraints": gold["constraints"]})]
            if not gold["constraints"] and not gold.get("unsupported") and "classic" not in d["tags"]:
                warns.append("제약도 unsupported도 없습니다. 일반 스도쿠 문장이면 'classic' 태그를 붙이세요")
        if not isinstance(d["tags"], list):
            errs.append("tags는 목록이어야 합니다")
        else:
            unknown = sorted(set(d["tags"]) - KNOWN_TAGS)
            if unknown:
                warns.append(f"처음 보는 태그: {unknown}")
        seen_ids.add(did)
        seen_texts.add(text)
        out.append((did, errs, warns))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="평가 문장 검사·추가")
    ap.add_argument("file", help="검사할 JSONL")
    ap.add_argument("--append", choices=["dev", "test"], default=None, help="모두 통과하면 이 세트에 추가")
    args = ap.parse_args(argv)

    items: list[dict] = []
    for n, line in enumerate(Path(args.file).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"[오류] 줄 {n}: JSON 형식이 아닙니다 — {exc.msg}")
            return 1

    report = check_items(items, load_dataset("all"))
    n_err = 0
    for did, errs, warns in report:
        status = "오류" if errs else ("경고" if warns else "통과")
        print(f"[{status}] {did}")
        for e in errs:
            print(f"    ✗ {e}")
        for w in warns:
            print(f"    △ {w}")
        n_err += bool(errs)
    print(f"\n{len(items)}문장: 통과 {len(items) - n_err}, 오류 {n_err}")

    if args.append:
        if n_err:
            print("오류가 있어 추가하지 않았습니다.")
            return 1
        target = DATA_DIR / SPLITS[args.append][0]
        with open(target, "a", encoding="utf-8") as f:
            for d in items:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        print(f"{target.name}에 {len(items)}문장을 추가했습니다.")
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
