"""LLM 연동 풀이 평가 — 자연어 퍼즐 → ③ 파서(LLM) → ② 백트래킹 / ② 지역 탐색.

LLM은 퍼즐마다 한 번만 파싱한다. 같은 명세를 두 알고리즘에 그대로 넣으므로
두 알고리즘의 차이는 파싱 품질이 아니라 탐색 방법에서만 생긴다(공정 비교 + 크레딧 절반).

    cd parser
    # 1) 점검 (LLM 호출 없음, 정답 명세를 그대로 돌려주는 가짜 LLM)
    python -m llm_parser.solver_eval --client oracle --limit 5
    # 2) 실제 실행: 파싱(크레딧 사용) + 두 알고리즘 풀이
    python -m llm_parser.solver_eval --client factchat --model gemini-3.5-flash
    # 3) 파싱 결과 재사용: 풀이 설정만 바꿔 다시 돌릴 때 (크레딧 0)
    python -m llm_parser.solver_eval --specs results/solver_specs_gemini-3.5-flash_<stamp>.jsonl --trials 5

퍼즐 (--puzzles)
  nl       : puzzles/nl_prompts.jsonl 40개 (④-A 자연어 설명, 단서 격자는 코드가 추출)
  examples : examples/ 10개 (rules_text + givens)
  all      : 둘 다 (기본, 50개)

방법 (② 엔진 기본값과 같음, benchmark.run_method_comparison 참고)
  backtracking/mrv_degree/lcv/ac3, backtracking/static/asc/none   — 결정적, 퍼즐당 1회
  min-conflicts/random/noise0.05, min-conflicts/row/noise0.05      — 무작위, 퍼즐당 --trials회(seed 변경)

지표 (방법별)
  정답률       = 정답 격자와 같은 시도 / 전체 시도   ← 핵심 지표 (파싱 실패도 실패로 센다)
  풀이 성공률   = 해를 낸 시도 / 전체 시도 (명세가 틀려도 '해'는 낼 수 있어 정답률과 구분)
  평균 시간    = 실패 시도는 time_limit으로 센 평균 (생존 편향 방지, ② 벤치마크와 같은 방식)
  정답 명세 기준 = LLM 없이 정답 명세로 같은 풀이를 돌린 결과 (알고리즘 자체의 한계)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from .baseline import EXAMPLES_DIR, PuzzleMock, _grid_str
from .canonical import canonical_items, compare, safe_canonical
from .checks import extract_givens
from .clients import STOP_KINDS, LLMAPIError, LLMClient, Throttled, make_client

REPO = Path(__file__).resolve().parents[2]
PUZZLES_DIR = REPO / "puzzles"
RESULTS = Path(__file__).resolve().parent.parent / "results"


# ---------------------------------------------------------------- 퍼즐

def _solutions_by_id() -> dict[str, str]:
    sol: dict[str, str] = {}
    for path in sorted(PUZZLES_DIR.glob("*.jsonl")):
        if path.name == "nl_prompts.jsonl":
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    if r.get("solution"):
                        sol[r["id"]] = r["solution"]
    return sol


def load_eval_puzzles(which: str = "all") -> list[dict]:
    """[{id, source, variant, tier, text, givens, gold_constraints, solution}]

    text  : LLM에게 주는 문장 그대로 (nl은 단서 격자 포함 전체 설명, examples는 rules_text)
    givens: nl은 extract_givens(text)로 코드가 꺼낸 값 — 실제 사용 흐름과 같다
    """
    items: list[dict] = []
    if which in ("nl", "all"):
        sols = _solutions_by_id()
        with open(PUZZLES_DIR / "nl_prompts.jsonl", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                items.append({
                    "id": r["id"], "source": "nl", "puzzle_id": r.get("puzzle_id"),
                    "variant": "+".join(r.get("variant", [])), "tier": r.get("tier", "?"),
                    "text": r["text"], "givens": extract_givens(r["text"]),
                    "gold_givens": r["spec"]["givens"], "gold_constraints": r["spec"]["constraints"],
                    "solution": sols.get(r.get("puzzle_id")),
                })
    if which in ("examples", "all"):
        for path in sorted(EXAMPLES_DIR.glob("*.json")):
            ex = json.loads(path.read_text(encoding="utf-8"))
            items.append({
                "id": ex["name"], "source": "examples", "puzzle_id": None,
                "variant": "+".join(sorted({c["type"] for c in ex["constraints"]})) or "classic",
                "tier": next((t for t in ("easy", "medium", "expert") if t in ex["name"]), "-"),
                "text": ex["rules_text"], "givens": ex["givens"], "gold_givens": ex["givens"],
                "gold_constraints": ex["constraints"], "solution": ex["solution"],
            })
    return items


# ---------------------------------------------------------------- 1단계: LLM 파싱 (퍼즐당 1회)

def parse_one(item: dict, client: LLMClient, max_attempts: int = 3) -> dict:
    from .parser import parse_rules

    t0 = time.perf_counter()
    row = {"id": item["id"], "givens_ok": item["givens"] == item["gold_givens"]}
    if not item["givens"]:
        row.update(status="failed", spec=None, error={"kind": "givens", "message": "단서 격자 추출 실패"},
                   attempts=0, spec_exact=False, latency=0.0, credit=None)
        return row
    result = parse_rules(item["text"], client, max_attempts=max_attempts, givens=item["givens"],
                         check_solvable=True)
    usable = result.status in ("ok", "unsupported")
    cmp = compare(safe_canonical(result.spec) if usable else None,
                  canonical_items({"constraints": item["gold_constraints"]}))
    credits = [a.credit for a in result.attempts if getattr(a, "credit", None) is not None]
    row.update(
        status=result.status, spec=result.spec if usable else None, unsupported=result.unsupported,
        error=result.error, attempts=result.n_attempts, spec_exact=cmp["exact"],
        tp=cmp["tp"], fp=cmp["fp"], fn=cmp["fn"], solvability=result.solvability,
        latency=round(time.perf_counter() - t0, 3), credit=round(sum(credits), 4) if credits else None,
        stages=[a.stage for a in result.attempts],
    )
    return row


# ---------------------------------------------------------------- 2단계: 같은 명세로 두 알고리즘

def methods(time_limit: float):
    from sudoku_engine import SolverConfig
    from sudoku_engine.local_search import LocalSearchConfig

    bt = [SolverConfig(var_order="mrv_degree", val_order="lcv", propagation="ac3", time_limit=time_limit),
          SolverConfig(var_order="static", val_order="asc", propagation="none", time_limit=time_limit)]
    ls = [LocalSearchConfig(init="random"), LocalSearchConfig(init="row")]
    return bt, ls


def _check_against_gold(grid: str | None, item: dict) -> tuple[bool, bool]:
    """(정답과 같음, 정답 명세의 모든 제약 만족)."""
    if grid is None:
        return False, False
    from sudoku_engine.spec import load_spec

    model = load_spec({"givens": "." * 81, "constraints": item["gold_constraints"]})
    assign = {(i // 9, i % 9): int(ch) for i, ch in enumerate(grid)}
    givens_kept = all(ch in ".0" or grid[i] == ch for i, ch in enumerate(item["gold_givens"]))
    valid = givens_kept and all(c.check(assign) for c in model.constraints)
    return grid == item["solution"], valid


def solve_spec(spec: dict, item: dict, time_limit: float, trials: int, seed: int, index: int) -> list[dict]:
    """명세 하나를 모든 방법으로 푼다. 시도마다 Model을 새로 만든다(풀이기가 Model을 바꿀 수 있으므로)."""
    from sudoku_engine import solve
    from sudoku_engine.local_search import LocalSearchConfig, solve_local_search
    from sudoku_engine.spec import load_spec

    bt, ls = methods(time_limit)
    out: list[dict] = []
    for cfg in bt:
        r = solve(load_spec(spec), cfg)
        grid = _grid_str(r.solution) if r.solved else None
        exact, valid = _check_against_gold(grid, item)
        out.append({"method": "backtracking/" + cfg.label(), "kind": "backtracking", "trial": 0,
                    "solved": r.solved, "exact": exact, "valid": valid, "timed_out": r.stats.timed_out,
                    "elapsed": r.stats.elapsed, "nodes": getattr(r.stats, "nodes", None)})
    for lcfg in ls:
        for t in range(trials):
            run_cfg = LocalSearchConfig(noise=lcfg.noise, patience=lcfg.patience, init=lcfg.init,
                                        max_steps=lcfg.max_steps, seed=seed + 1000 * index + t,
                                        time_limit=time_limit)
            r = solve_local_search(load_spec(spec), run_cfg)
            grid = _grid_str(r.solution) if r.solved else None
            exact, valid = _check_against_gold(grid, item)
            out.append({"method": lcfg.label(), "kind": "local_search", "trial": t,
                        "solved": r.solved, "exact": exact, "valid": valid, "timed_out": r.stats.timed_out,
                        "elapsed": r.stats.elapsed, "steps": r.stats.steps, "restarts": r.stats.restarts,
                        "best_violation": r.stats.best_violation})
    return out


def failed_runs(item: dict, time_limit: float, trials: int) -> list[dict]:
    """파싱 실패 → 풀 명세가 없음. 모든 방법에서 '실패'로 기록(시간은 time_limit으로 셈)."""
    bt, ls = methods(time_limit)
    rows = [{"method": "backtracking/" + c.label(), "kind": "backtracking", "trial": 0} for c in bt]
    rows += [{"method": c.label(), "kind": "local_search", "trial": t} for c in ls for t in range(trials)]
    for r in rows:
        r.update(solved=False, exact=False, valid=False, timed_out=False, elapsed=time_limit, no_spec=True)
    return rows


# ---------------------------------------------------------------- 집계

def summarize(runs: list[dict], time_limit: float) -> list[dict]:
    rows = []
    for m in dict.fromkeys(r["method"] for r in runs):
        rs = [r for r in runs if r["method"] == m]
        ok = [r["elapsed"] for r in rs if r["exact"]]
        rows.append({
            "method": m,
            "kind": rs[0]["kind"],
            "정답": f"{sum(r['exact'] for r in rs)}/{len(rs)}",
            "정답률": f"{100 * sum(r['exact'] for r in rs) / len(rs):.0f}%",
            "풀이 성공률": f"{100 * sum(r['solved'] for r in rs) / len(rs):.0f}%",
            "시간 초과": sum(r["timed_out"] for r in rs),
            "중앙값 ms(정답만)": round(statistics.median(ok) * 1000, 1) if ok else None,
            "평균 ms(실패=제한)": round(statistics.mean(r["elapsed"] if r["exact"] else time_limit
                                                  for r in rs) * 1000, 1),
        })
    return rows


def by_group(runs: list[dict], items: dict[str, dict], key: str) -> list[dict]:
    """방법 × (tier 또는 variant) 정답률 표 — 보고서 그래프용."""
    groups = sorted({items[r["id"]][key] for r in runs})
    meths = list(dict.fromkeys(r["method"] for r in runs))
    out = []
    for g in groups:
        row = {key: g}
        for m in meths:
            rs = [r for r in runs if r["method"] == m and items[r["id"]][key] == g]
            row[m] = f"{100 * sum(r['exact'] for r in rs) / len(rs):.0f}%" if rs else "-"
        out.append(row)
    return out


def table(rows: list[dict]) -> str:
    if not rows:
        return "(결과 없음)"
    hs = list(rows[0].keys())
    lines = ["| " + " | ".join(hs) + " |", "|" + "|".join("---" for _ in hs) + "|"]
    lines += ["| " + " | ".join("-" if r.get(h) is None else str(r.get(h)) for h in hs) + " |" for r in rows]
    return "\n".join(lines)


def parse_summary(parsed: list[dict]) -> dict:
    n = len(parsed)
    st = [p["status"] for p in parsed]
    credits = [p["credit"] for p in parsed if p.get("credit") is not None]
    return {
        "퍼즐": n,
        "파싱 사용 가능(ok+unsupported)": sum(s in ("ok", "unsupported") for s in st),
        "명세 완전일치": sum(bool(p.get("spec_exact")) for p in parsed),
        "실패(failed)": st.count("failed"), "API 오류": st.count("api_error"),
        "단서 추출 정확": sum(bool(p.get("givens_ok")) for p in parsed),
        "평균 호출 수": round(statistics.mean(p["attempts"] for p in parsed), 2) if parsed else 0,
        "사용 크레딧(응답 기준)": round(sum(credits), 2) if credits else None,
    }


# ---------------------------------------------------------------- CLI

class SpecMock(PuzzleMock):
    """solver_eval용 가짜 LLM: 파싱 요청에 정답 명세를 돌려준다(noisy면 첫 시도만 깨진 JSON)."""

    def __init__(self, items: list[dict], mode: str = "oracle") -> None:
        fake = [{"givens": it["givens"] or "", "rules_text": it["text"], "constraints": it["gold_constraints"],
                 "solution": it["solution"]} for it in items]
        super().__init__(fake, mode)


def _load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LLM 파싱 → 백트래킹 / 지역 탐색 풀이 평가")
    ap.add_argument("--client", default="oracle",
                    choices=["oracle", "noisy", "factchat", "anthropic", "openai", "gemini", "gemini-openai"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--puzzles", default="all", choices=["nl", "examples", "all"])
    ap.add_argument("--limit", type=int, default=None, help="앞에서 N개만 (시험용)")
    ap.add_argument("--specs", default=None, help="이전 실행의 solver_specs_*.jsonl — 파싱을 건너뛰고 재사용(크레딧 0)")
    ap.add_argument("--time-limit", type=float, default=5.0, help="풀이 1회당 제한(초), ② 벤치마크 기본값과 같음")
    ap.add_argument("--trials", type=int, default=3, help="지역 탐색 seed 반복 횟수")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.0, help="LLM 호출 사이 최소 간격(초)")
    ap.add_argument("--max-tokens", type=int, default=None)
    ap.add_argument("--no-gold", action="store_true", help="정답 명세 기준(LLM 없음) 풀이 생략")
    ap.add_argument("--out", default=str(RESULTS))
    args = ap.parse_args(argv)

    items = load_eval_puzzles(args.puzzles)
    if args.limit:
        items = items[: args.limit]
    missing = [it["id"] for it in items if not it["solution"]]
    if missing:
        print(f"[경고] 정답 격자가 없는 퍼즐 {len(missing)}개 제외: {missing}")
        items = [it for it in items if it["solution"]]
    by_id = {it["id"]: it for it in items}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    # ---- 1단계: 파싱
    if args.specs:
        parsed = [p for p in _load_jsonl(Path(args.specs)) if p["id"] in by_id]
        model_name = parsed[0].get("model", "cached") if parsed else "cached"
        print(f"파싱 결과 재사용: {args.specs} ({len(parsed)}개, LLM 호출 없음)")
        items = [by_id[p["id"]] for p in parsed]
    else:
        try:
            if args.client in ("oracle", "noisy"):
                client: LLMClient = SpecMock(items, args.client)
            else:
                client = make_client(args.client, args.model, max_tokens=args.max_tokens)
                if args.sleep > 0:
                    client = Throttled(client, args.sleep)
        except LLMAPIError as exc:
            print(f"\n[API 오류] {exc}")
            return 1
        model_name = client.name
        real = args.client not in ("oracle", "noisy")
        parsed = []
        spec_path = out / f"solver_specs_{model_name.split(':')[-1].replace('/', '_')}_{stamp}.jsonl"
        with open(spec_path, "w", encoding="utf-8") as f:
            for k, it in enumerate(items, 1):
                print(f"  [파싱 {k}/{len(items)}] {it['id']} ...", end="", flush=True)
                p = parse_one(it, client)
                p["model"] = model_name
                parsed.append(p)
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
                f.flush()
                tag = "명세 일치" if p["spec_exact"] else p["status"]
                print(f" {tag} (호출 {p['attempts']}회{', ' + str(p['credit']) + ' cr' if p.get('credit') else ''})")
                if real and p.get("error") and p["error"].get("kind") in STOP_KINDS:
                    print(f"\n[중단 — API 오류] {p['error']['message']}\n지금까지의 파싱 결과: {spec_path}"
                          f"\n남은 퍼즐은 문제를 해결한 뒤 다시 실행하세요.")
                    return 1
        print(f"파싱 결과 저장: {spec_path}")

    # ---- 2단계: 같은 명세로 두 알고리즘 (+ 정답 명세 기준)
    runs: list[dict] = []
    gold_runs: list[dict] = []
    for i, (it, p) in enumerate(zip(items, parsed)):
        print(f"  [풀이 {i + 1}/{len(items)}] {it['id']} ...", end="", flush=True)
        rs = solve_spec(p["spec"], it, args.time_limit, args.trials, args.seed, i) if p.get("spec") \
            else failed_runs(it, args.time_limit, args.trials)
        for r in rs:
            r.update(id=it["id"], parse_status=p["status"], spec_exact=p.get("spec_exact"))
        runs.extend(rs)
        if not args.no_gold:
            gold_spec = {"givens": it["gold_givens"], "constraints": it["gold_constraints"]}
            if p.get("spec_exact") and p.get("givens_ok"):
                grs = [dict(r) for r in rs]  # 같은 명세 + 같은 seed → 같은 결과, 다시 풀지 않음
            else:
                grs = solve_spec(gold_spec, it, args.time_limit, args.trials, args.seed, i)
                for r in grs:
                    r.update(id=it["id"])
            gold_runs.extend(grs)
        bt_ok = sum(r["exact"] for r in rs if r["kind"] == "backtracking")
        ls_ok = sum(r["exact"] for r in rs if r["kind"] == "local_search")
        print(f" 백트래킹 정답 {bt_ok}/2 · 지역 탐색 정답 {ls_ok}/{2 * args.trials}")

    # ---- 집계·저장
    psum = parse_summary(parsed)
    llm_tab = summarize(runs, args.time_limit)
    gold_tab = summarize(gold_runs, args.time_limit) if gold_runs else []
    tag = f"solver_eval_{args.puzzles}_" + str(model_name).split(":")[-1].replace("/", "_")
    with open(out / f"{tag}_{stamp}.jsonl", "w", encoding="utf-8") as f:
        for r in runs:
            f.write(json.dumps({"pipeline": "llm", **r}, ensure_ascii=False) + "\n")
        for r in gold_runs:
            f.write(json.dumps({"pipeline": "gold", **r}, ensure_ascii=False) + "\n")
    summary = {
        "model": model_name, "puzzles": args.puzzles, "n": len(items), "time_limit": args.time_limit,
        "trials": args.trials, "seed": args.seed, "specs": args.specs, "parse": psum,
        "llm_pipeline": llm_tab, "gold_spec": gold_tab,
        "by_tier": by_group(runs, by_id, "tier"), "by_variant": by_group(runs, by_id, "variant"),
    }
    (out / f"{tag}_{stamp}_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")
    md = [f"# LLM 연동 풀이 평가 — {model_name}", "",
          f"퍼즐 {len(items)}개 · 풀이 제한 {args.time_limit}초 · 지역 탐색 seed {args.trials}회", "",
          "## 1. 파싱 (LLM, 퍼즐당 1회)", "", table([psum]), "",
          "## 2. LLM 명세 → 풀이 (파싱 실패는 실패로 셈)", "", table(llm_tab), ""]
    if gold_tab:
        md += ["## 3. 정답 명세 → 풀이 (LLM 없음, 알고리즘 자체의 한계)", "", table(gold_tab), ""]
    md += ["## 4. 난이도별 정답률 (LLM 명세)", "", table(summary["by_tier"]), "",
           "## 5. 변형별 정답률 (LLM 명세)", "", table(summary["by_variant"]), ""]
    (out / f"{tag}_{stamp}.md").write_text("\n".join(md), encoding="utf-8")
    print("\n" + "\n".join(md))
    print(f"\n결과 저장: {out / f'{tag}_{stamp}.md'} (+ .jsonl, _summary.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
