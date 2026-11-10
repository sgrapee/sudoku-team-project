"""파싱 실패 케이스 수집·분류 — evaluate 결과 JSONL → 오류 유형별 리포트(마크다운 + CSV).

    cd parser
    python -m llm_parser.evaluate --client noisy                       # results/noisy_<시각>.jsonl 생성
    python -m llm_parser.failures results/noisy_<시각>.jsonl           # 화면에 리포트
    python -m llm_parser.failures results/....jsonl --md report.md --csv failures.csv

정답 명세와 비교해 틀린 문장마다 원인을 이름 붙인다(한 문장에 여러 개일 수 있음).

  부등호 방향 반전 / 온도계 방향 반전 / 짝·홀 반전
  합 오류(킬러·샌드위치·화살표 원 위치는 같고 값만 다름)
  좌표 1칸 밀림(같은 모양이 행·열로 ±1 이동 — 0/1 인덱스 혼동의 흔적)
  샌드위치 줄 번호 ±1 / 샌드위치 행·열 혼동
  대각선 하나·둘 혼동(diagonal ↔ 9칸 alldiff)
  제약 누락: <종류> / 제약 추가(환각): <종류>
  미지원·정보 부족을 놓침(억지 변환) / 지원 규칙을 미지원 처리
  검증 실패: <마지막 거부 단계> / API 오류: <종류>

재시도로 결국 맞혔더라도 중간에 거부된 시도는 '복구된 오류'로 따로 집계한다(④ 실패 사례 분석용).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import Counter
from pathlib import Path

from .canonical import canonical_items, safe_canonical
from .evaluate import load_dataset

KIND_NAMES = {"killer": "킬러", "thermo": "온도계", "arrow": "화살표", "sandwich": "샌드위치",
              "alldiff": "alldiff", "parity": "짝·홀", "lessthan": "부등호", "diagonal": "대각선"}
DIAG_MAIN = frozenset((i, i) for i in range(9))
DIAG_ANTI = frozenset((i, 8 - i) for i in range(9))


def _cells(item: tuple) -> tuple[list, tuple]:
    """(칸 목록, 칸이 아닌 속성) — 좌표 밀림 비교용."""
    kind = item[0]
    if kind == "killer":
        return sorted(item[1]), (item[2],)
    if kind == "thermo":
        return list(item[1]), ()
    if kind == "arrow":
        return [item[1]] + sorted(item[2]), ()
    if kind in ("alldiff",):
        return sorted(item[1]), ()
    if kind == "sandwich":
        return sorted(item[1]), (item[2],)
    if kind == "parity":
        return [item[1]], (item[2],)
    if kind == "lessthan":
        return [item[1], item[2]], ()
    return [], item[1:]


def _shifted(a: tuple, b: tuple) -> bool:
    ca, ra = _cells(a)
    cb, rb = _cells(b)
    if a[0] != b[0] or ra != rb or not ca or len(ca) != len(cb):
        return False
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if (dr or dc) and [(r + dr, c + dc) for r, c in ca] == cb:
                return True
            if (dr or dc) and sorted((r + dr, c + dc) for r, c in ca) == sorted(cb) and a[0] not in ("thermo", "lessthan"):
                return True
    return False


def _line_kind(cells: frozenset) -> tuple[str, int] | None:
    rows = {r for r, _ in cells}
    cols = {c for _, c in cells}
    if len(rows) == 1:
        return "row", next(iter(rows))
    if len(cols) == 1:
        return "col", next(iter(cols))
    return None


def classify_spec_errors(pred: Counter, gold: Counter) -> list[str]:
    missing = list((gold - pred).elements())
    extra = list((pred - gold).elements())
    cats: list[str] = []

    def take(pred_fn, label) -> None:
        for m in list(missing):
            for e in list(extra):
                if pred_fn(m, e):
                    cats.append(label(m) if callable(label) else label)
                    missing.remove(m)
                    extra.remove(e)
                    break

    take(lambda m, e: m[0] == e[0] == "lessthan" and (m[1], m[2]) == (e[2], e[1]), "부등호 방향 반전")
    take(lambda m, e: m[0] == e[0] == "thermo" and m[1] == tuple(reversed(e[1])), "온도계 방향 반전")
    take(lambda m, e: m[0] == e[0] == "parity" and m[1] == e[1] and m[2] != e[2], "짝·홀 반전")
    take(lambda m, e: m[0] == e[0] in ("killer", "sandwich") and m[1] == e[1] and m[2] != e[2], "합 오류")
    take(lambda m, e: m[0] == e[0] == "arrow" and m[2] == e[2] and m[1] != e[1], "화살표 원 위치 오류")

    def sandwich_line(m, e, rule):
        if not (m[0] == e[0] == "sandwich" and m[2] == e[2]):
            return False
        lm, le = _line_kind(m[1]), _line_kind(e[1])
        return bool(lm and le and rule(lm, le))

    take(lambda m, e: sandwich_line(m, e, lambda a, b: a[0] == b[0] and abs(a[1] - b[1]) == 1), "샌드위치 줄 번호 ±1")
    take(lambda m, e: sandwich_line(m, e, lambda a, b: a[0] != b[0]), "샌드위치 행·열 혼동")
    take(lambda m, e: (m[0] == "diagonal" and e[0] == "alldiff" and e[1] in (DIAG_MAIN, DIAG_ANTI))
         or (e[0] == "diagonal" and m[0] == "alldiff" and m[1] in (DIAG_MAIN, DIAG_ANTI)), "대각선 하나·둘 혼동")
    take(_shifted, "좌표 1칸 밀림")
    # 같은 종류가 하나는 빠지고 하나는 생겼는데 위 유형이 아니면 '내용 오류'로 묶는다
    take(lambda m, e: m[0] == e[0], lambda m: f"내용 오류: {KIND_NAMES.get(m[0], m[0])}")
    cats += [f"제약 누락: {KIND_NAMES.get(m[0], m[0])}" for m in missing]
    cats += [f"제약 추가(환각): {KIND_NAMES.get(e[0], e[0])}" for e in extra]
    return cats


def classify_row(row: dict, gold: dict) -> list[str]:
    if row["status"] == "api_error":
        return [f"API 오류: {(row.get('error') or {}).get('kind', 'unknown')}"]
    if row["status"] == "failed":
        last = next((a["stage"] for a in reversed(row["attempts"]) if a["stage"]), "unknown")
        return [f"검증 실패: {last}"]
    cats: list[str] = []
    pred = safe_canonical(row.get("spec")) or Counter()
    g = canonical_items(gold)
    if pred != g:
        cats += classify_spec_errors(pred, g)
    pred_uns, gold_uns = bool(row.get("unsupported")), gold["unsupported"]
    if gold_uns and not pred_uns:
        cats.append("미지원·정보 부족을 놓침(억지 변환)")
    if pred_uns and not gold_uns:
        cats.append("지원 규칙을 미지원 처리")
    return cats or ["분류 불가"]


def analyze(rows: list[dict], gold_by_id: dict[str, dict]) -> dict:
    wrong, recovered = [], Counter()
    by_cat, by_tag = Counter(), Counter()
    for r in rows:
        for a in r["attempts"]:
            if a["stage"] and r["exact"]:
                recovered[a["stage"]] += 1
        if r["exact"]:
            continue
        gold = gold_by_id[r["id"]]["gold"]
        cats = classify_row(r, gold)
        by_cat.update(cats)
        for t in r["tags"]:
            by_tag[t] += 1
        last = next((a for a in reversed(r["attempts"]) if a["stage"]), None)
        wrong.append({
            "run": r.get("run_index", 1), "id": r["id"], "text": r["text"], "tags": r["tags"],
            "status": r["status"], "categories": cats, "calls": r["calls"],
            "last_stage": last["stage"] if last else "", "last_feedback": (last["feedback"] if last else "")[:160],
            "final_output": (r["attempts"][-1]["raw_output"] if r["attempts"] else "")[:300],
        })
    return {"n_rows": len(rows), "n_wrong": len(wrong), "by_category": by_cat, "by_tag": by_tag,
            "recovered_rejections": recovered, "wrong": wrong}


def to_markdown(res: dict, source: str) -> str:
    lines = [f"## 파싱 실패 케이스 리포트 — `{source}`", "",
             f"문장 {res['n_rows']}개 중 오답 {res['n_wrong']}개", "", "### 오류 유형", "",
             "| 유형 | 건수 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in res["by_category"].most_common()] or ["| (없음) | 0 |"]
    lines += ["", "### 오답이 많이 나온 태그", "", "| 태그 | 오답 수 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in res["by_tag"].most_common()] or ["| (없음) | 0 |"]
    lines += ["", "### 재시도로 복구된 오류 (결국 정답인 문장의 중간 거부)", "", "| 거부 단계 | 횟수 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in res["recovered_rejections"].most_common()] or ["| (없음) | 0 |"]
    lines += ["", "### 오답 문장", "", "| 반복 | ID | 유형 | 문장 |", "|---|---|---|---|"]
    for w in res["wrong"]:
        text = w["text"].replace("|", "\\|")
        lines.append(f"| {w['run']} | {w['id']} | {', '.join(w['categories'])} | {text[:60]}{'…' if len(text) > 60 else ''} |")
    return "\n".join(lines)


def to_csv(res: dict) -> str:
    buf = io.StringIO()
    fields = ["run", "id", "status", "categories", "calls", "last_stage", "last_feedback", "tags", "text", "final_output"]
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for x in res["wrong"]:
        w.writerow({**{k: x[k] for k in fields if k not in ("categories", "tags")},
                    "categories": "; ".join(x["categories"]), "tags": "; ".join(x["tags"])})
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="파싱 실패 케이스 분류 리포트")
    ap.add_argument("results", help="llm_parser.evaluate가 만든 결과 JSONL")
    ap.add_argument("--md", default=None, help="마크다운 리포트 저장 경로")
    ap.add_argument("--csv", default=None, help="오답 목록 CSV 저장 경로(엑셀에서 열 때는 UTF-8 BOM 포함)")
    args = ap.parse_args(argv)

    rows = [json.loads(l) for l in Path(args.results).read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if "attempts" in r and "tp" in r]
    if not rows:
        print("evaluate 결과 파일이 아닙니다(baseline 결과는 지원하지 않음).")
        return 1
    pool = load_dataset("all")
    try:
        pool += load_dataset("nl")
    except FileNotFoundError:
        pass
    gold_by_id = {d["id"]: d for d in pool}
    missing = [r["id"] for r in rows if r["id"] not in gold_by_id]
    if missing:
        print(f"데이터셋에 없는 ID가 있습니다: {missing[:5]}")
        return 1
    res = analyze(rows, gold_by_id)
    md = to_markdown(res, Path(args.results).name)
    print(md)
    if args.md:
        Path(args.md).write_text(md + "\n", encoding="utf-8")
    if args.csv:
        Path(args.csv).write_text("﻿" + to_csv(res), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
