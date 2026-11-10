"""파싱 정확도 측정.

    cd parser
    python -m llm_parser.evaluate --client oracle                   # 채점기 자체 점검 (100%여야 정상)
    python -m llm_parser.evaluate --client noisy                    # 재시도 루프 점검 (가짜 LLM이 일부러 틀림)
    python -m llm_parser.evaluate --client gemini --sleep 6         # 무료 등급 (GEMINI_API_KEY)
    python -m llm_parser.evaluate --client anthropic --repeat 3     # 같은 데이터로 3회 반복
    python -m llm_parser.evaluate --client gemini --list-models     # 내 키로 쓸 수 있는 모델 이름
    python -m llm_parser.evaluate --client openai --price-in 0.15 --price-out 0.6   # 예상 비용(USD/100만 토큰)

데이터 분리 (3-1)
  --split test (기본) : data/rules_test.jsonl — 최종 보고용. few-shot과 겹치지 않음
  --split dev         : data/rules_dev.jsonl  — 프롬프트를 고칠 때만 사용
  --split all         : 둘 다
  프롬프트를 고치면서 test 결과를 보고 다시 고치면 test가 dev가 된다. 최종 보고 직전에만 test를 돌릴 것.

결과: results/<모델>_<시각>.jsonl (반복·문장별 원문 출력, 시도별 단계·사유·토큰·지연, API 오류)
      results/<모델>_<시각>_summary.json (반복별 지표 + 평균·표준편차)
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from . import parse_rules
from .canonical import canonical_items, compare, safe_canonical
from .checks import OutputFormatError, extract_givens, extract_json, split_output
from .clients import STOP_KINDS, LLMAPIError, LLMClient, ScriptedClient, Throttled, make_client

HERE = Path(__file__).resolve().parent.parent
DATA_DIR = HERE / "data"
SPLITS = {"dev": ["rules_dev.jsonl"], "test": ["rules_test.jsonl"], "all": ["rules_dev.jsonl", "rules_test.jsonl"],
          "nl": []}
NL_PROMPTS = HERE.parent / "puzzles" / "nl_prompts.jsonl"


def load_nl_prompts(path: Path = NL_PROMPTS) -> list[dict]:
    """④-A가 만든 자연어 퍼즐 설명(datagen/nl_prompts.py)을 평가 항목으로 바꾼다.

    ③이 직접 쓰지 않은 문장이라 독립 평가 세트로 쓴다. 단서 격자는 문장 안에 있지만
    LLM이 아니라 코드(extract_givens)가 꺼내므로, 파싱 정확도는 constraints만 비교한다.
    """
    items: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            style = r.get("style", {})
            items.append({
                "id": r["id"], "text": r["text"],
                "gold": {"constraints": r["spec"]["constraints"], "unsupported": False},
                "tags": list(r.get("variant", [])) + [f"coord_{style.get('coord', '?')}",
                                                      f"grid_{style.get('grid', '?')}", "nl4a"],
                "givens": r["spec"].get("givens"), "author": "④-A",
            })
    return items


def load_dataset(split: str = "test", data_dir: Path = DATA_DIR) -> list[dict]:
    if split == "nl":
        return load_nl_prompts()
    rows: list[dict] = []
    for name in SPLITS[split]:
        with open(data_dir / name, encoding="utf-8") as f:
            rows.extend(json.loads(line) for line in f if line.strip())
    return rows


def gold_as_output(item: dict) -> dict:
    """정답 명세를 LLM 출력 형식으로 바꾼다."""
    return {
        "constraints": item["gold"]["constraints"],
        "unsupported": ["(지원하지 않거나 정보가 부족한 규칙)"] if item["gold"]["unsupported"] else [],
    }


# ---------------------------------------------------------------- 가짜 LLM

def oracle_client(data: list[dict]) -> ScriptedClient:
    by_text = {d["text"]: gold_as_output(d) for d in data}
    return ScriptedClient(lambda text, _a: json.dumps(by_text[text], ensure_ascii=False), "oracle")


def _typo_cell(c) -> str:
    """"r1c1" 또는 [0, 0] → "R1-C1" (LLM이 낼 법한 좌표 표기 오타)."""
    if isinstance(c, str):
        return c.replace("r", "R").replace("c", "-C")
    if isinstance(c, dict):
        c = [c.get("row", c.get("r")), c.get("col", c.get("c"))]
    return f"R{int(c[0]) + 1}-C{int(c[1]) + 1}"


def _corrupt(output: dict, kind: str) -> str:
    """LLM이 실제로 낼 법한 실수를 흉내 낸다."""
    cons = json.loads(json.dumps(output["constraints"]))
    if kind == "broken_json":
        return "다음은 결과입니다:\n```json\n" + json.dumps(output, ensure_ascii=False)[:-2] + "\n```"
    if kind == "api_empty":
        raise LLMAPIError("empty")
    if kind == "bad_type" and cons:
        cons[0]["type"] = "unicorn"
    elif kind == "cell_typo" and cons:
        for key in ("cells", "path"):
            if key in cons[0]:
                cons[0][key] = [_typo_cell(c) for c in cons[0][key]]
                break
        else:
            return "{'constraints': 작은따옴표}"
    elif kind == "silent_flip":
        # 검증을 통과해 버리는 실수: 부등호 방향 반대 / 합 1 차이
        for c in cons:
            if c.get("type") == "lessthan":
                c["smaller"], c["larger"] = c["larger"], c["smaller"]
                break
            if c.get("type") == "killer":
                c["sum"] += 1
                break
    return json.dumps({"constraints": cons, "unsupported": output["unsupported"]}, ensure_ascii=False)


NOISE_KINDS = ["broken_json", "bad_type", "cell_typo", "silent_flip", "api_empty", "none"]


def noisy_client(data: list[dict]) -> ScriptedClient:
    """문장마다 첫 시도에 한 종류의 실수(빈 응답 포함)를 하고, 재시도에서 정답을 낸다.
    silent_flip은 검증을 통과하므로 재시도 기회 없이 오답으로 남는다(의도된 동작)."""
    plan = {d["text"]: (gold_as_output(d), NOISE_KINDS[i % len(NOISE_KINDS)]) for i, d in enumerate(data)}

    def respond(text: str, attempt: int) -> str:
        out, kind = plan[text]
        if attempt == 0 and kind != "none":
            return _corrupt(out, kind)
        return json.dumps(out, ensure_ascii=False)

    return ScriptedClient(respond, "noisy")


# ---------------------------------------------------------------- 평가

def _first_attempt_correct(result, item: dict) -> bool:
    """첫 시도 출력만 봤을 때 정답이었는가(재시도 효과를 정답률로 보기 위함)."""
    first = result.attempts[0]
    if first.stage == "api":
        return False
    try:
        spec, unsupported = split_output(extract_json(first.raw_output))
    except OutputFormatError:
        return False
    cmp = compare(safe_canonical(spec), canonical_items(item["gold"]))
    return cmp["exact"] and bool(unsupported) == item["gold"]["unsupported"]


def evaluate(
    data: list[dict], client: LLMClient, max_attempts: int = 3, strict: bool = True,
    rows: list[dict] | None = None, progress: bool = False, run_index: int = 1, run_started_at: str = "",
) -> tuple[list[dict], dict]:
    """rows를 넘기면 거기에 문장별 결과를 채운다(중간에 멈춰도 그때까지 결과를 저장할 수 있게)."""
    rows = [] if rows is None else rows
    start = len(rows)
    for k, item in enumerate(data, 1):
        if progress:
            print(f"  [{k}/{len(data)}] {item['id']} ...", end="", flush=True)
        t0 = time.perf_counter()
        result = parse_rules(item["text"], client, max_attempts=max_attempts, strict=strict)
        gold = canonical_items(item["gold"])
        pred = safe_canonical(result.spec) if result.status in ("ok", "unsupported") else None
        cmp = compare(pred, gold)
        unsup_ok = bool(result.unsupported) == item["gold"]["unsupported"] and result.status != "api_error"
        tokens_in = sum(a.input_tokens or 0 for a in result.attempts)
        tokens_out = sum(a.output_tokens or 0 for a in result.attempts)
        rows.append({
            "model": client.name,
            "run_index": run_index,
            "run_started_at": run_started_at,
            "id": item["id"],
            "text": item["text"],
            "tags": item["tags"],
            "status": result.status,
            "error": result.error,
            "calls": result.n_attempts,
            "first_validation_pass": result.attempts[0].stage == "",
            "final_validation_pass": result.status in ("ok", "unsupported"),
            "first_exact": _first_attempt_correct(result, item),
            "attempts": [asdict(a) for a in result.attempts],
            "spec": result.spec,
            "unsupported": result.unsupported,
            "unsupported_ok": unsup_ok,
            **cmp,
            "exact": cmp["exact"] and unsup_ok,
            "latency": round(time.perf_counter() - t0, 3),
            # 문장 안 단서 격자를 코드가 정확히 꺼냈는지 (nl 세트처럼 정답 단서가 있을 때만)
            "givens_ok": (extract_givens(item["text"]) == item["givens"]) if item.get("givens") else None,
            "input_tokens": tokens_in or None,
            "output_tokens": tokens_out or None,
        })
        if progress:
            r = rows[-1]
            mark = "정답" if r["exact"] else ("API 오류" if r["status"] == "api_error" else "오답")
            print(f" {mark} (호출 {r['calls']}회, {r['latency']:.1f}초)")
        if result.status == "api_error" and result.error and result.error["kind"] in STOP_KINDS:
            # 키·크레딧·일일 한도 문제는 다음 문장에서도 똑같이 실패하므로 즉시 중단
            raise LLMAPIError(result.error["kind"], result.error.get("detail") or result.error["message"])
    return rows, summarize(rows[start:])


def summarize(rows: list[dict], price_in: float | None = None, price_out: float | None = None) -> dict:
    n = len(rows)
    tp, fp, fn = (sum(r[k] for r in rows) for k in ("tp", "fp", "fn"))
    p = tp / (tp + fp) if tp + fp else 1.0
    rc = tp / (tp + fn) if tp + fn else 1.0
    by_tag: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        for t in r["tags"]:
            by_tag[t].append(r["exact"])
    tin = sum(r["input_tokens"] or 0 for r in rows)
    tout = sum(r["output_tokens"] or 0 for r in rows)
    calls = sum(r["calls"] for r in rows)
    cost = None
    if price_in is not None and price_out is not None and (tin or tout):
        cost = round(tin / 1e6 * price_in + tout / 1e6 * price_out, 4)
    gv = [r["givens_ok"] for r in rows if r.get("givens_ok") is not None]
    return {
        "n": n,
        "givens_extract_acc": (sum(gv) / len(gv)) if gv else None,          # 단서 격자 코드 추출 정확도
        "exact": sum(r["exact"] for r in rows) / n,                         # 최종 정답률
        "first_exact": sum(r["first_exact"] for r in rows) / n,             # 첫 시도 정답률
        "precision": p,
        "recall": rc,
        "f1": 2 * p * rc / (p + rc) if p + rc else 0.0,
        "first_validation_pass": sum(r["first_validation_pass"] for r in rows) / n,
        "final_validation_pass": sum(r["final_validation_pass"] for r in rows) / n,  # 검증 통과율 ≠ 정답률
        "unsupported_acc": sum(r["unsupported_ok"] for r in rows) / n,
        "avg_calls": calls / n,
        "avg_latency": sum(r["latency"] for r in rows) / n,
        "api_errors": sum(r["status"] == "api_error" for r in rows),
        "api_error_kinds": dict(Counter(r["error"]["kind"] for r in rows if r["error"])),
        "input_tokens": tin or None,
        "output_tokens": tout or None,
        "est_cost_usd": cost,
        "status": dict(Counter(r["status"] for r in rows)),
        "reject_stages": dict(Counter(a["stage"] for r in rows for a in r["attempts"] if a["stage"])),
        "exact_by_tag": {t: f"{sum(v)}/{len(v)}" for t, v in sorted(by_tag.items())},
        "wrong_ids": [r["id"] for r in rows if not r["exact"]],
    }


AGG_KEYS = ["exact", "first_exact", "f1", "first_validation_pass", "final_validation_pass",
            "unsupported_acc", "avg_calls", "avg_latency"]


def aggregate(runs: list[dict]) -> dict:
    out = {}
    for k in AGG_KEYS:
        vals = [r[k] for r in runs]
        out[k] = {"mean": statistics.mean(vals), "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0}
    return out


def format_summary(s: dict, name: str) -> str:
    tok = (f"{s['input_tokens']:,} / {s['output_tokens']:,}" if s["input_tokens"] else "기록 없음(가짜 LLM)")
    cost = f"${s['est_cost_usd']}" if s["est_cost_usd"] is not None else "—(--price-in/--price-out 지정 시 계산)"
    lines = [
        f"### 파싱 평가 — {name} (문장 {s['n']}개)",
        "",
        "| 지표 | 값 |",
        "|---|---|",
        f"| 최종 정답률 (문장 완전일치) | {s['exact']:.1%} |",
        f"| 첫 시도 정답률 | {s['first_exact']:.1%} |",
        f"| 제약 P / R / F1 | {s['precision']:.1%} / {s['recall']:.1%} / {s['f1']:.1%} |",
        f"| 첫 시도 검증 통과율 | {s['first_validation_pass']:.1%} |",
        f"| 최종 검증 통과율 (≠ 정답률) | {s['final_validation_pass']:.1%} |",
        f"| unsupported 판별 정확도 | {s['unsupported_acc']:.1%} |",
        f"| 평균 API 호출 / 문장 | {s['avg_calls']:.2f} |",
        f"| 평균 응답 시간 / 문장 | {s['avg_latency']:.2f}초 |",
        f"| API 오류 | {s['api_errors']}건 {s['api_error_kinds'] or ''} |",
        f"| 토큰 입력 / 출력 | {tok} |",
        *([f"| 단서 격자 추출(코드) | {s['givens_extract_acc']:.1%} |"] if s.get("givens_extract_acc") is not None else []),
        f"| 예상 비용 | {cost} |",
        "",
        f"거부 단계: {s['reject_stages'] or '없음'}",
        f"태그별 정답: {s['exact_by_tag']}",
        f"틀린 문장: {', '.join(s['wrong_ids']) or '없음'}",
    ]
    return "\n".join(lines)


def format_aggregate(agg: dict, n_runs: int) -> str:
    names = {"exact": "최종 정답률", "first_exact": "첫 시도 정답률", "f1": "제약 F1",
             "first_validation_pass": "첫 시도 검증 통과율", "final_validation_pass": "최종 검증 통과율",
             "unsupported_acc": "unsupported 판별", "avg_calls": "평균 호출", "avg_latency": "평균 응답 시간(초)"}
    lines = [f"### {n_runs}회 반복 평균 ± 표준편차", "", "| 지표 | 값 |", "|---|---|"]
    for k in AGG_KEYS:
        m, sd = agg[k]["mean"], agg[k]["stdev"]
        if k in ("avg_calls", "avg_latency"):
            lines.append(f"| {names[k]} | {m:.2f} ± {sd:.2f} |")
        else:
            lines.append(f"| {names[k]} | {m:.1%} ± {sd:.1%} |")
    return "\n".join(lines)


def _save(rows: list[dict], summary: dict | None, out_dir: str, name: str, stamp: str, split: str = "") -> Path:
    """파일 이름: <split>_<모델>[_partial]_<시각>.jsonl  예) test_gemini-3.5-flash_partial_20261110-171002.jsonl"""
    os.makedirs(out_dir, exist_ok=True)
    model = name.split(":")[-1].replace("/", "_")
    tag = (f"{split}_" if split else "") + model + ("" if summary else "_partial")
    path = Path(out_dir) / f"{tag}_{stamp}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if summary:
        with open(Path(out_dir) / f"{tag}_{stamp}_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    return path


def _load_resume(path: str, model: str, ids: set[str]) -> tuple[list[dict], set[tuple[int, str]]]:
    """멈춘 결과 파일에서 정상 완료된 문장만 가져온다(API 오류로 끝난 문장은 다시 측정)."""
    prev = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    prev = [r for r in prev if "run_index" in r and "id" in r]
    models = {r["model"] for r in prev}
    if models and models != {model}:
        raise ValueError(f"결과 파일의 모델 {sorted(models)}과 지금 모델 '{model}'이 다릅니다. "
                         "같은 모델로만 이어서 측정할 수 있습니다(SUDOKU_LLM_MODEL 또는 --model 확인).")
    keep = [r for r in prev if r["status"] != "api_error" and r["id"] in ids]
    if prev and not keep:
        raise ValueError("이어서 쓸 결과가 없습니다(분할(--split)이 다르거나 모두 API 오류).")
    return keep, {(r["run_index"], r["id"]) for r in keep}


def _preflight(client: LLMClient) -> None:
    """측정 전에 한 번만 짧게 호출해서 키·크레딧·모델 문제를 먼저 잡는다(재시도 1회만, 오래 기다리지 않음)."""
    print(f"연결 확인 중: {client.name} ...", flush=True)
    inner = getattr(client, "inner", client)
    saved = getattr(inner, "max_retries", 5)
    inner.max_retries = 1
    try:
        client.complete("JSON 객체 {} 하나만 출력하세요.", [{"role": "user", "content": "ping"}])
    except LLMAPIError as exc:
        if exc.kind in ("server", "rate_limit", "network"):
            raise LLMAPIError(exc.kind, f"{exc.detail} — 원인 확인: python -m llm_parser.evaluate "
                                        f"--client gemini --diagnose  (다른 모델: --model 이름)") from exc
        raise
    finally:
        inner.max_retries = saved
    print("연결 확인 완료. 측정을 시작합니다.\n")


def _diagnose(model: str | None) -> int:
    """Gemini 연결 문제를 한 번에 확인한다. 키 전체는 출력하지 않는다."""
    import os

    from .clients import GEMINI_NATIVE_URL, GeminiNativeClient

    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    print("== 1. 키")
    if not key:
        print("  GEMINI_API_KEY 환경변수가 없습니다.")
        return 1
    print(f"  앞부분 {key[:3]}…  길이 {len(key)}  공백 포함 {any(ch.isspace() for ch in key)}")
    client = GeminiNativeClient(model, json_mode=False)
    print(f"== 2. 모델 목록 ({GEMINI_NATIVE_URL}/models)")
    try:
        names = client.list_models()
        flash = [n for n in names if "flash" in n]
        print(f"  {len(names)}개. flash 계열: {', '.join(flash[:12]) or '없음'}")
        print(f"  지정 모델 '{client.model}' 목록에 있음: {client.model in names}")
    except Exception as exc:  # noqa: BLE001
        print(f"  실패: {type(exc).__name__} {getattr(exc, 'status_code', '')} {exc}")
    for label, json_mode in (("일반 텍스트", False), ("JSON 모드", True)):
        print(f"== 3. 짧은 요청 — {label} (모델 {client.model}, 재시도 없음)")
        payload = {"contents": [{"role": "user", "parts": [{"text": "ping이라고만 답하세요."}]}]}
        if json_mode:
            payload["systemInstruction"] = {"parts": [{"text": "JSON 객체 하나만 출력하세요."}]}
            payload["generationConfig"] = {"responseMimeType": "application/json"}
        try:
            data = client._request("POST", f"models/{client.model}:generateContent", payload)
            cand = (data.get("candidates") or [{}])[0]
            text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
            print(f"  성공 — finishReason={cand.get('finishReason')} 응답={text[:60]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"  실패: HTTP {getattr(exc, 'status_code', '?')} — {' '.join(str(exc).split())[:300]}")
    print("\n위 출력 전체를 그대로 공유하면 원인을 찾을 수 있습니다(키 전체는 출력되지 않음).")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LLM 파서 정확도 측정")
    ap.add_argument("--client", default="oracle", choices=["oracle", "noisy", "anthropic", "openai", "gemini", "gemini-openai"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--split", default="test", choices=list(SPLITS))
    ap.add_argument("--repeat", type=int, default=1, help="같은 데이터로 반복 측정할 횟수 (실제 LLM은 2~3 권장)")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--no-strict", action="store_true", help="그럴듯함 검사 끄기 (비교 실험용)")
    ap.add_argument("--sleep", type=float, default=0.0, help="LLM 호출 사이 최소 간격(초). 무료 등급이면 4~6 권장")
    ap.add_argument("--price-in", type=float, default=None, help="입력 토큰 가격 (USD / 100만 토큰)")
    ap.add_argument("--price-out", type=float, default=None, help="출력 토큰 가격 (USD / 100만 토큰)")
    ap.add_argument("--list-models", action="store_true", help="이 키로 쓸 수 있는 모델 이름을 보여주고 끝냄")
    ap.add_argument("--diagnose", action="store_true", help="Gemini 연결 진단(키 형식·모델 목록·짧은 요청)")
    ap.add_argument("--resume", default=None,
                    help="중간에 멈춘 결과 파일(*_partial.jsonl). 이미 끝난 문장은 다시 호출하지 않고 이어서 측정")
    ap.add_argument("--out", default=str(HERE / "results"))
    args = ap.parse_args(argv)
    if args.max_attempts < 1 or args.repeat < 1:
        ap.error("--max-attempts와 --repeat는 1 이상이어야 합니다")

    if args.diagnose:
        return _diagnose(args.model)
    data = load_dataset(args.split)
    real = args.client not in ("oracle", "noisy")
    try:
        if args.client == "oracle":
            client: LLMClient = oracle_client(data)
        elif args.client == "noisy":
            client = noisy_client(data)
        else:
            client = make_client(args.client, args.model)
            if args.list_models:
                names = client.list_models() if hasattr(client, "list_models") \
                    else sorted(m.id for m in client._client.models.list())
                print("\n".join(names))
                return 0
            if args.sleep > 0:
                client = Throttled(client, args.sleep)
            _preflight(client)
    except LLMAPIError as exc:
        print(f"\n[API 오류] {exc}")
        return 1

    stamp = time.strftime("%Y%m%d-%H%M%S")
    rows: list[dict] = []
    runs: list[dict] = []
    done: set[tuple[int, str]] = set()
    if args.resume:
        try:
            rows, done = _load_resume(args.resume, client.name, {d["id"] for d in data})
        except ValueError as exc:
            print(f"[이어서 측정 불가] {exc}")
            return 1
        print(f"이어서 측정: 이미 끝난 {len(done)}문장은 건너뜁니다 (API 오류로 끝난 문장은 다시 시도).")
    try:
        for i in range(1, args.repeat + 1):
            if args.repeat > 1:
                print(f"\n=== 반복 {i}/{args.repeat} ===")
            started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            todo = [d for d in data if (i, d["id"]) not in done]
            if len(todo) < len(data):
                print(f"  반복 {i}: {len(data) - len(todo)}문장 완료됨, {len(todo)}문장 남음")
            run_rows, _ = evaluate(todo, client, args.max_attempts, strict=not args.no_strict,
                                   rows=rows, progress=real, run_index=i, run_started_at=started)
            run_slice = [r for r in rows if r["run_index"] == i]
            s = summarize(run_slice, args.price_in, args.price_out)
            s.update({"run_index": i, "run_started_at": started, "model": client.name, "split": args.split})
            runs.append(s)
            print(format_summary(s, f"{client.name} · {args.split} · 반복 {i}"))
    except LLMAPIError as exc:
        print(f"\n\n[중단 — API 오류] {exc}")
        if rows:
            print(f"그때까지 {len(rows)}문장 결과를 저장했습니다: {_save(rows, None, args.out, client.name, stamp, args.split)}")
        return 1
    except KeyboardInterrupt:
        print("\n\n[중단 — 사용자]")
        if rows:
            print(f"그때까지 {len(rows)}문장 결과를 저장했습니다: {_save(rows, None, args.out, client.name, stamp, args.split)}")
        return 130

    summary = {"model": client.name, "split": args.split, "repeat": args.repeat, "runs": runs}
    if args.repeat > 1:
        summary["aggregate"] = aggregate(runs)
        print("\n" + format_aggregate(summary["aggregate"], args.repeat))
    path = _save(rows, summary, args.out, client.name, stamp, args.split)
    print(f"\n결과 저장: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
