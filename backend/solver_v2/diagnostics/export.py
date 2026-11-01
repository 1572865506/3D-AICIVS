"""
几何诊断导出模块（结构审计任务 §3 输入规范）。

用途：将一次求解终态的全部结构化几何诊断聚合为单一 JSON 可导出对象，
供"修复-回归"振荡审计的归因工作流消费（表 C 候选生命周期追踪、
棘轮不变量核查、空腔排除类别分布统计）。

输入：SolverSolution（含 telemetry.placement_diagnostics /
telemetry.cavity_diagnostics / telemetry.candidates_rejected_by_reason）、
case_id、可选的求解前基线诊断。

输出：dict，结构见 export_diagnostics_bundle docstring；可直接
json.dump 到 artifacts/（.gitignore 已忽略该目录）。

被谁调用：诊断驱动脚本 / tests（本轮为表 C 追踪提供数据源）。

说明（渲染网格包围盒 vs 算法 AABB 偏差）：前端 scene 数据与算法
placements 出自同一份 dict 数据流（backend/api/adapters/scene_adapter.py
直接读取 x/y/z/dx/dy/dz，无独立网格量化/原点平移），结构性偏差为 0，
故本模块仅输出 schema 声明字段 render_mesh_aabb_deviation 恒为 0 并附
same_source=True 标记；若未来前端引入网格简化，需在此处补实测。
"""
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional


def export_diagnostics_bundle(
    solution: Any,
    case_id: str = "unknown",
    output_dir: Optional[str] = None,
    baseline: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    聚合并导出几何诊断束。

    返回结构：
    {
      "case_id": str,
      "generated_at": ISO 时间,
      "placement_summary": {placed, unplaced, utilization_pct, status},
      "per_box": [placement_diagnostics 原样展开, 附 placement_id],
      "support_anomalies": {disconnected_boxes, low_ratio_boxes, overloaded_boxes},
      "cavities": [telemetry.cavity_diagnostics 原样],
      "cavity_category_distribution": {类别: 数量},
      "rejection_reason_distribution": {过滤器名: 次数},
      "ratchet_snapshot": {hard_violations, unexplained_cavities},
      "render_mesh_aabb_deviation": {"max_dim_delta_m": 0.0, "same_source": True},
    }
    """
    telemetry = getattr(solution, "telemetry", None)
    plc_diag: Dict[str, Dict[str, Any]] = getattr(telemetry, "placement_diagnostics", {}) or {}
    cavities: list = getattr(telemetry, "cavity_diagnostics", []) or []
    rejections: Dict[str, int] = dict(getattr(telemetry, "candidates_rejected_by_reason", {}) or {})

    per_box = [{"placement_id": pid, **diag} for pid, diag in plc_diag.items()]

    disconnected = [b["placement_id"] for b in per_box if not b.get("is_connected", True)]
    low_ratio = [b["placement_id"] for b in per_box if b.get("support_ratio", 1.0) < 0.70 - 1e-4]
    overloaded = [b["placement_id"] for b in per_box if b.get("bearing_margin_kg", 1e9) < -1e-4]

    cat_dist: Dict[str, int] = {}
    for cav in cavities:
        cat = cav.get("exclusion_category", "UNCLASSIFIED")
        cat_dist[cat] = cat_dist.get(cat, 0) + 1

    val = getattr(solution, "validation_result", None)
    hard_violations = len(getattr(val, "violations", []) or [])

    bundle: Dict[str, Any] = {
        "case_id": case_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "placement_summary": {
            "placed": getattr(solution, "placed_count", None),
            "unplaced": getattr(solution, "unplaced_count", None),
            "utilization_pct": getattr(solution, "volume_utilization_pct", None),
            "status": getattr(solution, "status", None),
        },
        "per_box": per_box,
        "support_anomalies": {
            "disconnected_boxes": disconnected,
            "low_ratio_boxes": low_ratio,
            "overloaded_boxes": overloaded,
        },
        "cavities": cavities,
        "cavity_category_distribution": cat_dist,
        "rejection_reason_distribution": rejections,
        "ratchet_snapshot": {
            "hard_violations": hard_violations,
            # 不可解释空洞 = 无 exclusion_category 的空腔（分类器覆盖盲区将在此显形）
            "unexplained_cavities": sum(1 for c in cavities if not c.get("exclusion_category")),
        },
        "render_mesh_aabb_deviation": {"max_dim_delta_m": 0.0, "same_source": True},
    }
    if baseline:
        bundle["baseline"] = baseline

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"geometry_diagnostics_{case_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, ensure_ascii=False, indent=1)
        bundle["exported_path"] = path

    return bundle
