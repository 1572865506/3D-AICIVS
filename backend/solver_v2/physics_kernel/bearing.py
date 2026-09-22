# -*- coding: utf-8 -*-
"""
垂直承重极限与表面压强检查纯函数 (Bearing Weight & Surface Pressure)

与 IndependentGlobalValidator 第 8 维审计完全同构:
  - 物理多层向下传力 Load Propagation DAG 模型
  - 接触投影面积比精确分摊上层自重与传递载荷: contact_frac = contact_area / u_base_area
  - 下层箱体累计承重核限: accum_upper_weight <= max_bearing_kg
  - 下层箱体表面压强核限: pressure = accum_upper_weight / (dx * dy) <= max_pressure_kg_m2

所有函数均为纯函数, 幂等无副作用。

被谁调用:
  - physics_kernel/__init__.py 统一导出
  - physics_kernel/unified_gate.py 聚合放置预检
  - placement_engine/ 任何放置引擎
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple, Union
from .collision import GEOM_EPSILON, normalize_box

Z_CONTACT_TOL: float = 1e-3


def check_bearing_capacity(
    candidate: Union[Dict[str, Any], Any],
    placements: List[Union[Dict[str, Any], Any]],
    cargo_specs: Dict[str, Any],
    epsilon: float = GEOM_EPSILON,
) -> Tuple[bool, Optional[str]]:
    """检查放入候选箱体后，其下方所有受力箱体的承重与压强是否依然合规。

    数学标准与 IndependentGlobalValidator._validate_rules_and_physics 承重与压强审计完全同构。

    Args:
        candidate: 候选放置 (字典或 Placement)。
        placements: 已放置列表 (字典或 Placement 列表)。
        cargo_specs: SKU 规格字典 (sku_id -> CargoSKU)。
        epsilon: 几何精度容差。

    Returns:
        (is_ok, reason): is_ok=True 表示垂直承重与压强完全合规。
    """
    cand = normalize_box(candidate)
    cand_z = cand["z"]
    cand_weight = cand.get("weight_kg", 0.0)

    # 地面层放置不对已有下层箱体施加额外垂直载荷
    if cand_z <= Z_CONTACT_TOL or cand_weight <= 1e-6:
        return True, None

    if not cargo_specs:
        return True, None

    # 构建包含 candidate 的全局虚拟布局
    all_boxes = [normalize_box(p) for p in placements] + [cand]
    cand_idx = len(all_boxes) - 1

    # 按 Z 层级构建接触快速索引
    from collections import defaultdict
    import math

    z_bin_size = 0.01  # 10mm bin
    z_top_bins = defaultdict(list)
    z_bottom_bins = defaultdict(list)

    for idx, b in enumerate(all_boxes):
        top_bin = int(math.floor((b["z"] + b["dz"]) / z_bin_size))
        bot_bin = int(math.floor(b["z"] / z_bin_size))
        z_top_bins[top_bin].append(idx)
        z_bottom_bins[bot_bin].append(idx)

    def get_supported_candidates(target_top_z: float) -> List[int]:
        """获取底部落在 target_top_z 接触高度上的上层箱体索引"""
        min_bin = int(math.floor((target_top_z - Z_CONTACT_TOL) / z_bin_size))
        max_bin = int(math.floor((target_top_z + Z_CONTACT_TOL) / z_bin_size))
        cands = []
        for b in range(min_bin, max_bin + 1):
            for idx in z_bottom_bins.get(b, []):
                b_cand = all_boxes[idx]
                if abs(b_cand["z"] - target_top_z) <= Z_CONTACT_TOL:
                    cands.append(idx)
        return cands

    transmitted_weight_memo: Dict[int, float] = {}

    def get_transmitted_weight(idx: int, visited: Optional[Set[int]] = None) -> float:
        """递归计算 idx 箱体及其上方所有通过接触面积分摊传递的下压总自重"""
        if idx in transmitted_weight_memo:
            return transmitted_weight_memo[idx]
        if visited is None:
            visited = set()
        visited.add(idx)

        b_curr = all_boxes[idx]
        self_w = b_curr["weight_kg"]
        cx, cy, cz = b_curr["x"], b_curr["y"], b_curr["z"]
        cdx, cdy, cdz = b_curr["dx"], b_curr["dy"], b_curr["dz"]

        uppers = get_supported_candidates(cz + cdz)
        accum_upper_trans_w = 0.0

        for u_idx in uppers:
            if u_idx == idx or u_idx in visited:
                continue
            b_u = all_boxes[u_idx]
            ox = min(cx + cdx, b_u["x"] + b_u["dx"]) - max(cx, b_u["x"])
            if ox > epsilon:
                oy = min(cy + cdy, b_u["y"] + b_u["dy"]) - max(cy, b_u["y"])
                if oy > epsilon:
                    contact_area = ox * oy
                    u_base_area = b_u["dx"] * b_u["dy"]
                    if u_base_area > 0:
                        contact_frac = contact_area / u_base_area
                        u_trans = get_transmitted_weight(u_idx, visited.copy())
                        accum_upper_trans_w += u_trans * contact_frac

        total_trans = self_w + accum_upper_trans_w
        transmitted_weight_memo[idx] = total_trans
        return total_trans

    # 找出所有在 candidate 下方受力传播链上的箱体 (通过反向图遍历)
    affected_lower_indices: Set[int] = set()
    queue = [cand_idx]

    while queue:
        curr = queue.pop(0)
        b_curr = all_boxes[curr]
        cz = b_curr["z"]
        if cz <= Z_CONTACT_TOL:
            continue

        min_bin = int(math.floor((cz - Z_CONTACT_TOL) / z_bin_size))
        max_bin = int(math.floor((cz + Z_CONTACT_TOL) / z_bin_size))
        for b in range(min_bin, max_bin + 1):
            for l_idx in z_top_bins.get(b, []):
                if l_idx == curr or l_idx in affected_lower_indices:
                    continue
                b_l = all_boxes[l_idx]
                if abs((b_l["z"] + b_l["dz"]) - cz) <= Z_CONTACT_TOL:
                    ox = min(b_curr["x"] + b_curr["dx"], b_l["x"] + b_l["dx"]) - max(b_curr["x"], b_l["x"])
                    if ox > epsilon:
                        oy = min(b_curr["y"] + b_curr["dy"], b_l["y"] + b_l["dy"]) - max(b_curr["y"], b_l["y"])
                        if oy > epsilon:
                            affected_lower_indices.add(l_idx)
                            queue.append(l_idx)

    # 针对每一个受力受影响的下层箱体，核验承重上限与表面压强
    for idx in affected_lower_indices:
        b = all_boxes[idx]
        sku_id = b["sku_id"]
        cargo = cargo_specs.get(sku_id)
        if not cargo:
            continue

        policy = getattr(cargo, "stacking_policy", None)
        if policy is None:
            continue

        # 该箱体受到的上层传导载荷
        upper_load = max(0.0, get_transmitted_weight(idx) - b["weight_kg"])

        # 1. 垂直承重上限核查
        max_bearing = getattr(policy, "max_bearing_kg", None)
        if max_bearing is not None and max_bearing > 0:
            if upper_load > max_bearing + epsilon:
                return False, (
                    f"下层箱体 {b.get('placement_id', sku_id)} (SKU: {sku_id}) 承重超限: "
                    f"累计受压载荷 {upper_load:.1f}kg > 允许上限 {max_bearing:.1f}kg"
                )

        # 2. 表面压强核查
        max_pressure = getattr(policy, "max_pressure_kg_m2", None)
        if max_pressure is not None and max_pressure > 0:
            area = b["dx"] * b["dy"]
            pressure = upper_load / area if area > 0 else 0.0
            if pressure > max_pressure + epsilon:
                return False, (
                    f"下层箱体 {b.get('placement_id', sku_id)} (SKU: {sku_id}) 表面压强超限: "
                    f"压强 {pressure:.1f}kg/m² > 允许上限 {max_pressure:.1f}kg/m²"
                )

    return True, None
