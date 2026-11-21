"""
双向汇合装载 + EMS 极大空闲空间 + 多路径评分择优原型（Role A 原型组件）。

用途：
    1. 门区逆向封门（从 x = L 往 -X 生长）：提取 DOOR_SEAL SKU，调用
       `exact_recipe_builder.generate_mixed_height_blocks(allow_door=True)` 生成高对齐门墙块，
       紧贴 x = L 往柜内放置，记录门墙真实占用的最小 X 边界 `door_actual_min_x`。
    2. 主区正向推进（从 x = 0 往 `door_actual_min_x` 生长）：在 `[0, door_actual_min_x]` 内维护
       三维极大空闲空间（EMS），先放置高填充率、混高满高的 `CompoundBlock`，再由小件/零散件
       按 EMS 最佳贴合度填充剩余空腔与汇合缝（含防饥饿首件保障）。
    3. 多路径评分择优：运行 3 条差异化策略（`volume_first`、`complete_sku_first`、`large_then_gap`），
       每条严格执行前置物理校验（0 碰撞、地面/≥60% 支撑+质心安全、TIP-03 倾覆前向支撑、
       承重、层数与朝向），用统一评分函数择优并通过 `IndependentGlobalValidator.validate` 验收。

输入：container (ContainerSpec), cargo_list (List[CargoSKU]), flexible_unspecified (bool)
输出：SolverSolution
被谁调用：`scripts/run_prototype_ab.py`
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Tuple

from backend.solver_v2.domain.models import (
    CargoSKU, ContainerSpec, Orientation3D, OrientationMode, OrientationRegion,
    OrientationRule, PackingRole, Placement, PlacementContext, Point3D,
    PolicySource, UniversalCargoTensor, UniversalZone, ZoneType,
)
from backend.solver_v2.solver.baseline_solver import SolverSolution, SolverTelemetry
from backend.solver_v2.solver.exact_recipe_builder import BlockBox, CompoundBlock, generate_mixed_height_blocks
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator

_EPS = 1e-4
_FRAGILE_KEYWORDS = ("玻璃", "易碎", "glass", "fragile")
@dataclass(frozen=True)
class EMS:
    """三维极大空闲空间（Empty Maximal Space）。"""
    x0: float; y0: float; z0: float; x1: float; y1: float; z1: float
    @property
    def dx(self) -> float: return self.x1 - self.x0
    @property
    def dy(self) -> float: return self.y1 - self.y0
    @property
    def dz(self) -> float: return self.z1 - self.z0
    @property
    def volume(self) -> float: return max(0.0, self.dx) * max(0.0, self.dy) * max(0.0, self.dz)
@dataclass
class _PlacedRecord:
    """已放置箱体内部索引记录，用于快速支撑/碰撞/承重/倾覆检查。"""
    placement: Placement
    x0: float; y0: float; z0: float; x1: float; y1: float; z1: float
    layer: int; top_load_kg: float = 0.0


def _is_door_sku(sku: CargoSKU) -> bool:
    req = sku.source_requirement_text or ""
    return PackingRole.DOOR_SEAL in sku.packing_roles or sku.target_zone == ZoneType.DOOR or any(k in req for k in ("封柜门", "封门", "最后放"))


def _is_fragile_sku(sku: CargoSKU) -> bool:
    hp = getattr(getattr(sku, "cargo_profile", None), "handling_policy", None)
    return bool(hp and hp.fragile) or any(k in f"{sku.name} {sku.source_requirement_text}".lower() for k in _FRAGILE_KEYWORDS)


def _is_upright_locked(sku: CargoSKU) -> bool:
    hp = getattr(getattr(sku, "cargo_profile", None), "handling_policy", None)
    if hp is not None and hp.keep_upright and hp.source == PolicySource.USER_DEFINED:
        return True
    req = (sku.source_requirement_text or "").lower()
    if any(k in req for k in ("立放", "不可倒置", "不能倒", "不可平放", "keep upright", "upright only")):
        return True
    pol = sku.orientation_policy
    return pol.source == PolicySource.USER_DEFINED and not pol.allow_flat and not pol.allow_side


def build_flexible_cargo_list(cargo_list: List[CargoSKU]) -> List[CargoSKU]:
    """为 C 组实验开放未锁立放且非易碎普通货物的 6 向旋转策略（不修改原对象）。"""
    out: List[CargoSKU] = []
    all_regions = (OrientationRegion.MAIN_BODY, OrientationRegion.TOP_FILL, OrientationRegion.DOOR_ZONE)
    all_ctx = (PlacementContext.MAIN_WALL, PlacementContext.TOP_FILL, PlacementContext.GAP_FILL, PlacementContext.DOOR_SEAL)
    new_rules = tuple(OrientationRule(m, all_regions) for m in (OrientationMode.UPRIGHT, OrientationMode.FLAT, OrientationMode.SIDE))
    for s in cargo_list:
        if _is_fragile_sku(s) or _is_upright_locked(s):
            out.append(s)
            continue
        sc = copy.copy(s)
        sc.orientation_policy = replace(
            s.orientation_policy, allow_upright=True, allow_flat=True, allow_side=True,
            flat_only_on_top=False, allowed_contexts_for_flat=all_ctx, allowed_contexts_for_side=all_ctx, rules=new_rules,
        )
        out.append(sc)
    return out


def _sku_to_tensor(s: CargoSKU, flexible_unspecified: bool) -> UniversalCargoTensor:
    req = s.source_requirement_text or ""
    zp = UniversalZone.INNER if (s.target_zone == ZoneType.REAR or "最里面" in req) else (
        UniversalZone.DOOR if _is_door_sku(s) else UniversalZone.FLEXIBLE
    )
    allow_flat, allow_side = s.orientation_policy.allow_flat, s.orientation_policy.allow_side
    if flexible_unspecified and not _is_fragile_sku(s) and not _is_upright_locked(s):
        allow_flat = allow_side = True
    t = UniversalCargoTensor(
        s.sku_id, s.name, s.box.x, s.box.y, s.box.z, s.weight_kg, s.quantity.required, zp,
        allow_flat=allow_flat, allow_side=allow_side, max_stack_layers=s.stacking_policy.max_stack_layers,
        must_be_on_floor=bool(s.stacking_policy.must_be_on_floor), raw_requirement=req,
        is_elastic=bool(s.quantity.is_elastic or "可以减少" in req or "可减少" in req),
    )
    setattr(t, "allow_stacking_on_top", getattr(s.stacking_policy, "allow_stacking_on_top", True))
    setattr(t, "max_bearing_kg", getattr(s.stacking_policy, "max_bearing_kg", None))
    return t


def _merge_adjacent_ems(ems_list: List[EMS], max_ems: int = 220) -> List[EMS]:
    """合并同底高（z0/z1 一致）且在 X 或 Y 方向相邻/交叠的碎片 EMS，消除墙间窄条碎片。"""
    merged = list(ems_list)
    for _ in range(2):
        used, next_list, changed = [False] * len(merged), [], False
        for i in range(len(merged)):
            if used[i]:
                continue
            cur = merged[i]
            for j in range(i + 1, len(merged)):
                if used[j]:
                    continue
                o = merged[j]
                if abs(cur.z0 - o.z0) <= 1e-3 and abs(cur.z1 - o.z1) <= 1e-3:
                    if abs(cur.x0 - o.x0) <= 1e-3 and abs(cur.x1 - o.x1) <= 1e-3 and cur.y1 >= o.y0 - 1e-3 and o.y1 >= cur.y0 - 1e-3:
                        cur = EMS(cur.x0, min(cur.y0, o.y0), cur.z0, cur.x1, max(cur.y1, o.y1), cur.z1)
                        used[j], changed = True, True
                    elif abs(cur.y0 - o.y0) <= 1e-3 and abs(cur.y1 - o.y1) <= 1e-3 and cur.x1 >= o.x0 - 1e-3 and o.x1 >= cur.x0 - 1e-3:
                        cur = EMS(min(cur.x0, o.x0), cur.y0, cur.z0, max(cur.x1, o.x1), cur.y1, cur.z1)
                        used[j], changed = True, True
            next_list.append(cur)
        merged = next_list
        if not changed:
            break
    merged.sort(key=lambda m: m.volume, reverse=True)
    pruned: List[EMS] = []
    for c in merged:
        if not any(c.x0 >= k.x0 - _EPS and c.x1 <= k.x1 + _EPS and c.y0 >= k.y0 - _EPS and c.y1 <= k.y1 + _EPS and c.z0 >= k.z0 - _EPS and c.z1 <= k.z1 + _EPS for k in pruned):
            pruned.append(c)
            if len(pruned) >= max_ems:
                break
    return pruned


def _update_ems_list(
    ems_list: List[EMS], bx0: float, by0: float, bz0: float, bx1: float, by1: float, bz1: float,
    min_edge: float = 0.04, max_ems: int = 220, merge: bool = True,
) -> List[EMS]:
    """放入箱体后对相交 EMS 执行 6 面切割、去包含剪枝与可选相邻同底高 EMS 合并。"""
    next_ems: List[EMS] = []
    for e in ems_list:
        if bx1 <= e.x0 + _EPS or bx0 >= e.x1 - _EPS or by1 <= e.y0 + _EPS or by0 >= e.y1 - _EPS or bz1 <= e.z0 + _EPS or bz0 >= e.z1 - _EPS:
            next_ems.append(e)
            continue
        for c in (
            EMS(e.x0, e.y0, e.z0, bx0, e.y1, e.z1), EMS(bx1, e.y0, e.z0, e.x1, e.y1, e.z1),
            EMS(e.x0, e.y0, e.z0, e.x1, by0, e.z1), EMS(e.x0, by1, e.z0, e.x1, e.y1, e.z1),
            EMS(e.x0, e.y0, e.z0, e.x1, e.y1, bz0), EMS(e.x0, e.y0, bz1, e.x1, e.y1, e.z1),
        ):
            if c.dx >= min_edge - _EPS and c.dy >= min_edge - _EPS and c.dz >= min_edge - _EPS:
                next_ems.append(c)
    if merge:
        return _merge_adjacent_ems(next_ems, max_ems=max_ems)
    next_ems.sort(key=lambda m: m.volume, reverse=True)
    pruned: List[EMS] = []
    for c in next_ems:
        if not any(c.x0 >= k.x0 - _EPS and c.x1 <= k.x1 + _EPS and c.y0 >= k.y0 - _EPS and c.y1 <= k.y1 + _EPS and c.z0 >= k.z0 - _EPS and c.z1 <= k.z1 + _EPS for k in pruned):
            pruned.append(c)
            if len(pruned) >= max_ems:
                break
    return pruned


class _SingleStrategyRunner:
    """单策略双向汇合 + EMS 装载执行器。"""

    def __init__(self, container: ContainerSpec, cargo_list: List[CargoSKU], strategy: str, flexible_unspecified: bool):
        self.container, self.cargo_list, self.strategy = container, cargo_list, strategy
        self.flexible_unspecified = flexible_unspecified
        self.sku_map: Dict[str, CargoSKU] = {s.sku_id: s for s in cargo_list}
        self.tensors: List[UniversalCargoTensor] = [_sku_to_tensor(s, flexible_unspecified) for s in cargo_list]
        self.tensor_map: Dict[str, UniversalCargoTensor] = {t.sku_id: t for t in self.tensors}
        self.rem_qty: Dict[str, int] = {s.sku_id: s.quantity.required for s in cargo_list}
        self.placed: List[_PlacedRecord] = []
        self.total_weight: float = 0.0
        self.step_idx: int = 0
        self.min_sku_edge: float = min((min(s.box.x, s.box.y, s.box.z) for s in cargo_list), default=0.04)

    def _has_front_wall(self, e: EMS) -> bool:
        """判断 EMS 前端 (x1) 是否已有柜门或已落位墙面，以支持逆向贴墙放置避免倾覆误杀。"""
        if e.x1 >= self.container.Lx - 0.04 - _EPS:
            return True
        return any(
            abs(r.x0 - e.x1) <= 0.03 and min(e.y1, r.y1) - max(e.y0, r.y0) >= 0.08 and min(e.z1, r.z1) - max(e.z0, r.z0) >= 0.08
            for r in self.placed
        )

    def _check_box_valid(
        self, sku: CargoSKU, x: float, y: float, z: float, dx: float, dy: float, dz: float,
        extra_records: Optional[List[_PlacedRecord]] = None,
    ) -> Tuple[bool, int, List[_PlacedRecord]]:
        """前置硬约束检查：边界、载重、0 碰撞、地面/≥60% 支撑+质心安全、TIP-03 倾覆、承重与层数。"""
        x1, y1, z1 = x + dx, y + dy, z + dz
        if x < -_EPS or y < -_EPS or z < -_EPS or x1 > self.container.Lx + _EPS or y1 > self.container.Ly + _EPS or z1 > self.container.Lz + _EPS:
            return False, 1, []
        if self.container.max_payload_kg > 0 and self.total_weight + sku.weight_kg > self.container.max_payload_kg + _EPS:
            return False, 1, []
        if sku.stacking_policy.must_be_on_floor and z >= 1e-3:
            return False, 1, []

        all_recs = self.placed if not extra_records else (self.placed + extra_records)
        supporters: List[Tuple[_PlacedRecord, float]] = []
        has_fwd = (x1 >= self.container.Lx - 0.04 - _EPS) or ((2.0 * dx / max(1e-6, dz)) >= 1.5 - _EPS)

        for r in all_recs:
            if not (x1 <= r.x0 + _EPS or x >= r.x1 - _EPS or y1 <= r.y0 + _EPS or y >= r.y1 - _EPS or z1 <= r.z0 + _EPS or z >= r.z1 - _EPS):
                return False, 1, []
            if z >= 1e-3 and abs(r.z1 - z) <= 1e-3:
                ox, oy = min(x1, r.x1) - max(x, r.x0), min(y1, r.y1) - max(y, r.y0)
                if ox > _EPS and oy > _EPS:
                    supporters.append((r, ox * oy))
            if not has_fwd and abs(r.x0 - x1) <= 0.03 and min(y1, r.y1) - max(y, r.y0) >= 0.20 * dy - _EPS and min(z1, r.z1) - max(z, r.z0) >= 0.20 * dz - _EPS:
                has_fwd = True

        if not has_fwd:
            return False, 1, []
        if z < 1e-3:
            return True, 1, []
        if not supporters:
            return False, 1, []

        total_sup_area = sum(a for _, a in supporters)
        if total_sup_area / max(1e-9, dx * dy) < max(0.60, float(sku.stacking_policy.min_support_ratio or 0.60)) - _EPS:
            return False, 1, []
        cx, cy = x + dx * 0.5, y + dy * 0.5
        if not (min(r.x0 for r, _ in supporters) - _EPS <= cx <= max(r.x1 for r, _ in supporters) + _EPS
                and min(r.y0 for r, _ in supporters) - _EPS <= cy <= max(r.y1 for r, _ in supporters) + _EPS):
            return False, 1, []

        layer = max(r.layer for r, _ in supporters) + 1
        if sku.stacking_policy.max_stack_layers is not None and layer > sku.stacking_policy.max_stack_layers:
            return False, 1, []
        sup_objs: List[_PlacedRecord] = []
        for r, area in supporters:
            sup_sku = self.sku_map[r.placement.sku_id]
            if not sup_sku.stacking_policy.allow_stacking_on_top or (sup_sku.stacking_policy.max_stack_layers is not None and layer > sup_sku.stacking_policy.max_stack_layers):
                return False, 1, []
            max_b = sup_sku.stacking_policy.max_bearing_kg
            if max_b is not None and r.top_load_kg + sku.weight_kg * (area / total_sup_area) > max_b + _EPS:
                return False, 1, []
            sup_objs.append(r)
        return True, layer, sup_objs

    def _commit_box(
        self, sku: CargoSKU, x: float, y: float, z: float, ori: Orientation3D,
        context: PlacementContext, layer: int, supporters: List[_PlacedRecord],
    ) -> None:
        self.step_idx += 1
        p = Placement(
            f"P-{self.step_idx:05d}", f"{sku.sku_id}-{self.step_idx:05d}", sku.sku_id,
            Point3D(round(x, 5), round(y, 5), round(z, 5)), ori, sku.weight_kg, context, self.step_idx,
        )
        rec = _PlacedRecord(p, p.min_x, p.min_y, p.min_z, p.max_x, p.max_y, p.max_z, layer)
        if supporters:
            areas = [(r, (min(rec.x1, r.x1) - max(rec.x0, r.x0)) * (min(rec.y1, r.y1) - max(rec.y0, r.y0))) for r in supporters]
            total_a = sum(a for _, a in areas)
            if total_a > _EPS:
                for r, a in areas:
                    r.top_load_kg += sku.weight_kg * (a / total_a)
        self.placed.append(rec)
        self.rem_qty[sku.sku_id] -= 1
        self.total_weight += sku.weight_kg

    def _try_place_block(
        self, blk: CompoundBlock, bx0: float, by0: float, bz0: float, context: PlacementContext,
    ) -> bool:
        """原子性校验并放置整个 CompoundBlock（按底到顶、+X 到 -X 顺序以便同块前向支撑生效）。"""
        if any(self.rem_qty.get(sid, 0) < cnt for sid, cnt in blk.sku_counts.items()):
            return False
        if self.container.max_payload_kg > 0 and self.total_weight + blk.total_weight_kg > self.container.max_payload_kg + _EPS:
            return False
        staged, staged_recs = [], []
        for b in sorted(blk.boxes, key=lambda x: (x.oz, -x.ox, x.oy)):
            sku, px, py, pz = self.sku_map[b.sku_id], bx0 + b.ox, by0 + b.oy, bz0 + b.oz
            ok, layer, _ = self._check_box_valid(sku, px, py, pz, b.dx, b.dy, b.dz, extra_records=staged_recs)
            if not ok:
                return False
            ori = Orientation3D(b.dx, b.dy, b.dz, b.orientation, "UPRIGHT" in b.orientation, "FLAT" in b.orientation, "SIDE" in b.orientation)
            staged_recs.append(_PlacedRecord(Placement("T", "T", sku.sku_id, Point3D(px, py, pz), ori, sku.weight_kg, context, 0), px, py, pz, px + b.dx, py + b.dy, pz + b.dz, layer))
            staged.append((sku, px, py, pz, ori))
        for sku, px, py, pz, ori in staged:
            _, real_layer, real_sups = self._check_box_valid(sku, px, py, pz, ori.dx, ori.dy, ori.dz)
            self._commit_box(sku, px, py, pz, ori, context, real_layer, real_sups)
        return True

    def _score_block(self, blk: CompoundBlock, ems: EMS) -> float:
        rigid_cnt = sum(cnt for sid, cnt in blk.sku_counts.items() if not self.tensor_map[sid].is_elastic)
        if rigid_cnt == 0 and any(self.rem_qty[t.sku_id] > 0 and not t.is_elastic for t in self.tensors):
            return -1e9
        u_w = 220.0 if self.strategy == "complete_sku_first" else 40.0
        unstarted = sum(u_w for sid in blk.sku_counts if self.rem_qty.get(sid, 0) == self.sku_map[sid].quantity.required and not self.tensor_map[sid].is_elastic)
        z_fit, y_fit = blk.dz / max(1e-6, ems.dz), blk.dy / max(1e-6, ems.dy)
        y_tight = 35.0 if (ems.dy - blk.dy) < 0.12 - _EPS else 0.0
        x_tight = 30.0 if (ems.dx <= 1.50 + _EPS and (ems.dx - blk.dx) < 0.12 - _EPS) else 0.0
        if self.strategy == "volume_first":
            return blk.fill_ratio * 120.0 + z_fit * 50.0 + y_fit * 30.0 + y_tight + x_tight + blk.cargo_vol * 20.0 + blk.completes_skus * 15.0 + unstarted
        if self.strategy == "complete_sku_first":
            return blk.completes_skus * 80.0 + blk.fill_ratio * 70.0 + z_fit * 40.0 + y_fit * 25.0 + y_tight + x_tight + blk.cargo_vol * 10.0 + unstarted
        return blk.cargo_vol * 40.0 + blk.fill_ratio * 80.0 + z_fit * 35.0 + y_fit * 25.0 + y_tight + x_tight + blk.completes_skus * 25.0 + unstarted

    def _pack_door_reverse(self) -> Tuple[float, List[EMS]]:
        """门区逆向封门：从 x = Lx 往 -X 生长，返回真实占用的最小 X 边界与门区残余 EMS。"""
        door_tensors = [t for t in self.tensors if t.zone_preference == UniversalZone.DOOR and self.rem_qty[t.sku_id] > 0]
        if not door_tensors:
            return self.container.Lx, []

        door_ems = [EMS(max(0.0, self.container.Lx - 3.5), 0.0, 0.0, self.container.Lx, self.container.Ly, self.container.Lz)]
        while door_ems and any(self.rem_qty[t.sku_id] > 0 for t in door_tensors):
            door_ems.sort(key=lambda e: (e.z0 >= 1e-3, -round(e.x1, 3), round(e.z0, 3), round(e.y0, 3)))
            placed_any = False
            for e in door_ems:
                if e.dx < self.min_sku_edge - _EPS or e.dy < self.min_sku_edge - _EPS or e.dz < self.min_sku_edge - _EPS:
                    continue
                blks = generate_mixed_height_blocks(
                    door_tensors, self.rem_qty, target_h=e.dz, max_w=e.dy, max_l=e.dx,
                    allow_door=True, flexible_unspecified=self.flexible_unspecified, limit=30,
                )
                blks.sort(key=lambda b: self._score_block(b, e), reverse=True)
                for blk in blks[:12]:
                    bx0 = e.x1 - blk.dx
                    if self._try_place_block(blk, bx0, e.y0, e.z0, PlacementContext.DOOR_SEAL):
                        door_ems = _update_ems_list(door_ems, bx0, e.y0, e.z0, e.x1, e.y0 + blk.dy, e.z0 + blk.dz, self.min_sku_edge)
                        placed_any = True
                        break
                if placed_any:
                    break
            if not placed_any:
                break

        door_ems = self._fill_singles(door_ems, door_tensors, reverse_x=True, context=PlacementContext.DOOR_SEAL)
        min_x = min((r.x0 for r in self.placed), default=self.container.Lx)
        return min_x, [e for e in door_ems if e.x1 > min_x + 0.05]

    def _fill_singles(
        self, ems_list: List[EMS], pool: List[UniversalCargoTensor],
        reverse_x: bool = False, context: PlacementContext = PlacementContext.GAP_FILL,
        max_per_sku: Optional[int] = None, door_min_x: float = 0.0, focus_seam_edges: bool = False,
    ) -> List[EMS]:
        """按 EMS 优先 + 智能贴前墙逆向填缝：先地面后上层、先刚性后弹性，消除单箱倾覆误杀。"""
        if max_per_sku == 1:
            for t in pool:
                if self.rem_qty.get(t.sku_id, 0) <= 0 or not ems_list:
                    continue
                sku = self.sku_map[t.sku_id]
                ems_list.sort(key=lambda e: (e.z0 >= 1e-3, -round(e.x1, 3) if reverse_x else round(e.x0, 3), round(e.z0, 3), round(e.y0, 3)))
                placed_one = False
                for e in ems_list:
                    ctx = PlacementContext.TOP_FILL if e.z0 >= 1e-3 else context
                    oris = sku.orientation_policy.get_legal_orientations(sku.box, ctx)
                    if not oris and self.flexible_unspecified and not _is_fragile_sku(sku) and not _is_upright_locked(sku):
                        oris = sku.orientation_policy.get_legal_orientations(sku.box, PlacementContext.GENERAL)
                    use_rev = reverse_x or self._has_front_wall(e)
                    for o in oris:
                        if o.dx > e.dx + _EPS or o.dy > e.dy + _EPS or o.dz > e.dz + _EPS:
                            continue
                        for px in ((e.x1 - o.dx, e.x0) if use_rev else (e.x0, e.x1 - o.dx)):
                            for py in (e.y0, e.y1 - o.dy):
                                ok, layer, sups = self._check_box_valid(sku, px, py, e.z0, o.dx, o.dy, o.dz)
                                if ok:
                                    self._commit_box(sku, px, py, e.z0, o, ctx, layer, sups)
                                    ems_list = _update_ems_list(ems_list, px, py, e.z0, px + o.dx, py + o.dy, e.z0 + o.dz, self.min_sku_edge, merge=False)
                                    placed_one = True
                                    break
                            if placed_one: break
                        if placed_one: break
                    if placed_one: break
            return _merge_adjacent_ems(ems_list)

        for _ in range(3000):
            active_pool = [t for t in pool if self.rem_qty.get(t.sku_id, 0) > 0]
            if not active_pool or not ems_list:
                break
            active_pool.sort(key=lambda t: (1 if t.is_elastic else 0, 0 if self.rem_qty[t.sku_id] <= 5 else 1, -t.volume_m3))
            cands = ems_list if not focus_seam_edges else [
                e for e in ems_list if e.x1 >= door_min_x - 0.80 or e.y0 < 0.05 or e.y1 > self.container.Ly - 0.05 or e.dx < 0.80 or e.dy < 0.80
            ]
            cands = sorted(cands, key=lambda e: (e.z0 >= 1e-3, -round(e.x1, 3) if reverse_x else round(e.x0, 3), round(e.z0, 3), round(e.y0, 3)))
            placed_any = False
            for e in cands:
                if e.dx < self.min_sku_edge - _EPS or e.dy < self.min_sku_edge - _EPS or e.dz < self.min_sku_edge - _EPS:
                    continue
                ctx, use_rev, best = (PlacementContext.TOP_FILL if e.z0 >= 1e-3 else context), (reverse_x or self._has_front_wall(e)), None
                for t in active_pool:
                    sku = self.sku_map[t.sku_id]
                    oris = sku.orientation_policy.get_legal_orientations(sku.box, ctx)
                    if not oris and self.flexible_unspecified and not _is_fragile_sku(sku) and not _is_upright_locked(sku):
                        oris = sku.orientation_policy.get_legal_orientations(sku.box, PlacementContext.GENERAL)
                    for o in oris:
                        if o.dx > e.dx + _EPS or o.dy > e.dy + _EPS or o.dz > e.dz + _EPS:
                            continue
                        px = (e.x1 - o.dx) if use_rev else e.x0
                        ok, layer, sups = self._check_box_valid(sku, px, e.y0, e.z0, o.dx, o.dy, o.dz)
                        if not ok:
                            continue
                        sc = (0.0 if not t.is_elastic else -50.0) + (o.dx * o.dy * o.dz) / max(1e-9, e.volume) * 10.0 + (2.0 if abs(e.dz - o.dz) < 0.05 else 0.0) + (1.5 if abs(e.dy - o.dy) < 0.05 else 0.0)
                        if best is None or sc > best[0]:
                            best = (sc, sku, o, px, layer, sups)
                if best is not None:
                    _, sku, o, px, layer, sups = best
                    self._commit_box(sku, px, e.y0, e.z0, o, ctx, layer, sups)
                    ems_list = _update_ems_list(ems_list, px, e.y0, e.z0, px + o.dx, e.y0 + o.dy, e.z0 + o.dz, self.min_sku_edge, merge=False)
                    placed_any = True
                    break
            if not placed_any:
                break
        return _merge_adjacent_ems(ems_list)

    def run(self) -> List[Placement]:
        door_min_x, door_rem_ems = self._pack_door_reverse()
        main_tensors = [t for t in self.tensors if t.zone_preference != UniversalZone.DOOR]
        ems_list = [EMS(0.0, 0.0, 0.0, max(0.0, door_min_x), self.container.Ly, self.container.Lz)]

        for _ in range(500):
            if not ems_list or not any(self.rem_qty[t.sku_id] > 0 for t in main_tensors):
                break
            ems_list.sort(key=lambda e: (e.z0 >= 1e-3, e.dy < 0.45, round(e.x0, 2), round(e.z0, 2), round(e.y0, 2)))
            placed_any, tried_dims = False, set()
            for e in ems_list:
                if e.volume < 0.04 or e.dx < 0.25 or e.dy < 0.25 or e.dz < 0.30:
                    continue
                front_wall = self._has_front_wall(e)
                dim_key = (round(e.dx, 2), round(e.dy, 2), round(e.dz, 2), front_wall)
                if dim_key in tried_dims:
                    continue
                tried_dims.add(dim_key)
                blks = generate_mixed_height_blocks(main_tensors, self.rem_qty, e.dz, e.dy, e.dx, False, self.flexible_unspecified, 30)
                blks.sort(key=lambda b: self._score_block(b, e), reverse=True)
                for blk in blks[:12]:
                    if self._score_block(blk, e) < -1e8:
                        continue
                    for bx0 in ([e.x1 - blk.dx, e.x0] if front_wall else [e.x0]):
                        if self._try_place_block(blk, bx0, e.y0, e.z0, PlacementContext.MAIN_WALL):
                            ems_list = _update_ems_list(ems_list, bx0, e.y0, e.z0, bx0 + blk.dx, e.y0 + blk.dy, e.z0 + blk.dz, self.min_sku_edge)
                            placed_any = True; break
                    if placed_any: break
                if placed_any or len(tried_dims) >= 16: break
            if not placed_any: break

        ems_list.extend(door_rem_ems)
        unstarted = [t for t in main_tensors if self.rem_qty[t.sku_id] == self.sku_map[t.sku_id].quantity.required and not t.is_elastic]
        if unstarted:
            ems_list = self._fill_singles(ems_list, unstarted, reverse_x=False, context=PlacementContext.GAP_FILL, max_per_sku=1, door_min_x=door_min_x)
        ems_list = self._fill_singles(ems_list, main_tensors, reverse_x=False, context=PlacementContext.GAP_FILL, door_min_x=door_min_x, focus_seam_edges=True)
        self._fill_singles(ems_list, main_tensors, reverse_x=False, context=PlacementContext.GAP_FILL, door_min_x=door_min_x)
        return [r.placement for r in self.placed]


def _score_solution(placements: List[Placement], cargo_list: List[CargoSKU], val_res: Any) -> float:
    placed_cnt: Dict[str, int] = {}
    for p in placements:
        placed_cnt[p.sku_id] = placed_cnt.get(p.sku_id, 0) + 1
    packed_vol = sum(p.volume for p in placements)
    completed = sum(1 for s in cargo_list if s.quantity.required > 0 and placed_cnt.get(s.sku_id, 0) >= s.quantity.required)
    starved = sum(1 for s in cargo_list if s.quantity.required > 0 and placed_cnt.get(s.sku_id, 0) == 0)
    rigid_unfilled = sum(s.quantity.required - placed_cnt.get(s.sku_id, 0) for s in cargo_list if not s.quantity.is_elastic and placed_cnt.get(s.sku_id, 0) < s.quantity.required)
    elastic_placed = sum(placed_cnt.get(s.sku_id, 0) for s in cargo_list if s.quantity.is_elastic)
    inv_pen = 10000.0 if (rigid_unfilled > 0 and elastic_placed > 0) else 0.0
    viol_pen = len(getattr(val_res, "violations", []) or []) * 5000.0
    col_pen = int(getattr(val_res, "overlap_pair_count", 0) or 0) * 10000.0
    return packed_vol * 100.0 + completed * 50.0 - starved * 5000.0 - inv_pen - viol_pen - col_pen


def solve_bidirectional_ems(container: ContainerSpec, cargo_list: List[CargoSKU], flexible_unspecified: bool = False) -> SolverSolution:
    """运行 3 条策略并择优返回通过 IndependentGlobalValidator 验证的 SolverSolution。"""
    t0 = time.time()
    effective_cargo = build_flexible_cargo_list(cargo_list) if flexible_unspecified else cargo_list
    best_score, best_solution, total_req = -1e18, None, sum(s.quantity.required for s in effective_cargo)
    for strat in ("volume_first", "complete_sku_first", "large_then_gap"):
        placements = _SingleStrategyRunner(container, effective_cargo, strat, flexible_unspecified).run()
        val_res = IndependentGlobalValidator.validate(container, placements, effective_cargo)
        sc = _score_solution(placements, effective_cargo, val_res)
        if sc > best_score:
            best_score, packed_vol = sc, sum(p.volume for p in placements)
            tel = SolverTelemetry(runtime_ms=(time.time() - t0) * 1000.0, steps_committed=len(placements))
            tel.phases_completed = [f"BIDIRECTIONAL_EMS:{strat}"]
            best_solution = SolverSolution(
                "OPTIMAL" if val_res.is_valid else "FEASIBLE", container, placements, len(placements),
                max(0, total_req - len(placements)), 100.0 * packed_vol / max(1e-9, container.volume),
                sum(p.weight_kg for p in placements), val_res, tel,
            )
    assert best_solution is not None
    best_solution.telemetry.runtime_ms = (time.time() - t0) * 1000.0
    return best_solution
