"""solver_eval: 가짜 LLM으로 파싱 → 백트래킹·지역 탐색 → 집계가 끝까지 도는지 확인 (LLM 호출 없음)."""

import json

from llm_parser import solver_eval


def test_load_eval_puzzles_has_solutions_and_givens():
    items = solver_eval.load_eval_puzzles("all")
    assert len(items) == 50
    assert all(it["solution"] and len(it["solution"]) == 81 for it in items)
    assert all(it["givens"] == it["gold_givens"] for it in items)  # 코드 추출 단서 = 정답 단서


def test_oracle_run_end_to_end(tmp_path):
    rc = solver_eval.main(["--client", "oracle", "--puzzles", "examples", "--limit", "2",
                           "--time-limit", "2", "--trials", "1", "--out", str(tmp_path)])
    assert rc == 0
    summ = json.loads(next(tmp_path.glob("*_summary.json")).read_text(encoding="utf-8"))
    assert summ["parse"]["명세 완전일치"] == 2
    bt = [r for r in summ["llm_pipeline"] if r["kind"] == "backtracking"]
    assert bt and bt[0]["정답"] == "2/2"
    # 저장된 파싱 결과를 재사용하면 LLM 없이 같은 표가 나온다
    specs = next(tmp_path.glob("solver_specs_*.jsonl"))
    out2 = tmp_path / "again"
    assert solver_eval.main(["--specs", str(specs), "--puzzles", "examples", "--time-limit", "2",
                             "--trials", "1", "--out", str(out2)]) == 0
    summ2 = json.loads(next(out2.glob("*_summary.json")).read_text(encoding="utf-8"))
    assert summ2["llm_pipeline"][0]["정답"] == summ["llm_pipeline"][0]["정답"]


def test_failed_parse_counts_as_failure():
    item = solver_eval.load_eval_puzzles("examples")[0]
    rows = solver_eval.failed_runs(item, 5.0, 2)
    assert len(rows) == 2 + 2 * 2
    assert not any(r["exact"] for r in rows)
    assert solver_eval.summarize(rows, 5.0)[0]["정답률"] == "0%"
