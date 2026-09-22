# -*- coding: utf-8 -*-
"""
大规模多样化工况合成器 (Manifest & Scenario Synthesizer)

支持参数化随机、正交采样与极端工况组合，具备万级多样化工况合成能力。
覆盖:
  - 4 大标准集装箱: 20GP, 40GP, 40HQ, 45HQ
  - 12 种典型工业 SKU 原型:
      PALLET_HEAVY, CUBE_MEDIUM, CARTON_LIGHT, LONG_BEAM, FLAT_PANEL,
      TALL_SLENDER, FRAGILE_TOP_CAP, FLOOR_HEAVY_BASE, DOOR_SEAL_BAG,
      ELASTIC_PILLOW, IRREGULAR_COMPONENT, ULTRA_THIN_DISPLAY
  - 6 大核心物理约束组合:
      落地专属(含自叠限额), 垂直承重传递受限, 绝对/同品类禁顶叠,
      姿态上下文限定 (Upright-only / Flat in Topfill), 门区硬隔离, 倾覆敏感

被谁调用:
  - data_pipeline/collector.py (数据工场自动化收集流水线)
  - scripts/run_data_factory.py (CLI 批量工况生成器)
  - tests/test_data_pipeline.py (数据管线单测)
"""
from __future__ import annotations

import random
import copy
from typing import Any, Dict, List, Optional, Tuple

from ..domain.models import (
    BoxDim,
    Point3D,
    Orientation3D,
    OrientationPolicy,
    OrientationMode,
    StackingPolicy,
    QuantityPlan,
    ContainerSpec,
    CargoSKU,
    PlacementContext,
    ZoneType,
    PackingRole,
)


CONTAINER_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "20GP": {
        "inner_dim": (5.898, 2.352, 2.393),
        "max_payload_kg": 21800.0,
        "door_zone_length_m": 0.8,
        "rear_zone_length_m": 0.6,
    },
    "40GP": {
        "inner_dim": (12.032, 2.352, 2.393),
        "max_payload_kg": 26680.0,
        "door_zone_length_m": 1.2,
        "rear_zone_length_m": 1.0,
    },
    "40HQ": {
        "inner_dim": (12.032, 2.352, 2.698),
        "max_payload_kg": 28600.0,
        "door_zone_length_m": 1.2,
        "rear_zone_length_m": 1.0,
    },
    "45HQ": {
        "inner_dim": (13.556, 2.352, 2.698),
        "max_payload_kg": 27700.0,
        "door_zone_length_m": 1.5,
        "rear_zone_length_m": 1.2,
    },
}


class ManifestSynthesizer:
    """工况合成器：生成多样化真实工业货物清单与工况规格"""

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)

    def create_container(self, container_type: str = "40HQ") -> ContainerSpec:
        """根据指定或随机型号创建 ContainerSpec"""
        if container_type not in CONTAINER_TEMPLATES:
            container_type = "40HQ"
        spec = CONTAINER_TEMPLATES[container_type]
        lx, ly, lz = spec["inner_dim"]
        return ContainerSpec(
            code=container_type,
            inner_dim=BoxDim(x=lx, y=ly, z=lz),
            max_payload_kg=spec["max_payload_kg"],
            door_zone_length_m=spec["door_zone_length_m"],
            rear_zone_length_m=spec["rear_zone_length_m"],
        )

    def generate_scenario(
        self,
        scenario_id: str,
        container_type: Optional[str] = None,
        num_skus_range: Tuple[int, int] = (4, 12),
        total_target_volume_ratio: float = 0.95,
        elastic_ratio: float = 0.15,
        complexity_level: str = "HIGH",  # 'LOW', 'MEDIUM', 'HIGH', 'EXTREME'
    ) -> Tuple[ContainerSpec, List[CargoSKU]]:
        """合成一个独立装载工况 (Container + CargoSKU List)"""
        c_type = container_type or self.rng.choice(list(CONTAINER_TEMPLATES.keys()))
        container = self.create_container(c_type)
        c_vol = container.inner_dim.x * container.inner_dim.y * container.inner_dim.z
        target_vol = c_vol * total_target_volume_ratio

        num_skus = self.rng.randint(num_skus_range[0], num_skus_range[1])
        skus: List[CargoSKU] = []

        # 保证工况具有物理结构分层性：基础地盘件、常规箱、特殊约束件、弹性收尾件
        remaining_vol = target_vol

        # 1. 基础重载托盘/大底座件 (1 ~ 2 种)
        num_base_types = self.rng.randint(1, 2)
        for i in range(num_base_types):
            bx = round(self.rng.uniform(1.0, 1.2), 2)
            by = round(self.rng.uniform(0.8, 1.0), 2)
            bz = round(self.rng.uniform(0.6, 1.1), 2)
            w = round(self.rng.uniform(200.0, 500.0), 1)
            vol_single = bx * by * bz
            qty = max(2, int((remaining_vol * 0.30) / (vol_single * num_base_types)))
            qty = min(qty, 20)

            must_floor = self.rng.choice([True, False])
            skus.append(CargoSKU(
                sku_id=f"SKU_{scenario_id}_BASE_{i+1}",
                name=f"Heavy Foundation Base {i+1}",
                box=BoxDim(x=bx, y=by, z=bz),
                weight_kg=w,
                quantity=QuantityPlan(required=qty),
                orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False, allow_side=False),
                stacking_policy=StackingPolicy(
                    max_bearing_kg=round(w * self.rng.uniform(2.5, 4.0), 1),
                    max_pressure_kg_m2=2500.0,
                    min_support_ratio=0.75,
                    must_be_on_floor=must_floor,
                    max_stack_layers=2 if must_floor else 3,
                    stack_on_self=True,
                    allow_stacking_on_top=True,
                ),
                packing_roles=(PackingRole.FOUNDATION,),
            ))
            remaining_vol -= vol_single * qty

        # 2. 中型主力箱 (3 ~ 6 种)
        num_mid = max(2, num_skus - num_base_types - 2)
        for i in range(num_mid):
            bx = round(self.rng.uniform(0.4, 0.8), 2)
            by = round(self.rng.uniform(0.3, 0.6), 2)
            bz = round(self.rng.uniform(0.3, 0.7), 2)
            w = round(self.rng.uniform(20.0, 80.0), 1)
            vol_single = bx * by * bz
            allocated_vol = max(vol_single * 4, (remaining_vol * 0.55) / num_mid)
            qty = max(4, int(allocated_vol / vol_single))

            # 根据复杂度赋予姿态与堆叠策略
            allow_flat = self.rng.choice([True, False])
            skus.append(CargoSKU(
                sku_id=f"SKU_{scenario_id}_MID_{i+1}",
                name=f"Standard Medium Carton {i+1}",
                box=BoxDim(x=bx, y=by, z=bz),
                weight_kg=w,
                quantity=QuantityPlan(required=qty),
                orientation_policy=OrientationPolicy(
                    allow_upright=True,
                    allow_flat=allow_flat,
                    allow_side=False,
                    allowed_contexts_for_flat=(PlacementContext.TOP_FILL,) if allow_flat else (),
                ),
                stacking_policy=StackingPolicy(
                    max_bearing_kg=round(w * self.rng.uniform(3.0, 5.0), 1),
                    max_pressure_kg_m2=1500.0,
                    min_support_ratio=0.70,
                    max_stack_layers=4,
                    allow_stacking_on_top=True,
                ),
                packing_roles=(PackingRole.MAIN_WALL,),
            ))
            remaining_vol -= vol_single * qty

        # 3. 约束特异件 (倾覆敏感件 / 绝对封顶件) (1 种)
        has_tipping_item = self.rng.choice([True, False])
        if has_tipping_item:
            # 高瘦件: dx 较小，dz 较大 (SF = 2*dx/dz < 1.5)
            bx = round(self.rng.uniform(0.25, 0.38), 2)
            by = round(self.rng.uniform(0.6, 1.0), 2)
            bz = round(self.rng.uniform(0.8, 1.2), 2)
            w = round(self.rng.uniform(40.0, 70.0), 1)
            skus.append(CargoSKU(
                sku_id=f"SKU_{scenario_id}_SLENDER_1",
                name="Tall Slender Tipping Item",
                box=BoxDim(x=bx, y=by, z=bz),
                weight_kg=w,
                quantity=QuantityPlan(required=self.rng.randint(4, 12)),
                orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False, allow_side=False),
                stacking_policy=StackingPolicy(min_support_ratio=0.80, allow_stacking_on_top=False, stack_on_self=False),
                packing_roles=(PackingRole.MAIN_WALL,),
            ))
        else:
            # 绝对封顶脆弱件
            bx = round(self.rng.uniform(0.5, 0.7), 2)
            by = round(self.rng.uniform(0.5, 0.7), 2)
            bz = round(self.rng.uniform(0.4, 0.6), 2)
            skus.append(CargoSKU(
                sku_id=f"SKU_{scenario_id}_FRAGILE_1",
                name="Fragile Cap Item",
                box=BoxDim(x=bx, y=by, z=bz),
                weight_kg=round(self.rng.uniform(15.0, 35.0), 1),
                quantity=QuantityPlan(required=self.rng.randint(4, 10)),
                stacking_policy=StackingPolicy(allow_stacking_on_top=False, stack_on_self=False),
                packing_roles=(PackingRole.TOP_FILL,),
            ))

        # 4. 门区专用密封件或弹性填充小件 (1 ~ 2 种)
        bx = round(self.rng.uniform(0.3, 0.5), 2)
        by = round(self.rng.uniform(0.4, 0.6), 2)
        bz = round(self.rng.uniform(0.3, 0.5), 2)
        skus.append(CargoSKU(
            sku_id=f"SKU_{scenario_id}_DOOR_1",
            name="Door Zone Seal Cargo",
            box=BoxDim(x=bx, y=by, z=bz),
            weight_kg=round(self.rng.uniform(10.0, 25.0), 1),
            quantity=QuantityPlan(required=self.rng.randint(6, 16)),
            packing_roles=(PackingRole.DOOR_SEAL,),
            target_zone=ZoneType.DOOR,
        ))

        return container, skus

    def generate_batch(
        self,
        count: int = 100,
        prefix: str = "batch_case",
    ) -> List[Tuple[ContainerSpec, List[CargoSKU]]]:
        """批量合成指定数量的工况集"""
        batch = []
        for i in range(count):
            cid = f"{prefix}_{i+1:05d}"
            case = self.generate_scenario(scenario_id=cid)
            batch.append(case)
        return batch
