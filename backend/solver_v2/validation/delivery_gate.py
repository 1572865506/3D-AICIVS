"""
交付门禁（Delivery Gate）——求解结果在"交付"前必须通过的独立质检关卡。

设计原则：
1. 独立于求解器：只读取 placements + 独立验证器结果 + 几何体检，不采信求解器自述；
2. 可解释：每条规则有 ID、实测值、阈值、是否通过、受影响对象；
3. 分级：BLOCK（必须拦截交付） / WARN（提示但可交付）；
4. 可配置：阈值在 config/delivery_gate.json，业务方可调，但属于"交付政策"而非算法参数。

规则清单：
- DG-001 硬约束违规（独立验证器）        BLOCK
- DG-002 碰撞/穿插                        BLOCK
- DG-003 载重超限                        BLOCK
- DG-004 刚性 SKU 饥饿（有件却 0 放置）  BLOCK
- DG-005 履约率（货物体积可装下时）      BLOCK
- DG-006 隐蔽空洞（柱顶以下的洞）        WARN
- DG-007 装载体包围盒空洞率              WARN
- DG-008 顶面硬台阶占比                  WARN
- DG-009 半悬空箱占比                    WARN
- DG-010 孤立箱                          WARN
- DG-011 重心严重偏载（纵向/横向）      BLOCK
- DG-012 不可解释空腔（无成因分类）       BLOCK
- DG-013 装载顺序可行性                  WARN
- DG-014 重心偏载提示（轻于 DG-011）      WARN

被谁调用：LoadingAPIService.register_solver_output（写入 metrics.delivery_gate）、
交付脚本/CI（作为放行判据）。
"""
import json
import os
from typing import Any, Dict, List, Optional

POLICY_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "delivery_gate.json")

DEFAULT_POLICY: Dict[str, Any] = {
    "_doc": "交付门禁策略。阈值属于交付政策（业务可调），不属于算法参数。"
            "severity=BLOCK 表示不通过则拒绝交付；WARN 表示提示。",
    "rules": {
        "DG-001": {"severity": "BLOCK", "name": "硬约束违规"},
        "DG-002": {"severity": "BLOCK", "name": "碰撞/穿插"},
        "DG-003": {"severity": "BLOCK", "name": "载重超限"},
        "DG-004": {"severity": "BLOCK", "name": "刚性SKU饥饿"},
        "DG-005": {"severity": "BLOCK", "name": "履约率", "min_fulfillment": 0.99,
                   "trigger_fillable_ratio": 0.95},
        "DG-006": {"severity": "WARN", "name": "隐蔽空洞", "max_hidden_void_pct": 3.0},
        "DG-007": {"severity": "WARN", "name": "包围盒空洞率(参考)", "max_bbox_void_pct": 60.0},
        "DG-008": {"severity": "WARN", "name": "顶面硬台阶", "max_steep_step_pct": 15.0},
        "DG-009": {"severity": "WARN", "name": "半悬空箱", "max_partial_support_pct": 5.0},
        "DG-010": {"severity": "WARN", "name": "孤立箱", "max_islands": 0},
        "DG-011": {"severity": "BLOCK", "name": "重心严重偏载", "max_cog_long_pct": 20.0,
                   "max_cog_lat_pct": 10.0},
        "DG-012": {"severity": "BLOCK", "name": "不可解释空腔", "max_unexplained": 0},
        "DG-013": {"severity": "WARN", "name": "装载顺序可行性"},
        "DG-014": {"severity": "WARN", "name": "重心偏载提示", "max_cog_long_pct": 10.0,
                   "max_cog_lat_pct": 5.0},
    },
}


def load_policy(path: Optional[str] = None) -> Dict[str, Any]:
    """读取策略文件；缺失则回退默认策略（不因缺文件而阻断交付判定）。"""
    p = path or POLICY_PATH
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = {"_doc": DEFAULT_POLICY.get("_doc"), "rules": dict(DEFAULT_POLICY["rules"])}
        for rid, cfg in (data.get("rules") or {}).items():
            if rid in merged["rules"]:
                merged["rules"][rid].update(cfg)
            else:
                merged["rules"][rid] = cfg
        return merged
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_POLICY


def _compute_cog(container: Any, placements: List[Any]) -> Dict[str, float]:
    """按重量加权计算三维重心及其相对柜体中心的偏移百分比。"""
    total_w = 0.0
    mx = my = mz = 0.0
    for p in placements:
        if isinstance(p, dict):
            x, y, z = p["x"], p["y"], p["z"]
            dx, dy, dz = p["dx"], p["dy"], p["dz"]
            w = p.get("weight_kg", 0.0)
        else:
            x, y, z = p.position.x, p.position.y, p.position.z
            dx, dy, dz = p.orientation.dx, p.orientation.dy, p.orientation.dz
            w = p.weight_kg
        cw = max(0.0, w)
        total_w += cw
        mx += (x + dx / 2) * cw
        my += (y + dy / 2) * cw
        mz += (z + dz / 2) * cw
    if total_w <= 1e-9:
        return {"cog_x_pct": 0.0, "cog_y_pct": 0.0, "cog_z_pct": 0.0,
                "long_offset_pct": 0.0, "lat_offset_pct": 0.0, "total_weight_kg": 0.0}
    cx, cy, cz = mx / total_w, my / total_w, mz / total_w
    return {
        "cog_x_pct": round(100.0 * cx / max(1e-9, container.Lx), 2),
        "cog_y_pct": round(100.0 * cy / max(1e-9, container.Ly), 2),
        "cog_z_pct": round(100.0 * cz / max(1e-9, container.Lz), 2),
        "long_offset_pct": round(abs(100.0 * cx / max(1e-9, container.Lx) - 50.0), 2),
        "lat_offset_pct": round(abs(100.0 * cy / max(1e-9, container.Ly) - 50.0), 2),
        "total_weight_kg": round(total_w, 2),
    }


def evaluate_delivery(
    solution: Any,
    cargo_list: List[Any],
    container: Any = None,
    geometry_qa: Optional[Dict[str, Any]] = None,
    cavity_diagnostics: Optional[List[Dict[str, Any]]] = None,
    policy: Optional[Dict[str, Any]] = None,
    sequence_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    执行交付门禁，返回结构化质检报告。

    参数：
    - solution：SolverSolution（读取 placements / validation_result / 重量）
    - cargo_list：原始货单（CargoSKU 列表，用于履约与饥饿判定）
    - container：ContainerSpec（缺省取 solution.container）
    - geometry_qa / cavity_diagnostics：缺省从 solution.telemetry 读取

    返回：{verdict: PASS|WARN|REJECT, checks: [...], blocked_by: [ids], warnings: [ids],
          cog: {...}, summary: str}
    """
    pol = policy or load_policy()
    rules = pol["rules"]
    cont = container or getattr(solution, "container", None)
    qa = geometry_qa if geometry_qa is not None else getattr(
        getattr(solution, "telemetry", None), "geometry_qa", None)
    cavs = cavity_diagnostics if cavity_diagnostics is not None else (
        getattr(getattr(solution, "telemetry", None), "cavity_diagnostics", None) or [])
    placements = list(getattr(solution, "placements", []) or [])
    val = getattr(solution, "validation_result", None)

    checks: List[Dict[str, Any]] = []

    def add(rid: str, measured: Any, limit: Any, passed: bool, detail: str = "") -> None:
        cfg = rules.get(rid, {"severity": "WARN", "name": rid})
        checks.append({
            "id": rid,
            "name": cfg.get("name", rid),
            "severity": cfg.get("severity", "WARN"),
            "measured": measured,
            "limit": limit,
            "passed": bool(passed),
            "detail": detail,
        })

    # DG-001 硬约束违规
    violations = list(getattr(val, "violations", []) or [])
    add("DG-001", len(violations), 0, len(violations) == 0,
        "；".join(f"{getattr(v.violation_type, 'name', '?')}:{getattr(v, 'placement_id', '?')}"
                 for v in violations[:3]))

    # DG-002 碰撞
    pairs = int(getattr(val, "overlap_pair_count", 0) or 0)
    add("DG-002", pairs, 0, pairs == 0)

    # DG-003 载重
    total_w = sum((p.weight_kg if not isinstance(p, dict) else p.get("weight_kg", 0.0)) for p in placements)
    max_payload = getattr(cont, "max_payload_kg", None)
    if max_payload:
        add("DG-003", round(total_w, 1), max_payload, total_w <= max_payload + 1e-6)
    else:
        add("DG-003", round(total_w, 1), None, True, "柜体未声明载重上限")

    # DG-004 刚性饥饿（有需求却 0 放置）
    placed_by_sku: Dict[str, int] = {}
    for p in placements:
        sid = p.sku_id if not isinstance(p, dict) else p["sku_id"]
        placed_by_sku[sid] = placed_by_sku.get(sid, 0) + 1
    starved: List[str] = []
    required_total = 0
    placed_total = len(placements)
    for c in cargo_list:
        req = getattr(getattr(c, "quantity", None), "required", 0) or 0
        is_elastic = bool(getattr(getattr(c, "quantity", None), "is_elastic", False))
        required_total += req
        if not is_elastic and req > 0 and placed_by_sku.get(c.sku_id, 0) == 0:
            starved.append(c.sku_id)
    add("DG-004", len(starved), 0, not starved, f"饥饿: {starved[:5]}" if starved else "")

    # DG-005 履约率（仅在"体积可装下"时强制）
    cargo_vol = sum(
        (p.orientation.dx * p.orientation.dy * p.orientation.dz) if not isinstance(p, dict)
        else (p["dx"] * p["dy"] * p["dz"])
        for p in placements
    )
    req_vol = 0.0
    for c in cargo_list:
        box = getattr(c, "box", None)
        req = getattr(getattr(c, "quantity", None), "required", 0) or 0
        if box is not None:
            req_vol += box.x * box.y * box.z * req
    cfg5 = rules["DG-005"]
    fillable_ratio = req_vol / max(1e-9, getattr(cont, "volume", 1e9))
    # 载重受限货单（请求总重超过柜体载重上限）无法全装属物理必然，
    # 履约率不设硬门槛，避免把合规的"装不完"误判为不可交付。
    _req_weight = 0.0
    for c in cargo_list:
        _req_weight += float(getattr(c, "weight_kg", 0.0) or 0.0) * (
            getattr(getattr(c, "quantity", None), "required", 0) or 0)
    _payload_cap = getattr(cont, "max_payload_kg", None)
    _payload_limited = bool(_payload_cap) and _req_weight > float(_payload_cap)
    if fillable_ratio <= cfg5.get("trigger_fillable_ratio", 0.95) and required_total > 0 and not _payload_limited:
        fulfillment = placed_total / max(1, required_total)
        add("DG-005", round(100.0 * fulfillment, 2), round(100.0 * cfg5["min_fulfillment"], 2),
            fulfillment >= cfg5["min_fulfillment"],
            f"请求体积占柜容 {fillable_ratio*100:.0f}%（可装下，强制履约）")
    else:
        add("DG-005", round(100.0 * placed_total / max(1, required_total), 2), None, True,
            f"请求体积占柜容 {fillable_ratio*100:.0f}%，请求总重 {_req_weight:.0f}kg"
            + (f" > 柜限 {_payload_cap:.0f}kg（载重受限，不设硬门槛）" if _payload_limited else "（超载，履约率不设硬门槛）"))

    # DG-006~010 几何观感
    if qa:
        cav = qa.get("cavities", {})
        add("DG-006", cav.get("hidden_void_pct_of_bbox", 0.0), rules["DG-006"]["max_hidden_void_pct"],
            cav.get("hidden_void_pct_of_bbox", 0.0) <= rules["DG-006"]["max_hidden_void_pct"])
        add("DG-007", qa.get("bbox_void_ratio_pct", 0.0), rules["DG-007"]["max_bbox_void_pct"],
            qa.get("bbox_void_ratio_pct", 0.0) <= rules["DG-007"]["max_bbox_void_pct"])
        ts = qa.get("top_surface", {})
        add("DG-008", ts.get("steep_step_ratio_pct", 0.0), rules["DG-008"]["max_steep_step_pct"],
            ts.get("steep_step_ratio_pct", 0.0) <= rules["DG-008"]["max_steep_step_pct"])
        sup = qa.get("support", {})
        add("DG-009", sup.get("partial_support_ratio_pct", 0.0), rules["DG-009"]["max_partial_support_pct"],
            sup.get("partial_support_ratio_pct", 0.0) <= rules["DG-009"]["max_partial_support_pct"])
        add("DG-010", qa.get("islands", 0), rules["DG-010"]["max_islands"],
            qa.get("islands", 0) <= rules["DG-010"]["max_islands"])
    else:
        for rid in ("DG-006", "DG-007", "DG-008", "DG-009", "DG-010"):
            add(rid, None, None, True, "无几何体检数据，跳过")

    # DG-011 重心严重偏载（BLOCK） / DG-014 偏载提示（WARN）
    # 政策例外：若货单含"封柜门/放最里面"等区域强制要求，偏载是业务约束的必然结果，
    # DG-011 降级为 WARN（仍提示但不拦截交付），避免把合规装载误判为不可交付。
    _zone_pinned = False
    for c in cargo_list:
        tz = getattr(getattr(c, "target_zone", None), "value", None)
        if tz in ("REAR", "DOOR"):
            _zone_pinned = True
            break
        roles = getattr(c, "packing_roles", ()) or ()
        if any(getattr(r, "value", str(r)) == "DOOR_SEAL" for r in roles):
            _zone_pinned = True
            break
        req_text = getattr(c, "source_requirement_text", "") or ""
        if any(k in req_text for k in ("最里面", "封柜门", "封门")):
            _zone_pinned = True
            break
    cog = _compute_cog(cont, placements) if cont is not None else {}
    if cog:
        c11 = rules["DG-011"]
        severe = (cog["long_offset_pct"] > c11["max_cog_long_pct"]
                  or cog["lat_offset_pct"] > c11["max_cog_lat_pct"])
        if severe and _zone_pinned:
            add("DG-011", {"long_pct": cog["long_offset_pct"], "lat_pct": cog["lat_offset_pct"]},
                {"long_pct": c11["max_cog_long_pct"], "lat_pct": c11["max_cog_lat_pct"]},
                False, "区域强制（封柜门/最里面）导致的偏载：按政策降级为提示")
            checks[-1]["severity"] = "WARN"
        else:
            add("DG-011", {"long_pct": cog["long_offset_pct"], "lat_pct": cog["lat_offset_pct"]},
                {"long_pct": c11["max_cog_long_pct"], "lat_pct": c11["max_cog_lat_pct"]},
                not severe)
        c14 = rules["DG-014"]
        add("DG-014", {"long_pct": cog["long_offset_pct"], "lat_pct": cog["lat_offset_pct"]},
            {"long_pct": c14["max_cog_long_pct"], "lat_pct": c14["max_cog_lat_pct"]},
            cog["long_offset_pct"] <= c14["max_cog_long_pct"]
            and cog["lat_offset_pct"] <= c14["max_cog_lat_pct"])

    # DG-012 不可解释空腔
    unexplained = sum(1 for c in cavs if not c.get("exclusion_category"))
    add("DG-012", unexplained, rules["DG-012"]["max_unexplained"],
        unexplained <= rules["DG-012"]["max_unexplained"])

    # DG-013 装载顺序可执行性（由 API 层通过 sequence_report 传入真实拓扑结果；
    # 未传时退回 loading_plan 标记，避免门禁自身依赖几何重算）
    _seq = sequence_report or {}
    if _seq:
        seq_ok = bool(_seq.get("feasible", True))
        add("DG-013", "feasible" if seq_ok else f"cycles={len(_seq.get('cycles') or [])}",
            "feasible", seq_ok,
            f"装载顺序依赖边 {_seq.get('edge_count')}；"
            f"旧枚举顺序受阻 {_seq.get('blocked_in_naive_order')} 箱")
    else:
        seq_ok = bool(getattr(getattr(solution, "loading_plan", None), "sequence_feasible", True))
        add("DG-013", "feasible" if seq_ok else "infeasible", "feasible", seq_ok,
            "未提供装载顺序报告，仅用 plan 标记")

    blocked = [c["id"] for c in checks if not c["passed"] and c["severity"] == "BLOCK"]
    warned = [c["id"] for c in checks if not c["passed"] and c["severity"] == "WARN"]
    verdict = "REJECT" if blocked else ("WARN" if warned else "PASS")
    summary = (
        f"交付门禁: {verdict} | 拦截 {len(blocked)} 项 {blocked} | 告警 {len(warned)} 项 {warned}"
    )
    return {
        "verdict": verdict,
        "checks": checks,
        "blocked_by": blocked,
        "warnings": warned,
        "cog": cog,
        "summary": summary,
    }
