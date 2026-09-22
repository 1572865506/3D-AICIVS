# -*- coding: utf-8 -*-
"""
防蜂窝空洞与方案质量过滤器 (Anti-Honeycomb & Solution Quality Filter)

坚决贯彻核心对齐原则: 坚决消除“数字利用率高但内部蜂窝空洞、碎片化不稳定”的假合理现象。

审计维度:
  1. 零违规硬门禁: 物理内核与验证器 violations == 0, collisions == 0
  2. 刚性件履约硬门禁: 饥饿 SKU == 0, 严惩抢占刚性件塞弹性的优先级倒挂
  3. 内部封闭蜂窝空洞率 (Enclosed Honeycomb Cavity Ratio)
  4. 层间交错咬合结构度 (Interlock Stacking Score - 杜绝独立烟囱柱)
  5. 空间紧凑度与碎片化指数 (Spatial Compactness & Fragmentation)

评级输出:
  - GOLD   : 金牌示范方案 (适合作为神经网络正样本 / 专家推荐实装方案)
  - SILVER : 银牌可用方案 (合格常规方案)
  - REJECT : 驳回淘汰方案 (存在空洞/饥饿/倒挂/结构性缺陷)

被谁调用:
  - data_pipeline/collector.py (沉淀金牌训练集)
  - scripts/run_data_factory.py (数据工场自动化质量控制)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Set

from ..domain.models import ContainerSpec, CargoSKU, Placement, PackingRole
from ..validation.independent_validator import IndependentGlobalValidator
from ..validation.types import ValidationResult


@dataclass
class QualityAuditReport:
    """方案质量全貌审计报告"""
    solution_id: str
    rating: str               # 'GOLD', 'SILVER', 'REJECT'
    score: float              # 0.0 ~ 100.0
    is_valid: bool
    violations_count: int
    volume_utilization_pct: float
    rigid_fulfillment_pct: float
    elastic_completion_pct: float
    starved_skus_count: int
    has_priority_inversion: bool
    enclosed_cavity_volume_m3: float
    enclosed_cavity_ratio_pct: float
    interlock_score: float
    rejection_reasons: List[str] = field(default_factory=list)
    quality_tags: List[str] = field(default_factory=list)


class AntiCavityFilter:
    """防蜂窝空洞质量过滤器"""

    def __init__(
        self,
        validator: Optional[IndependentGlobalValidator] = None,
        max_allowed_cavity_ratio_gold: float = 3.5,   # 金牌允许的最大内部空洞体积比 (%)
        max_allowed_cavity_ratio_silver: float = 6.0, # 银牌允许的最大内部空洞体积比 (%)
        min_interlock_score_gold: float = 0.50,       # 金牌要求的最低层间咬合度
        min_rigid_fulfillment_gold: float = 98.0,     # 金牌要求的最低刚性履约率 (%)
    ):
        self.validator = validator or IndependentGlobalValidator(grid_resolution=0.15)
        self.max_allowed_cavity_ratio_gold = max_allowed_cavity_ratio_gold
        self.max_allowed_cavity_ratio_silver = max_allowed_cavity_ratio_silver
        self.min_interlock_score_gold = min_interlock_score_gold
        self.min_rigid_fulfillment_gold = min_rigid_fulfillment_gold

    def audit_solution(
        self,
        solution_id: str,
        container: ContainerSpec,
        placements: List[Any],
        cargo_skus: List[CargoSKU],
        precomputed_val_result: Optional[ValidationResult] = None,
    ) -> QualityAuditReport:
        """对方案进行全方位物理质量与防空洞评定"""
        # 1. 独立验证器终审
        val_res = precomputed_val_result or self.validator.validate(
            container=container,
            placements=placements,
            cargo_list=cargo_skus,
        )

        rejection_reasons: List[str] = []
        quality_tags: List[str] = []

        # 2. 检查物理硬违规
        violations_count = len(val_res.violations)
        if not val_res.is_valid or violations_count > 0:
            rejection_reasons.append(f"存在 {violations_count} 处物理或业务规则硬违规")

        # 3. 计算刚性与弹性履约率、饥饿 SKU、优先级倒挂
        sku_dict = {s.sku_id: s for s in cargo_skus}
        placed_counts: Dict[str, int] = {}
        for p in placements:
            sid = p.get("sku_id") if isinstance(p, dict) else getattr(p, "sku_id", "")
            placed_counts[sid] = placed_counts.get(sid, 0) + 1

        rigid_required_total = 0
        rigid_placed_total = 0
        elastic_required_total = 0
        elastic_placed_total = 0
        starved_skus = 0

        for sku in cargo_skus:
            req = sku.quantity.required
            placed = placed_counts.get(sku.sku_id, 0)
            is_elastic = (
                getattr(sku, "is_elastic", False)
                or getattr(sku.quantity, "is_elastic", False)
                or (PackingRole.FLEXIBLE in getattr(sku, "packing_roles", ()))
            )

            if not is_elastic:
                rigid_required_total += req
                rigid_placed_total += min(placed, req)
                if req > 0 and placed == 0:
                    starved_skus += 1
            else:
                elastic_required_total += req
                elastic_placed_total += min(placed, req)

        rigid_pct = (rigid_placed_total / rigid_required_total * 100.0) if rigid_required_total > 0 else 100.0
        elastic_pct = (elastic_placed_total / elastic_required_total * 100.0) if elastic_required_total > 0 else 0.0

        has_inversion = False
        if rigid_pct < 98.0 and elastic_placed_total > 0:
            has_inversion = True
            rejection_reasons.append("优先级倒挂: 刚性SKU未装满前抢占空间装填弹性件")

        if starved_skus > 0:
            rejection_reasons.append(f"严重饥饿: 有 {starved_skus} 个指定刚性SKU完全弃装 (放置数为0)")

        # 4. 内部蜂窝空洞与残余死角审计
        metrics = val_res.metrics or {}
        enclosed_cavity_vol = metrics.get("enclosed_cavity_volume", 0.0)
        cargo_vol = metrics.get("cargo_volume", 1.0)
        util_pct = metrics.get("volume_utilization_pct", 0.0)

        cavity_ratio_pct = (enclosed_cavity_vol / cargo_vol * 100.0) if cargo_vol > 0 else 0.0
        if cavity_ratio_pct > self.max_allowed_cavity_ratio_silver:
            rejection_reasons.append(f"内部蜂窝空洞率超标 ({cavity_ratio_pct:.1f}% > {self.max_allowed_cavity_ratio_silver}%)")

        # 5. 咬合度审计 (Interlock Stacking Score)
        interlock_score = self._compute_interlock_score(placements)
        if interlock_score < 0.25 and len(placements) > 10:
            rejection_reasons.append(f"层间咬合力严重不足 (Interlock={interlock_score:.2f} < 0.25, 存在大量烟囱柱)")

        # 6. 最终综合打分与三档评级
        base_score = util_pct * 0.45 + rigid_pct * 0.40 + interlock_score * 15.0
        base_score -= (cavity_ratio_pct * 2.5)

        if len(rejection_reasons) > 0:
            rating = "REJECT"
            final_score = max(0.0, min(59.0, base_score * 0.5))
        elif (
            rigid_pct >= self.min_rigid_fulfillment_gold
            and cavity_ratio_pct <= self.max_allowed_cavity_ratio_gold
            and interlock_score >= self.min_interlock_score_gold
            and util_pct >= 70.0
            and starved_skus == 0
            and not has_inversion
        ):
            rating = "GOLD"
            final_score = max(88.0, min(100.0, base_score))
            quality_tags.extend(["EXPERT_APPROVED", "DENSE_STACK", "INTERLOCKED"])
        else:
            rating = "SILVER"
            final_score = max(60.0, min(87.9, base_score))
            quality_tags.append("ACCEPTABLE")

        return QualityAuditReport(
            solution_id=solution_id,
            rating=rating,
            score=round(final_score, 1),
            is_valid=val_res.is_valid and len(rejection_reasons) == 0,
            violations_count=violations_count,
            volume_utilization_pct=round(util_pct, 2),
            rigid_fulfillment_pct=round(rigid_pct, 1),
            elastic_completion_pct=round(elastic_pct, 1),
            starved_skus_count=starved_skus,
            has_priority_inversion=has_inversion,
            enclosed_cavity_volume_m3=round(enclosed_cavity_vol, 3),
            enclosed_cavity_ratio_pct=round(cavity_ratio_pct, 2),
            interlock_score=round(interlock_score, 2),
            rejection_reasons=rejection_reasons,
            quality_tags=quality_tags,
        )

    def _compute_interlock_score(self, placements: List[Any], eps: float = 1e-3) -> float:
        """计算方案的平均层间咬合度 (0.0: 完全烟囱直上独立堆叠, 1.0: 完美交错砌砖咬合)"""
        if len(placements) <= 3:
            return 1.0

        def get_geom(p):
            if isinstance(p, dict):
                return p["x"], p["y"], p["z"], p["dx"], p["dy"], p["dz"]
            pos = getattr(p, "position")
            ori = getattr(p, "orientation")
            return pos.x, pos.y, pos.z, ori.dx, ori.dy, ori.dz

        upper_boxes_count = 0
        interlocked_upper_boxes = 0

        for i, p in enumerate(placements):
            px, py, pz, pdx, pdy, pdz = get_geom(p)
            if pz <= 1e-3:
                continue

            upper_boxes_count += 1
            # 查找直接支撑它的下层箱体
            supporting_boxes = []
            for j, p2 in enumerate(placements):
                if i == j:
                    continue
                p2x, p2y, p2z, p2dx, p2dy, p2dz = get_geom(p2)
                if abs((p2z + p2dz) - pz) <= 0.005:
                    ox = min(px + pdx, p2x + p2dx) - max(px, p2x)
                    if ox > eps:
                        oy = min(py + pdy, p2y + p2dy) - max(py, p2y)
                        if oy > eps:
                            supporting_boxes.append((j, ox * oy))

            # 若由 2 个或以上不同下层箱体支撑，说明产生交错咬合
            if len(supporting_boxes) >= 2:
                interlocked_upper_boxes += 1
            elif len(supporting_boxes) == 1:
                # 即使单箱支撑，若尺寸错位交错超过 15%，也认定为咬合
                sub_idx = supporting_boxes[0][0]
                p2x, p2y, _, p2dx, p2dy, _ = get_geom(placements[sub_idx])
                x_offset = abs(px - p2x)
                y_offset = abs(py - p2y)
                if x_offset > 0.15 * pdx or y_offset > 0.15 * pdy:
                    interlocked_upper_boxes += 1

        if upper_boxes_count == 0:
            return 1.0
        return interlocked_upper_boxes / upper_boxes_count
