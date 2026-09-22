# -*- coding: utf-8 -*-
"""
高质量方案沉淀与数据归档流水线 (Solution Collector & Quality Archive Pipeline)

连接工况合成器、求解引擎、物理验证器与防蜂窝空洞过滤器，
完成金牌示范方案库 (Golden Dataset Repository) 的批量自动化生成与沉淀。

核心步骤:
  1. 批量调度 ManifestSynthesizer 生成工业级工况
  2. 驱动求解器运行 (支持多种子扰动策略探索)
  3. 执行物理内核前置核验与 IndependentGlobalValidator 独立审计
  4. 运用 AntiCavityFilter 过滤内部蜂窝空洞、饥饿弃装与优先级倒挂
  5. 序列化归档至 data/golden_solutions/ 供 Transformer 大脑训练

被谁调用:
  - scripts/run_data_factory.py (生产流水线 CLI)
  - tests/test_data_pipeline.py (数据工场端到端单测)
"""
from __future__ import annotations

import os
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from ..domain.models import ContainerSpec, CargoSKU
from .manifest_synthesizer import ManifestSynthesizer
from .anti_cavity_filter import AntiCavityFilter, QualityAuditReport


class SolutionCollector:
    """高质量方案沉淀收集器"""

    def __init__(
        self,
        output_dir: str = "data/golden_solutions",
        synthesizer: Optional[ManifestSynthesizer] = None,
        quality_filter: Optional[AntiCavityFilter] = None,
    ):
        self.output_dir = output_dir
        self.synthesizer = synthesizer or ManifestSynthesizer()
        self.quality_filter = quality_filter or AntiCavityFilter()
        os.makedirs(self.output_dir, exist_ok=True)

    def process_and_archive(
        self,
        scenario_id: str,
        container: ContainerSpec,
        cargo_skus: List[CargoSKU],
        placements: List[Any],
        execution_time_ms: float = 0.0,
    ) -> Optional[QualityAuditReport]:
        """审计单次求解方案，若为 GOLD 或 SILVER 则归档保存"""
        report = self.quality_filter.audit_solution(
            solution_id=scenario_id,
            container=container,
            placements=placements,
            cargo_skus=cargo_skus,
        )

        # 仅沉淀 GOLD 与合格 SILVER 方案，严厉淘汰 REJECT
        if report.rating in ("GOLD", "SILVER"):
            solution_payload = {
                "solution_id": scenario_id,
                "rating": report.rating,
                "score": report.score,
                "quality_tags": report.quality_tags,
                "metrics": {
                    "volume_utilization_pct": report.volume_utilization_pct,
                    "rigid_fulfillment_pct": report.rigid_fulfillment_pct,
                    "elastic_completion_pct": report.elastic_completion_pct,
                    "enclosed_cavity_ratio_pct": report.enclosed_cavity_ratio_pct,
                    "interlock_score": report.interlock_score,
                    "execution_time_ms": execution_time_ms,
                },
                "container": {
                    "code": container.code,
                    "inner_dim": [container.inner_dim.x, container.inner_dim.y, container.inner_dim.z],
                    "max_payload_kg": container.max_payload_kg,
                    "door_zone_length_m": container.door_zone_length_m,
                },
                "cargo_skus": [
                    {
                        "sku_id": s.sku_id,
                        "name": s.name,
                        "box": [s.box.x, s.box.y, s.box.z],
                        "weight_kg": s.weight_kg,
                        "required_qty": s.quantity.required,
                        "max_bearing_kg": getattr(s.stacking_policy, "max_bearing_kg", None),
                        "max_stack_layers": getattr(s.stacking_policy, "max_stack_layers", None),
                        "must_be_on_floor": getattr(s.stacking_policy, "must_be_on_floor", False),
                        "allow_stacking_on_top": getattr(s.stacking_policy, "allow_stacking_on_top", True),
                    }
                    for s in cargo_skus
                ],
                "placements": [
                    {
                        "placement_id": str(p["placement_id"] if isinstance(p, dict) else getattr(p, "placement_id", "")),
                        "sku_id": (p["sku_id"] if isinstance(p, dict) else getattr(p, "sku_id", "")),
                        "position": [
                            p["x"] if isinstance(p, dict) else getattr(getattr(p, "position", None), "x", 0.0),
                            p["y"] if isinstance(p, dict) else getattr(getattr(p, "position", None), "y", 0.0),
                            p["z"] if isinstance(p, dict) else getattr(getattr(p, "position", None), "z", 0.0),
                        ],
                        "dimension": [
                            p["dx"] if isinstance(p, dict) else getattr(getattr(p, "orientation", None), "dx", 1.0),
                            p["dy"] if isinstance(p, dict) else getattr(getattr(p, "orientation", None), "dy", 1.0),
                            p["dz"] if isinstance(p, dict) else getattr(getattr(p, "orientation", None), "dz", 1.0),
                        ],
                        "weight_kg": (p["weight_kg"] if isinstance(p, dict) else getattr(p, "weight_kg", 0.0)),
                    }
                    for p in placements
                ],
                "archived_at": time.time(),
            }

            # 存入对应分级文件
            file_name = f"{report.rating.lower()}_{scenario_id}.json"
            target_path = os.path.join(self.output_dir, file_name)
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(solution_payload, f, ensure_ascii=False, indent=2)

            # 同时追加写入聚合 jsonl
            jsonl_path = os.path.join(self.output_dir, "dataset_index.jsonl")
            with open(jsonl_path, "a", encoding="utf-8") as f:
                index_entry = {
                    "solution_id": scenario_id,
                    "rating": report.rating,
                    "score": report.score,
                    "utilization": report.volume_utilization_pct,
                    "rigid": report.rigid_fulfillment_pct,
                    "cavity_ratio": report.enclosed_cavity_ratio_pct,
                    "interlock": report.interlock_score,
                    "file": file_name,
                }
                f.write(json.dumps(index_entry, ensure_ascii=False) + "\n")

        return report
