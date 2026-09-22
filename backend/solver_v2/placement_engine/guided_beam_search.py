"""GuidedBeamSearch: 300 秒深度引导搜索引擎

深度集成:
1. Transformer 决策大脑 (Soft Guidance): 提供 SKU 动作先验分布、目标空间落位坐标与长远状态质量估值。
2. 共享物理内核门禁 (Hard Physics): 在每一步扩展时进行 0 违规严格物理可行性审查，违规即剪枝。
3. 动态时间预算控制: 支持最高 300 秒的深度空间探索与早停回退。
"""

import time
import math
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Set
import torch

from backend.solver_v2.domain.models import (
    ContainerSpec,
    CargoSKU,
    Placement,
    PlacementContext,
    Point3D,
    Orientation3D,
    PackingRole,
)
from backend.solver_v2.solver.baseline_solver import SolverSolution, SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from backend.solver_v2.physics_kernel.unified_gate import check_placement_feasibility
from backend.solver_v2.brain.packing_transformer import PackingTransformer, TransformerConfig


@dataclass
class SearchConfig:
    """深度引导搜索超参数配置"""
    beam_width: int = 4
    time_budget_sec: float = 300.0
    max_candidates_per_step: int = 16
    device: Optional[str] = None
    early_stop_threshold: float = 98.0  # 刚性 100% 且容积率超标可早停


@dataclass
class BeamNode:
    """搜索状态节点"""
    placements: List[Placement] = field(default_factory=list)
    remaining: Dict[str, int] = field(default_factory=dict)
    anchors: Set[Tuple[float, float, float]] = field(default_factory=lambda: {(0.0, 0.0, 0.0)})
    occupied_vol: float = 0.0
    total_weight: float = 0.0
    rigid_placed: int = 0
    rigid_required: int = 0
    interlock_pairs: int = 0
    estimated_value: float = 0.0
    score: float = 0.0


class GuidedBeamSearch:
    """3D-AICIVS 深度引导搜索引擎"""

    def __init__(
        self,
        container: ContainerSpec,
        brain: Optional[PackingTransformer] = None,
        config: Optional[SearchConfig] = None,
    ):
        self.container = container
        self.config = config or SearchConfig()
        self.validator = IndependentGlobalValidator()

        # 硬件加速设备绑定
        if self.config.device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(self.config.device)

        if brain is None:
            self.brain = PackingTransformer().to(self.device)
            self.brain.eval()
        else:
            self.brain = brain.to(self.device)
            self.brain.eval()

        self.container_vol = container.inner_dim.x * container.inner_dim.y * container.inner_dim.z

    def solve(
        self,
        cargo_list: List[CargoSKU],
        options: Optional[Dict[str, Any]] = None,
    ) -> SolverSolution:
        """执行 300 秒深度引导搜索"""
        t_start = time.perf_counter()
        time_budget = (options or {}).get("time_budget_sec", self.config.time_budget_sec)
        beam_width = (options or {}).get("beam_width", self.config.beam_width)

        telemetry = SolverTelemetry()
        sku_map = {s.sku_id: s for s in cargo_list}

        # 统计刚性与弹性需求
        initial_remaining: Dict[str, int] = {}
        rigid_req_total = 0
        total_items_to_place = 0
        for s in cargo_list:
            req = s.quantity.required
            initial_remaining[s.sku_id] = req
            total_items_to_place += req
            is_elastic = getattr(s, "is_elastic", False) or getattr(s.quantity, "is_elastic", False) or (PackingRole.FLEXIBLE in getattr(s, "packing_roles", ()))
            if not is_elastic:
                rigid_req_total += req

        # 初始根节点
        root = BeamNode(
            placements=[],
            remaining=initial_remaining,
            anchors={(0.0, 0.0, 0.0)},
            occupied_vol=0.0,
            total_weight=0.0,
            rigid_placed=0,
            rigid_required=rigid_req_total,
            interlock_pairs=0,
            estimated_value=0.0,
            score=0.0,
        )

        beam = [root]
        best_node = root
        step = 0

        # 张量化货柜与静态 SKU 特征
        cL, cW, cH = self.container.inner_dim.x, self.container.inner_dim.y, self.container.inner_dim.z
        c_feat = torch.tensor([[cL, cW, cH, self.container.max_payload_kg]], dtype=torch.float32, device=self.device)

        sku_feature_rows = []
        sku_ids = list(cargo_list)
        for s in cargo_list:
            is_floor = 1.0 if getattr(s.stacking_policy, "must_be_on_floor", False) else 0.0
            allow_top = 1.0 if getattr(s.stacking_policy, "allow_stacking_on_top", True) else 0.0
            max_b = float(getattr(s.stacking_policy, "max_bearing_kg", 5000.0) or 5000.0)
            max_l = float(getattr(s.stacking_policy, "max_stack_layers", 10.0) or 10.0)
            sku_feature_rows.append([
                s.box.x, s.box.y, s.box.z,
                s.weight_kg,
                float(s.quantity.required),
                max_b,
                max_l,
                is_floor,
                allow_top,
            ])
        sku_tensor = torch.tensor([sku_feature_rows], dtype=torch.float32, device=self.device)

        # 搜索主循环
        while beam:
            elapsed = time.perf_counter() - t_start
            if elapsed >= time_budget:
                telemetry.no_candidate_reason = "TIME_BUDGET_EXHAUSTED"
                break

            candidates_pool: List[BeamNode] = []

            for node in beam:
                # 检查是否全部已装完
                rem_sum = sum(node.remaining.values())
                if rem_sum == 0:
                    candidates_pool.append(node)
                    continue

                # 构建动态状态特征 [B, 6]
                packed_cnt = float(len(node.placements))
                vol_ratio = node.occupied_vol / max(self.container_vol, 1e-3)
                wt_ratio = node.total_weight / max(self.container.max_payload_kg, 1e-3)
                max_x = max((p.position.x + p.orientation.dx for p in node.placements), default=0.0) / max(cL, 1e-3)
                max_y = max((p.position.y + p.orientation.dy for p in node.placements), default=0.0) / max(cW, 1e-3)
                max_z = max((p.position.z + p.orientation.dz for p in node.placements), default=0.0) / max(cH, 1e-3)

                state_feat = torch.tensor([[packed_cnt, vol_ratio, wt_ratio, max_x, max_y, max_z]], dtype=torch.float32, device=self.device)
                valid_mask = torch.tensor([[node.remaining.get(s.sku_id, 0) > 0 for s in cargo_list]], dtype=torch.bool, device=self.device)

                # 1. 决策大脑输出软先验指引
                with torch.no_grad():
                    prior = self.brain.predict_action_prior(
                        container_features=c_feat,
                        sku_matrix=sku_tensor,
                        state_features=state_feat,
                        valid_sku_mask=valid_mask,
                    )

                sku_probs = prior["sku_probs"]
                pos_guidance = prior["pos_guidance"]
                est_val = prior["estimated_value"]

                # 排序可用 SKU（优先考虑剩余非零且模型推荐概率高的 SKU）
                available_skus = [
                    (sku_idx, cargo_list[sku_idx], sku_probs[sku_idx])
                    for sku_idx in range(len(cargo_list))
                    if node.remaining.get(cargo_list[sku_idx].sku_id, 0) > 0
                ]
                available_skus.sort(key=lambda x: x[2], reverse=True)

                # 筛选前几个推荐 SKU 展开
                expanded_in_node = 0
                for sku_idx, sku, prob in available_skus[:4]:
                    # 确定可能姿态
                    orientations = self._get_candidate_orientations(sku)
                    target_x = pos_guidance[sku_idx][0] * cL
                    target_y = pos_guidance[sku_idx][1] * cW
                    target_z = pos_guidance[sku_idx][2] * cH

                    # 锚点排序：重力法则优先 (z 越小越好)，其次靠壁 (y 越小越好)，其次纵深，紧凑性
                    sorted_anchors = sorted(
                        list(node.anchors),
                        key=lambda a: (
                            round(a[2], 2),  # z 优先
                            round(a[0], 2),  # x 靠后/进深
                            round(a[1], 2),  # y 靠壁
                            (a[0] - target_x)**2 + (a[1] - target_y)**2 + (a[2] - target_z)**2,
                        )
                    )

                    for ax, ay, az in sorted_anchors[:12]:
                        if az >= cH - 0.05:
                            continue

                        for dx, dy, dz in orientations:
                            if ax + dx > cL + 1e-4 or ay + dy > cW + 1e-4 or az + dz > cH + 1e-4:
                                continue

                            ctx = PlacementContext.FOUNDATION if az <= 1e-3 else PlacementContext.MAIN_WALL
                            step_idx = len(node.placements) + 1
                            cand_placement = Placement(
                                placement_id=f"p_{step_idx}",
                                instance_id=f"inst_{sku.sku_id}_{step_idx}",
                                sku_id=sku.sku_id,
                                position=Point3D(x=ax, y=ay, z=az),
                                orientation=Orientation3D(dx=dx, dy=dy, dz=dz),
                                weight_kg=sku.weight_kg,
                                context=ctx,
                                step_index=step_idx,
                            )

                            telemetry.candidates_generated += 1

                            # 2. 共享物理内核严苛门禁 (0 违规保证)
                            is_feasible, vio_type, reason = check_placement_feasibility(
                                candidate=cand_placement,
                                placements=node.placements,
                                container_spec=self.container,
                                cargo_specs=sku_map,
                                current_payload_weight=node.total_weight,
                                door_zone_length=self.container.door_zone_length_m or 0.0,
                                check_tipping=True,
                            )

                            telemetry.candidates_evaluated += 1

                            if not is_feasible:
                                rej_key = vio_type or reason or "UNKNOWN"
                                telemetry.candidates_rejected_by_reason[rej_key] = (
                                    telemetry.candidates_rejected_by_reason.get(rej_key, 0) + 1
                                )
                                continue

                            # 3. 构造有效子节点
                            new_rem = dict(node.remaining)
                            new_rem[sku.sku_id] -= 1

                            # 维护锚点集合
                            new_anchors = set(node.anchors)
                            new_anchors.discard((ax, ay, az))
                            if ax + dx < cL:
                                new_anchors.add((ax + dx, ay, az))
                            if ay + dy < cW:
                                new_anchors.add((ax, ay + dy, az))
                            if az + dz < cH:
                                new_anchors.add((ax, ay, az + dz))

                            box_vol = dx * dy * dz
                            new_occ_vol = node.occupied_vol + box_vol
                            new_weight = node.total_weight + sku.weight_kg

                            is_elastic = getattr(sku, "is_elastic", False) or getattr(sku.quantity, "is_elastic", False) or (PackingRole.FLEXIBLE in getattr(sku, "packing_roles", ()))
                            new_rigid = node.rigid_placed + (0 if is_elastic else 1)

                            # 计算咬合增益
                            interlock_gain = 0
                            if az > 1e-3:
                                for ep in node.placements:
                                    if abs((ep.position.z + ep.orientation.dz) - az) <= 0.005:
                                        ox = min(ax + dx, ep.position.x + ep.orientation.dx) - max(ax, ep.position.x)
                                        oy = min(ay + dy, ep.position.y + ep.orientation.dy) - max(ay, ep.position.y)
                                        if ox > 0.02 and oy > 0.02:
                                            interlock_gain += 1

                            new_interlock = node.interlock_pairs + interlock_gain

                            # 综合评分函数: 刚性率(45%) + 容积率(40%) + 咬合交错(10%) + 模型估值(5%)
                            util_ratio = new_occ_vol / max(self.container_vol, 1e-3)
                            rigid_ratio = new_rigid / max(node.rigid_required, 1)

                            node_score = (
                                rigid_ratio * 45.0
                                + util_ratio * 40.0
                                + min(1.0, new_interlock / max(len(node.placements) + 1, 1)) * 10.0
                                + (est_val / 100.0) * 5.0
                            )

                            child = BeamNode(
                                placements=node.placements + [cand_placement],
                                remaining=new_rem,
                                anchors=new_anchors,
                                occupied_vol=new_occ_vol,
                                total_weight=new_weight,
                                rigid_placed=new_rigid,
                                rigid_required=node.rigid_required,
                                interlock_pairs=new_interlock,
                                estimated_value=est_val,
                                score=node_score,
                            )
                            candidates_pool.append(child)
                            expanded_in_node += 1
                            if expanded_in_node >= self.config.max_candidates_per_step:
                                break

                        if expanded_in_node >= self.config.max_candidates_per_step:
                            break

            if not candidates_pool:
                break

            # 按综合分数修剪 Beam
            candidates_pool.sort(key=lambda n: n.score, reverse=True)
            beam = candidates_pool[:beam_width]

            if beam and beam[0].score > best_node.score:
                best_node = beam[0]

            step += 1

        # 终审验证与结果组装
        telemetry.runtime_ms = (time.perf_counter() - t_start) * 1000.0
        telemetry.steps_committed = len(best_node.placements)

        val_result = self.validator.validate(
            container=self.container,
            placements=best_node.placements,
            cargo_list=cargo_list,
        )

        vol_util = (best_node.occupied_vol / max(self.container_vol, 1e-3)) * 100.0
        placed_cnt = len(best_node.placements)
        unplaced_cnt = total_items_to_place - placed_cnt

        return SolverSolution(
            status="OPTIMAL" if val_result.is_valid and unplaced_cnt == 0 else ("FEASIBLE" if val_result.is_valid else "INVALID"),
            container=self.container,
            placements=best_node.placements,
            placed_count=placed_cnt,
            unplaced_count=unplaced_cnt,
            volume_utilization_pct=round(vol_util, 2),
            total_weight_kg=round(best_node.total_weight, 2),
            validation_result=val_result,
            telemetry=telemetry,
        )

    def _get_candidate_orientations(self, sku: CargoSKU) -> List[Tuple[float, float, float]]:
        """获取 SKU 允许的几何朝向尺寸 (符合 OrientationPolicy)"""
        dim = (sku.box.x, sku.box.y, sku.box.z)
        policy = getattr(sku, "orientation_policy", None)

        allow_upright = getattr(policy, "allow_upright", True) if policy else True
        allow_flat = getattr(policy, "allow_flat", False) if policy else False
        allow_side = getattr(policy, "allow_side", False) if policy else False

        perms = []
        if allow_upright:
            perms.extend([
                (dim[0], dim[1], dim[2]),
                (dim[1], dim[0], dim[2]),
            ])
        if allow_flat:
            perms.extend([
                (dim[0], dim[2], dim[1]),
                (dim[1], dim[2], dim[0]),
            ])
        if allow_side:
            perms.extend([
                (dim[2], dim[0], dim[1]),
                (dim[2], dim[1], dim[0]),
            ])

        if not perms:
            perms = [(dim[0], dim[1], dim[2])]

        seen = set()
        allowed = []
        for p in perms:
            if p not in seen:
                seen.add(p)
                allowed.append(p)
        return allowed
