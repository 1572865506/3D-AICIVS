"""统一评分入口（evaluate_plan）与候选方案排序。

对外只暴露两件事：
1. `evaluate_plan(...)`：给一个方案（SolverSolution 或放置列表）打分，
   自动补齐几何体检与交付门禁，返回可解释的 PlanScore。
2. `rank_plans(...)`：给同一货单的多个候选方案排序、选出推荐方案，
   并说明每个备选为什么没被推荐（安全底线/刚性履约/装载量约束）。

求解器只负责"产出候选"，本模块只负责"比较候选"——两者解耦，
避免评分逻辑再次散落进求解循环（此前 12 处门禁拷贝的教训）。

被谁调用：server.py（多方案选择与 API 输出）、tests/test_evaluation_score.py。
"""

import types
from typing import Any, Dict, Iterable, List, Optional

from backend.solver_v2.evaluation.scenarios import detect_scenario
from backend.solver_v2.evaluation.score import score_plan
from backend.solver_v2.evaluation.spec import PolicyProfile, get_policy


def _extract_placements(source: Any) -> List[Any]:
    if source is None:
        return []
    if isinstance(source, (list, tuple)):
        return list(source)
    return list(getattr(source, "placements", []) or [])


def _as_solution_source(source: Any) -> Any:
    """把放置列表包装成 evaluate_delivery / geometry_qa 需要的对象形状。"""
    if source is None or not isinstance(source, (list, tuple)):
        return source
    return types.SimpleNamespace(
        container=None,
        placements=list(source),
        validation_result=None,
        volume_utilization_pct=0.0,
        total_weight_kg=0.0,
        telemetry=types.SimpleNamespace(geometry_qa=None, cavity_diagnostics=[]),
    )


def evaluate_plan(
    source: Any,
    cargo_list: List[Any],
    container: Any,
    *,
    policy: Optional[str] = None,
    scenario: Optional[Dict[str, Any]] = None,
    qa: Optional[Dict[str, Any]] = None,
    gate: Optional[Dict[str, Any]] = None,
    sequence_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """给单个方案打分。

    参数：
    - source：SolverSolution 或放置列表（Placement / dict 均可）
    - cargo_list / container：货单与柜体（口径与求解器一致）
    - policy：策略档（缺省按场景推）；scenario：detect_scenario 的结果
    - qa / gate：已算好则直接复用，避免重复计算
    """
    sol = _as_solution_source(source)
    placements = _extract_placements(source)
    container = container or getattr(sol, "container", None)

    scen = scenario or detect_scenario(cargo_list, container)
    profile: PolicyProfile = get_policy(policy or scen.get("policy"))

    if qa is None:
        qa = getattr(getattr(sol, "telemetry", None), "geometry_qa", None)
    if qa is None:
        from backend.solver_v2.diagnostics.geometry_qa import compute_geometry_qa
        cavity = getattr(getattr(sol, "telemetry", None), "cavity_diagnostics", None) or []
        qa = compute_geometry_qa(container, placements, cavity)

    if gate is None:
        from backend.solver_v2.validation.delivery_gate import evaluate_delivery
        gate = evaluate_delivery(
            sol, cargo_list, container, geometry_qa=qa,
            sequence_report=sequence_report,
        )

    sequence_feasible = None
    sequence_measured = False
    if sequence_report is not None:
        sequence_measured = True
        sequence_feasible = bool(sequence_report.get("feasible", True))

    result = score_plan(
        placements, cargo_list, container,
        qa=qa, gate=gate,
        validation_result=getattr(sol, "validation_result", None),
        sequence_feasible=sequence_feasible,
        policy=profile,
    )
    result["scenario"] = scen
    result["sequence_measured"] = sequence_measured
    result["gate"] = {
        "verdict": gate.get("verdict"),
        "blocked_by": list(gate.get("blocked_by") or []),
        "warnings": list(gate.get("warnings") or []),
    }
    result["qa"] = qa
    return result


def _safety_ok(evaluation: Dict[str, Any]) -> bool:
    tiers = evaluation.get("tiers") or {}
    return bool((tiers.get("T1") or {}).get("passed", False))


def rank_plans(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """对候选方案排序并给出推荐。

    entries: [{key, label, evaluation}, ...]，evaluation 为 evaluate_plan 输出。
    返回：{ordered: [...], recommended_key, notes: [...]}
    """
    usable = [e for e in entries if isinstance(e.get("evaluation"), dict)]
    if not usable:
        return {"ordered": [], "recommended_key": None, "notes": ["没有可评分方案"]}

    profile = get_policy(usable[0]["evaluation"].get("policy"))
    # 业务约束（刚性/装载量）只在"满足安全底线"的方案之间比较：
    # 一个不安全的高装载率方案不能反过来把安全方案挤成"不合格"。
    safe_entries = [
        e for e in usable
        if not (e["evaluation"].get("hard_fail")) and _safety_ok(e["evaluation"])
    ] or usable
    safe_metrics = [e["evaluation"].get("metrics") or {} for e in safe_entries]
    best_rigid = max(float(m.get("rigid_ratio", 1.0) or 0.0) for m in safe_metrics)
    best_placed = max(int(m.get("placed_count", 0) or 0) for m in safe_metrics)

    eligible: List[Dict[str, Any]] = []
    notes: List[str] = []
    for entry in usable:
        ev = entry["evaluation"]
        m = ev.get("metrics") or {}
        reasons: List[str] = []
        if ev.get("hard_fail"):
            reasons.append("未通过 T0 硬约束")
        if not _safety_ok(ev):
            reasons.append(
                f"未达安全底线（门面 SF {m.get('door_min_sf')} / 失稳占比 "
                f"{float(m.get('transport_unstable_ratio', 0) or 0) * 100:.1f}%）"
            )
        if float(m.get("rigid_ratio", 1.0) or 0.0) < best_rigid - profile.max_rigid_loss_pp / 100.0:
            reasons.append(
                f"刚性履行 {float(m.get('rigid_ratio', 0)) * 100:.1f}% 低于最优 "
                f"{best_rigid * 100:.1f}% 超过 {profile.max_rigid_loss_pp}pp"
            )
        if best_placed and int(m.get("placed_count", 0) or 0) < best_placed * (1.0 - profile.max_placed_loss_ratio):
            reasons.append(f"装载量 {m.get('placed_count')} 箱低于最优 {best_placed} 箱超过 "
                           f"{profile.max_placed_loss_ratio * 100:.0f}%")
        if reasons:
            notes.append(f"{entry.get('label') or entry.get('key')} 不参与推荐：" + "；".join(reasons))
        else:
            eligible.append(entry)

    pool = eligible or [e for e in usable if not e["evaluation"].get("hard_fail")] or usable
    if not eligible:
        notes.append("没有方案同时满足安全底线与业务约束，退回按总分选择（结果需人工确认）")

    def _sort_key(entry: Dict[str, Any]):
        ev = entry["evaluation"]
        m = ev.get("metrics") or {}
        return (
            float(ev.get("score", 0.0) or 0.0),
            float(m.get("rigid_ratio", 0.0) or 0.0),
            float(m.get("utilization_pct", 0.0) or 0.0),
        )

    ordered = sorted(pool, key=_sort_key, reverse=True)
    recommended = ordered[0]

    return {
        "ordered": ordered,
        "recommended_key": recommended.get("key"),
        "policy": profile.key,
        "notes": notes,
    }


def _fmt_delta(value: float, unit: str = "", digits: int = 2) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{digits}f}{unit}"


def compare_plans(base: Dict[str, Any], other: Dict[str, Any],
                  max_items: int = 5) -> List[str]:
    """生成"备选相对推荐"的取舍说明（只列有实际差异的维度）。"""
    bm = base.get("metrics") or {}
    om = other.get("metrics") or {}
    diffs: List[str] = []

    util_d = float(om.get("utilization_pct", 0) or 0) - float(bm.get("utilization_pct", 0) or 0)
    if abs(util_d) >= 0.1:
        diffs.append(f"装载率 {_fmt_delta(util_d, 'pp')} "
                     f"（{bm.get('utilization_pct')}% → {om.get('utilization_pct')}%）")

    placed_d = int(om.get("placed_count", 0) or 0) - int(bm.get("placed_count", 0) or 0)
    if placed_d:
        diffs.append(f"装载件数 {_fmt_delta(placed_d, ' 箱', 0)}")

    rigid_d = (float(om.get("rigid_ratio", 1.0) or 0) - float(bm.get("rigid_ratio", 1.0) or 0)) * 100.0
    if abs(rigid_d) >= 0.1:
        diffs.append(f"刚性履行 {_fmt_delta(rigid_d, 'pp')}")

    b_sf, o_sf = bm.get("door_min_sf"), om.get("door_min_sf")
    if b_sf != o_sf and o_sf is not None:
        b_txt = f"{float(b_sf):.2f}" if b_sf is not None else "无门面"
        diffs.append(f"门面开门 SF {b_txt} → {float(o_sf):.2f}")

    trans_d = float(om.get("transport_unstable_volume_m3", 0) or 0) - float(
        bm.get("transport_unstable_volume_m3", 0) or 0)
    if abs(trans_d) >= 0.05:
        diffs.append(f"运输失稳体积 {_fmt_delta(trans_d, ' m³')}")

    pq_d = float(om.get("plan_quality_score", 0) or 0) - float(bm.get("plan_quality_score", 0) or 0)
    if abs(pq_d) >= 1.0:
        diffs.append(f"方案质量 {_fmt_delta(pq_d, ' 分', 1)}")

    score_d = float(other.get("score", 0) or 0) - float(base.get("score", 0) or 0)
    if abs(score_d) >= 0.1:
        diffs.append(f"综合评分 {_fmt_delta(score_d, ' 分', 1)}")

    return diffs[:max_items]


__all__ = ["evaluate_plan", "rank_plans", "compare_plans"]
