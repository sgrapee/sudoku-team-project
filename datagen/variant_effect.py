"""E3 변형 제약 효과: 같은 단서에서 변형 제약을 켜고 끄면 해 개수·탐색 비용이 어떻게 달라지는지 본다.

    python datagen/variant_effect.py              # 실행 + 그래프·표 (병렬 4개, 몇 분)
    python datagen/variant_effect.py --plot-only  # 저장된 CSV로 그래프·표만 다시 만든다

입력: puzzles/{diagonal,thermo,arrow,killer,mixed}_{easy,medium,expert}.jsonl (375개, 모두 유일해)
결과: results/E3_full/E3_raw.csv, E3_summary.md, figures/E3_0{1,2,3}_*.png

퍼즐마다
- ON : 원래 spec. 해 개수(2개까지 세서 유일한지 확인)와 첫 해까지의 탐색 비용
- OFF: 같은 단서에서 변형 제약을 모두 뺀 클래식. 해 개수(LIMIT개까지), 첫 해까지의 탐색 비용,
       그 해가 원래 정답과 같은지
- 혼합(diagonal+thermo+arrow)은 한 종류씩만 뺀 해 개수도 센다
- 백트래킹 설정은 엔진 기본(mrv_degree/lcv/ac3), 실행마다 제한 10초. 시간은 병렬 실행이라 보조 지표
"""
from __future__ import annotations

import argparse
import csv
import random
import statistics
import sys
from multiprocessing import Pool

from common import PUZZLES_DIR, ROOT, read_jsonl  # 엔진 import 경로 설정 포함 — sudoku_engine보다 먼저
from sudoku_engine import Solver, SolverConfig
from sudoku_engine.spec import load_spec

OUT_DIR = ROOT / "results" / "E3_full"
RAW = OUT_DIR / "E3_raw.csv"
TL, LIMIT, WORKERS = 10.0, 1000, 4
VARIANTS = ("diagonal", "thermo", "arrow", "killer", "mixed")
TIERS = ("easy", "medium", "expert")
MIXED_TYPES = ("diagonal", "thermo", "arrow")

BLUE, ORANGE, TEXT, MUTED, GRID, SURFACE = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
DPI = 180


# ------------------------------------------------------------------ 실행
def grid_string(solution: dict) -> str:
    return "".join(str(solution[(r, c)]) for r in range(9) for c in range(9))


def count(spec: dict, limit: int) -> tuple[int, int, float]:
    """(해 개수, 시간 초과 여부, ms). limit에 닿으면 그 이상일 수 있다."""
    solver = Solver(load_spec(spec), SolverConfig(time_limit=TL))
    found = solver.solve_all(limit=limit)
    return len(found), int(solver.stats.timed_out), round(solver.stats.elapsed * 1000, 2)


def first_solution(spec: dict, prefix: str) -> tuple[dict, str | None]:
    result = Solver(load_spec(spec), SolverConfig(time_limit=TL)).solve()
    st = result.stats
    row = {f"{prefix}_solved": int(result.solved), f"{prefix}_timed_out": int(st.timed_out),
           f"{prefix}_nodes": st.nodes, f"{prefix}_branch_nodes": st.branch_nodes,
           f"{prefix}_ms": round(st.elapsed * 1000, 2),
           f"{prefix}_revisions": st.propagation.get("arc_revisions", 0),
           f"{prefix}_eliminations": st.propagation.get("value_eliminations", 0)}
    return row, grid_string(result.solution) if result.solution else None


def work(item: tuple[str, str, dict]) -> dict:
    variant, tier, rec = item
    spec = rec["spec"]
    cons = spec.get("constraints") or []
    off_spec = dict(spec, constraints=[])
    row = {"puzzle_id": rec["id"], "variant": variant, "tier": tier, "givens": rec["givens"],
           "n_constraints": len(cons)}

    n, timed_out, ms = count(spec, 2)
    row.update(on_solutions=n, on_count_timed_out=timed_out, on_count_ms=ms)
    on_row, _ = first_solution(spec, "on")
    row.update(on_row)

    off_row, off_grid = first_solution(off_spec, "off")
    row.update(off_row)
    row["off_same_solution"] = int(off_grid == rec["solution"]) if off_grid else ""
    n, timed_out, ms = count(off_spec, LIMIT)
    row.update(off_solutions=n, off_count_capped=int(n >= LIMIT), off_count_timed_out=timed_out,
               off_count_ms=ms)

    for t in MIXED_TYPES:
        key = f"drop_{t}_solutions"
        if variant == "mixed":
            n, timed_out, _ = count(dict(spec, constraints=[c for c in cons if c["type"] != t]), LIMIT)
            row[key] = n
            row[f"drop_{t}_timed_out"] = timed_out
        else:
            row[key] = row[f"drop_{t}_timed_out"] = ""
    return row


def load_items() -> list[tuple[str, str, dict]]:
    items = []
    for variant in VARIANTS:
        for tier in TIERS:
            path = PUZZLES_DIR / f"{variant}_{tier}.jsonl"
            if not path.is_file():
                sys.exit(f"오류: {path} 가 없습니다.")
            items += [(variant, tier, rec) for rec in read_jsonl(path)]
    return items


def run() -> None:
    items = load_items()
    rows = []
    with Pool(WORKERS) as pool:
        for row in pool.imap_unordered(work, items):
            rows.append(row)
            if len(rows) % 25 == 0 or len(rows) == len(items):
                print(f"{len(rows)}/{len(items)}", flush=True)
    order = {(v, t): i for i, (v, t) in enumerate((v, t) for v in VARIANTS for t in TIERS)}
    rows.sort(key=lambda r: (order[(r["variant"], r["tier"])], r["puzzle_id"]))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with RAW.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"saved: {RAW} ({len(rows)} rows)")


# ------------------------------------------------------------------ 그래프·표
def read_rows() -> list[dict]:
    if not RAW.is_file():
        sys.exit(f"오류: {RAW} 가 없습니다. --plot-only 없이 먼저 실행하세요.")
    with RAW.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def by_variant(rows: list[dict]) -> dict[str, list[dict]]:
    return {v: [r for r in rows if r["variant"] == v] for v in VARIANTS if any(r["variant"] == v for r in rows)}


def med(values) -> float:
    values = list(values)
    return statistics.median(values) if values else float("nan")


def setup(plt) -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.size": 10, "text.color": TEXT, "axes.labelcolor": TEXT, "axes.edgecolor": MUTED,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "axes.axisbelow": True, "legend.frameon": False,
    })


def plot_solutions(plt, groups) -> None:
    """변형 제약을 끄면 해가 몇 개가 되는가 (켜면 모두 1개)."""
    jitter = random.Random(0)
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    for i, (variant, rs) in enumerate(groups.items()):
        ys = [int(r["off_solutions"]) for r in rs]
        ax.scatter([i + jitter.uniform(-0.22, 0.22) for _ in ys], ys, s=14, color=ORANGE, alpha=0.5,
                   linewidth=0, zorder=2)
        capped = sum(int(r["off_count_capped"]) for r in rs)
        ax.annotate(f"{100 * capped / len(rs):.0f}% ≥ {LIMIT}", (i, LIMIT * 1.9), ha="center", fontsize=9,
                    color=TEXT)
        ax.scatter([i], [1], marker="D", s=40, color=BLUE, zorder=3)
    ax.set_yscale("log")
    ax.set_ylim(0.6, LIMIT * 4)
    ax.set_xticks(range(len(groups)), [f"{v}\n{len(rs)} puzzles" for v, rs in groups.items()])
    ax.set_xlim(-0.6, len(groups) - 0.4)
    ax.grid(axis="x", visible=False)
    ax.set_ylabel(f"Number of solutions (counted up to {LIMIT}, log)")
    handles = [plt.Line2D([], [], marker="D", linestyle="", color=BLUE, markersize=7,
                          label="constraints ON: exactly 1 (every puzzle)"),
               plt.Line2D([], [], marker="o", linestyle="", color=ORANGE, markersize=5,
                          label="constraints OFF (same givens, classic rules only)")]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, fontsize=9)
    ax.set_title("Same givens, variant constraints switched off: how many solutions?", loc="left")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "figures" / "E3_01_solutions_off.png", dpi=DPI)
    plt.close(fig)


def ms_per_node(r: dict, prefix: str) -> float:
    """탐색 노드 하나에 드는 시간. 전파(이진 arc + 변형 제약의 propagate) 비용이 모두 들어간다.
    arc_revisions는 이진 arc만 세고 변형 제약의 전파는 세지 않아 전파 비용 비교에 쓰지 않는다."""
    return float(r[f"{prefix}_ms"]) / max(1, int(r[f"{prefix}_nodes"]))


def plot_cost(plt, groups) -> None:
    """첫 해까지 분기 노드, 노드당 시간 (ON vs OFF)."""
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6))
    names = list(groups)
    width = 0.38
    panels = (
        ("Branch nodes to first solution (median)", "branch_nodes", "symlog"),
        ("Time per search node, ms (median; includes all propagation)", "ms_per_node", "linear"),
    )
    for ax, (title, key, scale) in zip(axes, panels):
        for k, (prefix, label, color) in enumerate((("on", "constraints ON", BLUE),
                                                     ("off", "constraints OFF", ORANGE))):
            ys = []
            for v in names:
                rs = [r for r in groups[v] if r[f"{prefix}_solved"] == "1"]
                if key == "branch_nodes":
                    ys.append(med(float(r[f"{prefix}_branch_nodes"]) for r in rs))
                else:
                    ys.append(med(ms_per_node(r, prefix) for r in rs))
            xs = [i + (k - 0.5) * width for i in range(len(names))]
            bars = ax.bar(xs, ys, width=width, color=color, label=label, edgecolor=SURFACE, linewidth=2)
            ax.bar_label(bars, labels=[f"{y:.3g}" for y in ys], padding=2, fontsize=8.5, color=TEXT)
        ax.set_xticks(range(len(names)), names)
        ax.grid(axis="x", visible=False)
        ax.set_title(title, loc="left", fontsize=10)
        if scale == "symlog":
            ax.set_yscale("symlog", linthresh=1)
            top = max(p.get_height() for p in ax.patches)
            ax.set_ylim(0, max(top, 1) * 4)
        else:
            ax.set_ylim(0, max(p.get_height() for p in ax.patches) * 1.18)
    axes[0].legend(loc="upper left", fontsize=9)
    fig.suptitle("Search cost with and without variant constraints (mrv_degree/lcv/ac3)",
                 x=0.01, ha="left", fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "figures" / "E3_02_search_cost.png", dpi=DPI)
    plt.close(fig)


def plot_mixed(plt, rows) -> None:
    """혼합 퍼즐에서 제약 종류를 하나씩 빼면 해가 몇 개가 되는가."""
    mixed = [r for r in rows if r["variant"] == "mixed"]
    if not mixed:
        return
    conditions = [("all on", [int(r["on_solutions"]) for r in mixed])]  # 2개까지 센 값 (1 = 유일해)
    conditions += [(f"drop {t}", [int(r[f"drop_{t}_solutions"]) for r in mixed]) for t in MIXED_TYPES]
    conditions += [("all off", [int(r["off_solutions"]) for r in mixed])]
    jitter = random.Random(1)
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    for i, (name, ys) in enumerate(conditions):
        ax.scatter([i + jitter.uniform(-0.2, 0.2) for _ in ys], ys, s=14, color=BLUE, alpha=0.5,
                   linewidth=0, zorder=2)
        unique = sum(1 for y in ys if y == 1)
        capped = sum(1 for y in ys if y >= LIMIT)
        ax.annotate(f"unique {unique}/{len(ys)}\n≥{LIMIT}: {capped}", (i, LIMIT * 1.6), ha="center",
                    fontsize=8.5, color=TEXT)
    ax.set_yscale("log")
    ax.set_ylim(0.6, LIMIT * 6)
    ax.set_xticks(range(len(conditions)), [n for n, _ in conditions])
    ax.grid(axis="x", visible=False)
    ax.set_ylabel(f"Number of solutions (counted up to {LIMIT}, log)")
    ax.set_title(f"Mixed puzzles (diagonal + thermo + arrow, {len(mixed)} puzzles): "
                 "which constraint type makes the solution unique?", loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "figures" / "E3_03_mixed_ablation.png", dpi=DPI)
    plt.close(fig)


def write_summary(rows, groups) -> None:
    lines = ["# E3 변형 제약 효과", "",
             f"`python datagen/variant_effect.py`가 만든다. 퍼즐 {len(rows)}개, 엔진 기본 설정(mrv_degree/lcv/ac3), "
             f"실행마다 제한 {TL:g}초, 해는 {LIMIT}개까지 센다. 시간은 병렬 4개로 잰 값이라 보조 지표.", "",
             "## 해 개수 (E3_01_solutions_off.png)", "",
             "| 변형 | 퍼즐 | 단서 수 | ON 유일해 | OFF 해 개수 중앙값 | OFF ≥" + f"{LIMIT} | OFF 첫 해 = 원래 정답 |",
             "|---|---|---|---|---|---|---|"]
    for v, rs in groups.items():
        g = [int(r["givens"]) for r in rs]
        unique = sum(1 for r in rs if r["on_solutions"] == "1" and r["on_count_timed_out"] == "0")
        off = [int(r["off_solutions"]) for r in rs]
        capped = sum(int(r["off_count_capped"]) for r in rs)
        same = sum(1 for r in rs if r["off_same_solution"] == "1")
        med_off = med(off)
        lines.append(f"| {v} | {len(rs)} | {min(g)}~{max(g)} | {unique}/{len(rs)} | "
                     f"{'≥' + str(LIMIT) if med_off >= LIMIT else f'{med_off:g}'} | "
                     f"{100 * capped / len(rs):.0f}% ({capped}) | {100 * same / len(rs):.0f}% ({same}) |")
    lines += ["", "## 탐색 비용: 첫 해까지 (E3_02_search_cost.png)", "",
              "중앙값. 탐색 노드 수는 ON·OFF가 거의 같아서(대부분 빈칸 수만큼), 차이는 분기 노드(값을 2개 이상 시도한 곳)에서 난다. "
              "노드당 시간에는 변형 제약의 전파 비용이 모두 들어간다. 비율은 퍼즐마다 ON/OFF를 나눈 값의 중앙값.", "",
              "| 변형 | 분기 노드 ON | 분기 노드 OFF | ms ON | ms OFF | 노드당 ms ON | 노드당 ms OFF | 노드당 시간 비율 ON/OFF |",
              "|---|---|---|---|---|---|---|---|"]
    for v, rs in groups.items():
        both = [r for r in rs if r["on_solved"] == "1" and r["off_solved"] == "1"]

        def m(prefix, key):
            return med(float(r[f"{prefix}_{key}"]) for r in rs if r[f"{prefix}_solved"] == "1")

        def mpn(prefix):
            return med(ms_per_node(r, prefix) for r in rs if r[f"{prefix}_solved"] == "1")

        ratio = med(ms_per_node(r, "on") / ms_per_node(r, "off") for r in both if ms_per_node(r, "off") > 0)
        lines.append(f"| {v} | {m('on', 'branch_nodes'):g} | {m('off', 'branch_nodes'):g} | "
                     f"{m('on', 'ms'):.1f} | {m('off', 'ms'):.1f} | {mpn('on'):.3f} | {mpn('off'):.3f} | {ratio:.2f} |")
    mixed = [r for r in rows if r["variant"] == "mixed"]
    if mixed:
        lines += ["", f"## 혼합 퍼즐에서 한 종류씩 빼기 (E3_03_mixed_ablation.png, {len(mixed)}개)", "",
                  "| 조건 | 유일해 | 해 개수 중앙값 | ≥" + f"{LIMIT} |", "|---|---|---|---|"]
        conditions = [("모두 켬", [int(r["on_solutions"]) for r in mixed])]
        conditions += [(f"{t} 뺌", [int(r[f"drop_{t}_solutions"]) for r in mixed]) for t in MIXED_TYPES]
        conditions.append(("모두 뺌", [int(r["off_solutions"]) for r in mixed]))
        for name, ys in conditions:
            unique = sum(1 for y in ys if y == 1)
            capped = sum(1 for y in ys if y >= LIMIT)
            lines.append(f"| {name} | {unique}/{len(ys)} | {med(ys):g} | {capped} |")
    timeouts = sum(int(r["on_count_timed_out"]) + int(r["off_count_timed_out"]) + int(r["on_timed_out"])
                   + int(r["off_timed_out"]) for r in rows)
    lines += ["", f"시간 초과(어느 단계든): {timeouts}건"]
    (OUT_DIR / "E3_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def report() -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        sys.exit("matplotlib이 필요합니다. 실행: python -m pip install matplotlib")
    rows = read_rows()
    groups = by_variant(rows)
    (OUT_DIR / "figures").mkdir(parents=True, exist_ok=True)
    setup(plt)
    plot_solutions(plt, groups)
    plot_cost(plt, groups)
    plot_mixed(plt, rows)
    write_summary(rows, groups)


def main() -> None:
    ap = argparse.ArgumentParser(description="E3: 변형 제약 ON/OFF 효과")
    ap.add_argument("--plot-only", action="store_true", help="실행하지 않고 저장된 CSV로 그래프·표만 만든다")
    args = ap.parse_args()
    if not args.plot_only:
        run()
    report()


if __name__ == "__main__":
    main()
