"""PlanScore：对单个方案做可解释评分。

输入是"已经算好的事实"（放置坐标 + 几何体检 + 交付门禁），本模块只负责
把事实翻译成分层分数与扣分原因——不做任何求解，也不改变方案本身。

分层与权重见 spec.py；所有分量都是 0~100，越高越好：
- T0 硬约束：违规/碰撞/门禁 BLOCK —— 一票否决（hard_fail=True，总分 0）
- T1 场景安全：开门面 SF / 运输侧向失稳占比 / 重心偏载
- T2 业务履约：刚性履行率 / 弹性填充率 / 装载顺序可执行
- T3 方案质量：装载率 / 观感评分卡 / 几何总评
- T4 结构稳健：支撑完整度 / 孤立箱 / 隐藏空腔

被谁调用：evaluate.py（统一入口）、tests/test_evaluation_score.py。
"""

import collections
from typing import Any, Dict, Iterable, List, Optional

from backend.solver_v2.evaluation.spec import (
    THRESHOLDS,
    PolicyProfile,
    get_policy,
    grade_for,
)


def _val(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _placement_boxes(placements: Iterable[Any]):
    """统一取出 (x, y, z, dx, dy, dz, sku_id, weight_kg)。"""
    out = []
    for p in placements or []:
        if isinstance(p, dict):
            out.append((
                float(p.get("x", 0.0)), float(p.get("y", 0.0)), float(p.get("z", 0.0)),
                float(p.get("dx", 0.0)), float(p.get("dy", 0.0)), float(p.get("dz", 0.0)),
                str(p.get("sku_id", "")), float(p.get("weight_kg", 0.0) or 0.0),
            ))
        else:
            out.append((
                float(p.position.x), float(p.position.y), float(p.position.z),
                float(p.orientation.dx), float(p.orientation.dy), float(p.orientation.dz),
                str(p.sku_id), float(getattr(p, "weight_kg", 0.0) or 0.0),
            ))
    return out


def _container_volume(container: Any) -> float:
    vol = float(getattr(container, "volume", 0.0) or 0.0)
    if vol > 0:
        return vol
    return max(1e-9, float(getattr(container, "Lx", 0.0) or 0.0)
               * float(getattr(container, "Ly", 0.0) or 0.0)
               * float(getattr(container, "Lz", 0.0) or 0.0))


def _door_open_fallback(boxes, container) -> Dict[str, Any]:
    """与 geometry_qa 同口径的门面整列 SF 复算（qa 缺失时使用）。"""
    result = {"column_count": 0, "unsafe_columns": 0, "min_sf": None,
              "at_risk_volume_m3": 0.0}
    if not boxes:
        return result
    Lx = float(getattr(container, "Lx", 0.0) or 0.0)
    max_x = max(x + dx for (x, _, _, dx, _, _, _, _) in boxes)
    if max_x < Lx - 0.65:
        return result
    cols: Dict[tuple, Dict[str, float]] = {}
    for (x, y, _, dx, dy, dz, _, _) in boxes:
        if max_x - (x + dx) > 1e-3:
            continue
        key = (round(x, 3), round(y, 3))
        e = cols.setdefault(key, {"H": 0.0, "D": 0.0, "vol": 0.0})
        e["H"] += dz
        e["D"] = max(e["D"], dx)
        e["vol"] += dx * dy * dz
    if cols:
        sfs = [(2.0 * e["D"]) / max(e["H"], 1e-6) for e in cols.values()]
        result = {
            "column_count": len(cols),
            "unsafe_columns": sum(1 for s in sfs if s < 1.5 - 1e-6),
            "min_sf": round(min(sfs), 3),
            "at_risk_volume_m3": round(sum(
                e["vol"] for e, s in zip(cols.values(), sfs) if s < 1.5 - 1e-6), 3),
        }
    return result


def _transport_fallback(boxes, container) -> Dict[str, Any]:
    """与 geometry_qa.transport 同口径的侧向失稳复算（qa 缺失时使用）。"""
    from backend.solver_v2.validation.constraint_kernel import lateral_stable

    pls = [
        {"x": x, "y": y, "z": z, "dx": dx, "dy": dy, "dz": dz}
        for (x, y, z, dx, dy, dz, _, _) in boxes
    ]
    Ly = float(getattr(container, "Ly", 0.0) or 0.0)
    Lx = float(getattr(container, "Lx", 0.0) or 0.0)
    stats = {"slender_boxes": 0, "unstable_boxes": 0, "unstable_volume_m3": 0.0}
    for i, (x, y, z, dx, dy, dz, _, _) in enumerate(boxes):
        if dz / max(1e-6, min(dx, dy)) > 2.0:
            stats["slender_boxes"] += 1
        if lateral_stable(pls[i], pls, Ly, Lx):
            continue
        stats["unstable_boxes"] += 1
        stats["unstable_volume_m3"] += dx * dy * dz
    stats["unstable_volume_m3"] = round(stats["unstable_volume_m3"], 3)
    return stats


def _cog(boxes, container, cargo_volume: float) -> Dict[str, float]:
    """按体积加权重心（与门禁 DG-011/014 同口径的偏移百分比）。"""
    if not boxes or cargo_volume <= 0:
        return {"long_offset_pct": 0.0, "lat_offset_pct": 0.0, "height_pct": 0.0}
    Lx = max(1e-9, float(getattr(container, "Lx", 0.0) or 0.0))
    Ly = max(1e-9, float(getattr(container, "Ly", 0.0) or 0.0))
    Lz = max(1e-9, float(getattr(container, "Lz", 0.0) or 0.0))
    cx = cy = cz = 0.0
    for (x, y, z, dx, dy, dz, _, _) in boxes:
        v = dx * dy * dz
        cx += (x + dx / 2.0) * v
        cy += (y + dy / 2.0) * v
        cz += (z + dz / 2.0) * v
    cx /= cargo_volume
    cy /= cargo_volume
    cz /= cargo_volume
    return {
        "long_offset_pct": round(abs(cx - Lx / 2.0) / Lx * 100.0, 2),
        "lat_offset_pct": round(abs(cy - Ly / 2.0) / Ly * 100.0, 2),
        "height_pct": round(cz / Lz * 100.0, 2),
    }


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _high_score(value: float, bad: float, good: float) -> float:
    """value 从 bad→good 线性映射到 0→100。"""
    return _clamp(100.0 * (value - bad) / max(1e-9, good - bad))


def _low_score(value: float, good: float, bad: float) -> float:
    """value 从 good→bad 线性映射到 100→0。"""
    return _clamp(100.0 * (bad - value) / max(1e-9, bad - good))


def _door_sf_score(sf: Optional[float], min_sf: float) -> float:
    """门面 SF 的评分：底线之上给 60~100，底线之下快速归零。"""
    if sf is None:
        return 100.0
    if sf >= THRESHOLDS["door_sf_full"]:
        return 100.0
    if sf >= min_sf:
        span = max(1e-6, THRESHOLDS["door_sf_full"] - min_sf)
        return _clamp(60.0 + 40.0 * (sf - min_sf) / span)
    return _clamp(60.0 * max(0.0, sf) / max(1e-6, min_sf))


def _fulfillment_stats(cargo_list, boxes) -> Dict[str, Any]:
    by_sku: Dict[str, int] = collections.Counter(sid for (_, _, _, _, _, _, sid, _) in boxes)
    rigid_req = rigid_placed = elastic_req = elastic_placed = 0
    starved: List[str] = []
    elastic_skus: List[str] = []
    for c in cargo_list or []:
        sid = str(getattr(c, "sku_id", ""))
        req = int(getattr(getattr(c, "quantity", None), "required", 0)
                  or getattr(c, "quantity_required", 0) or 0)
        is_elastic = bool(
            getattr(getattr(c, "quantity", None), "is_elastic", False)
            or getattr(c, "is_elastic", False)
        )
        placed = int(by_sku.get(sid, 0))
        if is_elastic:
            elastic_req += req
            elastic_placed += min(req, placed)
            if placed > 0:
                elastic_skus.append(sid)
        else:
            rigid_req += req
            rigid_placed += min(req, placed)
            if req > 0 and placed == 0:
                starved.append(sid)
    return {
        "rigid_required": rigid_req,
        "rigid_placed": rigid_placed,
        "rigid_ratio": (rigid_placed / rigid_req) if rigid_req else 1.0,
        "rigid_gap": max(0, rigid_req - rigid_placed),
        "elastic_required": elastic_req,
        "elastic_placed": elastic_placed,
        "elastic_ratio": (elastic_placed / elastic_req) if elastic_req else 1.0,
        "starved_rigid_skus": starved,
        "elastic_skus_placed": len(elastic_skus),
        "placed_by_sku": dict(by_sku),
    }


def score_plan(
    placements: Iterable[Any],
    cargo_list: List[Any],
    container: Any,
    *,
    qa: Optional[Dict[str, Any]] = None,
    gate: Optional[Dict[str, Any]] = None,
    validation_result: Any = None,
    sequence_feasible: Optional[bool] = None,
    policy: Any = None,
) -> Dict[str, Any]:
    """对方案评分并给出可解释扣分项。

    qa/gate 可显式传入（推荐，避免重复计算）；缺省时按放置坐标复算
    门面 SF 与运输失稳。validation_result 缺省视为"无硬违规"。
    """
    profile: PolicyProfile = policy if isinstance(policy, PolicyProfile) else get_policy(policy)
    boxes = _placement_boxes(placements)
    container_vol = _container_volume(container)
    cargo_volume = sum(dx * dy * dz for (_, _, _, dx, dy, dz, _, _) in boxes)
    util_pct = 100.0 * cargo_volume / max(1e-9, container_vol)
    qa = qa or {}
    gate = gate or {}

    # ---------------- T0 硬约束 ----------------
    violations = list(getattr(validation_result, "violations", None) or []) if validation_result else []
    overlap_pairs = int(getattr(validation_result, "overlap_pair_count", 0) or 0) if validation_result else 0
    blocked_by = list(gate.get("blocked_by") or [])
    hard_fail = bool(violations or overlap_pairs or blocked_by)
    t0_reasons: List[str] = []
    if violations:
        t0_reasons.append(f"独立验证违规 {len(violations)} 条")
    if overlap_pairs:
        t0_reasons.append(f"货物碰撞 {overlap_pairs} 对")
    if blocked_by:
        t0_reasons.append(f"交付门禁 BLOCK：{','.join(blocked_by)}")

    # ---------------- T1 场景安全 ----------------
    door = qa.get("door_open")
    if door is None:
        door = _door_open_fallback(boxes, container)
    transport = qa.get("transport")
    if transport is None:
        transport = _transport_fallback(boxes, container)
    cog = (gate.get("cog") or {}) if gate else {}
    if not cog:
        cog = _cog(boxes, container, cargo_volume)

    min_sf = door.get("min_sf")
    unstable_vol = float(transport.get("unstable_volume_m3", 0.0) or 0.0)
    unstable_ratio = unstable_vol / max(1e-9, cargo_volume) if cargo_volume > 0 else 0.0
    door_score = _door_sf_score(min_sf, profile.door_min_sf)
    transport_score = _low_score(
        unstable_ratio,
        THRESHOLDS["transport_ratio_good"],
        THRESHOLDS["transport_ratio_bad"],
    )
    cog_offset = max(float(cog.get("long_offset_pct", 0.0) or 0.0),
                     float(cog.get("lat_offset_pct", 0.0) or 0.0))
    cog_score = _low_score(
        cog_offset,
        THRESHOLDS["cog_offset_good_pct"],
        THRESHOLDS["cog_offset_bad_pct"],
    )
    if door.get("column_count", 0) > 0:
        t1_weights = {"door": 0.5, "transport": 0.3, "cog": 0.2}
    else:
        t1_weights = {"door": 0.0, "transport": 0.6, "cog": 0.4}
    t1_total_w = sum(t1_weights.values()) or 1.0
    t1_score = (
        door_score * t1_weights["door"]
        + transport_score * t1_weights["transport"]
        + cog_score * t1_weights["cog"]
    ) / t1_total_w

    # ---------------- T2 业务履约 ----------------
    ful = _fulfillment_stats(cargo_list, boxes)
    sequence_measured = sequence_feasible is not None
    if sequence_measured:
        seq_score = THRESHOLDS["sequence_score"] if sequence_feasible else 0.0
        t2_score = (
            0.60 * ful["rigid_ratio"] * 100.0
            + 0.30 * ful["elastic_ratio"] * 100.0
            + 0.10 * seq_score
        )
    else:
        # 未测量时不给满分，也不假装失败：在剩余两项上重新归一
        seq_score = None
        t2_score = (
            0.65 * ful["rigid_ratio"] * 100.0
            + 0.35 * ful["elastic_ratio"] * 100.0
        )

    # ---------------- T3 方案质量 ----------------
    pq = qa.get("plan_quality") or {}
    pq_score = float(pq.get("score", 100.0) if pq else 100.0)
    geom_verdict = str(qa.get("verdict") or "GOOD").upper()
    geom_score = {
        "GOOD": THRESHOLDS["geometry_good"],
        "FAIR": THRESHOLDS["geometry_fair"],
        "POOR": THRESHOLDS["geometry_poor"],
    }.get(geom_verdict, 100.0)
    util_score = _high_score(
        util_pct, THRESHOLDS["util_floor_pct"], THRESHOLDS["util_ceil_pct"])
    t3_score = 0.45 * util_score + 0.35 * pq_score + 0.20 * geom_score

    # ---------------- T4 结构稳健 ----------------
    support = qa.get("support") or {}
    partial_pct = float(support.get("partial_support_ratio_pct", 0.0) or 0.0)
    islands = int(qa.get("islands", 0) or 0)
    hidden_pct = float((qa.get("cavities") or {}).get("hidden_void_pct_of_bbox", 0.0) or 0.0)
    support_score = _clamp(100.0 - partial_pct * THRESHOLDS["support_penalty_per_pct"])
    island_score = _clamp(100.0 - islands * THRESHOLDS["island_penalty"])
    hidden_score = _clamp(100.0 - hidden_pct * THRESHOLDS["hidden_void_penalty_per_pct"])
    t4_score = 0.50 * support_score + 0.25 * island_score + 0.25 * hidden_score

    weights = profile.weights.normalized()
    total = (
        t1_score * weights.safety
        + t2_score * weights.fulfillment
        + t3_score * weights.quality
        + t4_score * weights.robustness
    )
    if hard_fail:
        total = 0.0
    total = round(total, 1)

    # ---------------- 扣分解释（业务可读）----------------
    deductions: List[str] = []
    if min_sf is not None and min_sf < profile.door_min_sf:
        deductions.append(
            f"开门工况门面 SF {min_sf:.2f} < {profile.door_min_sf}（{door.get('unsafe_columns', 0)} 列，"
            f"风险体积 {door.get('at_risk_volume_m3', 0):.2f} m³）"
        )
    if unstable_ratio > THRESHOLDS["transport_ratio_good"]:
        deductions.append(
            f"运输侧向失稳 {unstable_vol:.2f} m³（占货量 {unstable_ratio*100:.1f}%，"
            f"{transport.get('unstable_boxes', 0)} 箱）"
        )
    if cog_offset > THRESHOLDS["cog_offset_good_pct"]:
        deductions.append(f"重心偏移 {cog_offset:.1f}%（纵 {cog.get('long_offset_pct', 0)}% / 横 {cog.get('lat_offset_pct', 0)}%）")
    if ful["rigid_ratio"] < 0.999:
        deductions.append(
            f"刚性履行 {ful['rigid_ratio']*100:.1f}%（缺口 {ful['rigid_gap']} 箱）"
        )
    if ful["elastic_required"] and ful["elastic_ratio"] < 1.0:
        deductions.append(
            f"弹性填充 {ful['elastic_placed']}/{ful['elastic_required']}（{ful['elastic_ratio']*100:.0f}%）"
        )
    if sequence_feasible is False:
        deductions.append("装载顺序不可执行（存在依赖环）")
    if pq and pq_score < 65.0:
        deductions.append(f"方案质量评分 {pq_score:.0f}（{pq.get('grade', '?')} 级）")
    if geom_verdict == "POOR":
        deductions.append(f"几何总评 POOR（惩罚分 {qa.get('penalty_score', '?')}）")
    if islands > 6:
        deductions.append(f"孤立箱 {islands} 个")
    if hidden_pct > 2.0:
        deductions.append(f"隐藏空腔占包围盒 {hidden_pct:.1f}%")

    tiers = {
        "T0": {"score": 0.0 if hard_fail else 100.0, "passed": not hard_fail,
               "reasons": t0_reasons},
        "T1": {"score": round(t1_score, 1), "components": {
            "door_open_sf": door_score, "transport_lateral": transport_score,
            "cog_balance": cog_score}, "passed": (
                (min_sf is None or min_sf >= profile.door_min_sf)
                and unstable_ratio <= profile.transport_max_unstable_ratio)},
        "T2": {"score": round(t2_score, 1), "components": {
            "rigid_fulfillment": round(ful["rigid_ratio"] * 100.0, 2),
            "elastic_fill": round(ful["elastic_ratio"] * 100.0, 2),
            "loading_sequence": (round(seq_score, 1) if seq_score is not None else None)},
            "passed": ful["rigid_ratio"] >= 0.99},
        "T3": {"score": round(t3_score, 1), "components": {
            "utilization": round(util_score, 1),
            "plan_quality": round(pq_score, 1),
            "geometry_verdict": round(geom_score, 1)}},
        "T4": {"score": round(t4_score, 1), "components": {
            "support": round(support_score, 1),
            "islands": round(island_score, 1),
            "hidden_void": round(hidden_score, 1)}},
    }

    metrics = {
        "placed_count": len(boxes),
        "cargo_volume_m3": round(cargo_volume, 3),
        "utilization_pct": round(util_pct, 2),
        "rigid_ratio": round(ful["rigid_ratio"], 4),
        "rigid_gap": ful["rigid_gap"],
        "elastic_placed": ful["elastic_placed"],
        "elastic_required": ful["elastic_required"],
        "starved_rigid_skus": ful["starved_rigid_skus"],
        "door_min_sf": min_sf,
        "door_unsafe_columns": door.get("unsafe_columns", 0),
        "door_at_risk_volume_m3": door.get("at_risk_volume_m3", 0.0),
        "transport_unstable_boxes": transport.get("unstable_boxes", 0),
        "transport_unstable_volume_m3": round(unstable_vol, 3),
        "transport_unstable_ratio": round(unstable_ratio, 4),
        "cog_offset_pct": cog_offset,
        "plan_quality_score": round(pq_score, 1),
        "plan_quality_grade": pq.get("grade"),
        "geometry_verdict": geom_verdict,
        "islands": islands,
        "hidden_void_pct": round(hidden_pct, 2),
        "sequence_feasible": (None if sequence_feasible is None else bool(sequence_feasible)),
        "sequence_measured": bool(sequence_measured),
    }

    return {
        "policy": profile.key,
        "policyLabel": profile.label,
        "score": total,
        "grade": grade_for(total, hard_fail),
        "hard_fail": hard_fail,
        "weights": {
            "safety": round(weights.safety, 3),
            "fulfillment": round(weights.fulfillment, 3),
            "quality": round(weights.quality, 3),
            "robustness": round(weights.robustness, 3),
        },
        "tiers": tiers,
        "metrics": metrics,
        "deductions": deductions,
        "summary": _build_summary(total, hard_fail, metrics, deductions, profile),
    }


def _build_summary(total: float, hard_fail: bool, metrics: Dict[str, Any],
                   deductions: List[str], profile: PolicyProfile) -> str:
    if hard_fail:
        return f"方案作废：{('；'.join(deductions[:2]) or '未通过硬约束')}"
    head = (
        f"{profile.label} {total:.1f} 分 · 装载 {metrics['placed_count']} 箱 / "
        f"{metrics['utilization_pct']:.1f}% · 刚性 {metrics['rigid_ratio']*100:.1f}%"
    )
    if deductions:
        return head + "｜扣分：" + "；".join(deductions[:3])
    return head + "｜无扣分项"


__all__ = ["score_plan"]
