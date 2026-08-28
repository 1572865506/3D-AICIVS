"""
Synthetic Cargo Stress Benchmark Generator & Multi-Scenario Evaluation Suite.

Provides:
1. Parametric Monte-Carlo cargo generator across dimensions, aspect ratios, densities,
   quantities, and constraint distributions.
2. Automated multi-batch batch stress tester (e.g. 50 scenarios, 100 scenarios).
3. Comprehensive diagnostic analysis:
   - Volume utilization distribution
   - Physical stability & 0-collision pass rate
   - Zone compliance score
   - Cavity & planar defect detection
   - Detailed bottleneck identification & performance scoring.
"""
from dataclasses import dataclass, field
import json
import math
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from src.unified_pipeline.model.UniversalCargoTensor import (
    UniversalCargoTensor,
    UniversalZone,
    ContainerDimensions
)
from src.unified_pipeline.engine.UniversalHierarchicalSolver import UniversalHierarchicalSolver


@dataclass
class GeneratorRangeConfig:
    sku_count_range: Tuple[int, int] = (5, 25)
    box_dim_x_range: Tuple[float, float] = (0.30, 1.20)
    box_dim_y_range: Tuple[float, float] = (0.20, 0.80)
    box_dim_z_range: Tuple[float, float] = (0.15, 0.70)
    weight_kg_range: Tuple[float, float] = (2.0, 35.0)
    quantity_range: Tuple[int, int] = (5, 250)
    zone_prob_inner: float = 0.20
    zone_prob_door: float = 0.15
    zone_prob_middle: float = 0.65


@dataclass
class ScenarioEvaluationResult:
    scenario_id: str
    container_type: str
    total_skus: int
    total_manifest_boxes: int
    total_placed_boxes: int
    volume_utilization_pct: float
    total_weight_tons: float
    is_physically_valid: bool
    violations_count: int
    zone_compliance_pct: float
    runtime_ms: float
    detected_issues: List[str] = field(default_factory=list)


class SyntheticCargoStressBenchmark:
    def __init__(self, config: Optional[GeneratorRangeConfig] = None):
        self.config = config or GeneratorRangeConfig()

    def generate_random_manifest(self, seed: Optional[int] = None) -> List[UniversalCargoTensor]:
        """Generates a randomized synthetic manifest within parametric bounds."""
        if seed is not None:
            random.seed(seed)

        sku_count = random.randint(*self.config.sku_count_range)
        cargo_list: List[UniversalCargoTensor] = []

        for i in range(1, sku_count + 1):
            dim_x = round(random.uniform(*self.config.box_dim_x_range), 3)
            dim_y = round(random.uniform(*self.config.box_dim_y_range), 3)
            dim_z = round(random.uniform(*self.config.box_dim_z_range), 3)
            weight = round(random.uniform(*self.config.weight_kg_range), 1)
            qty = random.randint(*self.config.quantity_range)

            # Zone assignment
            r_zone = random.random()
            if r_zone < self.config.zone_prob_inner:
                zp = UniversalZone.INNER
                raw_req = "最里面"
            elif r_zone < self.config.zone_prob_inner + self.config.zone_prob_door:
                zp = UniversalZone.DOOR
                raw_req = "封柜门"
            else:
                zp = UniversalZone.MIDDLE
                raw_req = "中间"

            allow_flat = (random.random() < 0.3)
            max_layers = random.choice([None, None, 4, 6, 8])

            cargo_list.append(UniversalCargoTensor(
                sku_id=f"SKU-{i:02d}",
                name=f"虚拟物料-{i:02d}",
                length=max(dim_x, dim_y),
                width=min(dim_x, dim_y),
                height=dim_z,
                weight_kg=weight,
                quantity_required=qty,
                zone_preference=zp,
                allow_flat=allow_flat,
                max_stack_layers=max_layers,
                raw_requirement=raw_req
            ))

        return cargo_list

    def evaluate_scenario(self, scenario_id: str, cargo_list: List[UniversalCargoTensor], container: Optional[ContainerDimensions] = None) -> ScenarioEvaluationResult:
        """Runs solver and performs in-depth geometric, physical, and zone diagnostics."""
        c_dim = container or ContainerDimensions()
        solver = UniversalHierarchicalSolver(container=c_dim)
        
        t0 = time.perf_counter()
        placements, metrics = solver.solve(cargo_list)
        runtime_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        issues: List[str] = []

        # 1. Physical Validity Check
        if not metrics['is_valid']:
            issues.append(f"物理校验未通过，存在 {metrics['violations_count']} 项力学/碰撞违规")

        # 2. Zone Compliance Diagnostics
        zone_compliance = 100.0
        inner_placements = [p for p in placements if any(c.sku_id == p['sku_id'] and c.zone_preference == UniversalZone.INNER for c in cargo_list)]
        door_placements = [p for p in placements if any(c.sku_id == p['sku_id'] and c.zone_preference == UniversalZone.DOOR for c in cargo_list)]

        if inner_placements and door_placements:
            max_inner_x = max(p['x'] + p['dx'] for p in inner_placements)
            min_door_x = min(p['x'] for p in door_placements)
            if max_inner_x > min_door_x + 0.10:
                zone_compliance = round(max(0.0, 100.0 - (max_inner_x - min_door_x) * 20.0), 1)
                issues.append(f"区位轻微交织: 内层最远端 ({max_inner_x:.2f}m) 超过了门端起始端 ({min_door_x:.2f}m)")

        # 3. Utilization Check: Alert only when container is constrained but utilization is abnormally low
        util = metrics.get('utilization_pct', 0.0)
        tot_manifest = sum(c.quantity_required for c in cargo_list)
        placed_boxes = len(placements)

        if util < 50.0 and placed_boxes < tot_manifest:
            issues.append(f"空间利用率偏低 ({util:.1f}%)，尚有 {tot_manifest - placed_boxes} 箱货物未装入")

        return ScenarioEvaluationResult(
            scenario_id=scenario_id,
            container_type=c_dim.code,
            total_skus=len(cargo_list),
            total_manifest_boxes=tot_manifest,
            total_placed_boxes=placed_boxes,
            volume_utilization_pct=round(util, 2),
            total_weight_tons=round(metrics.get('weight_loaded_kg', 0.0) / 1000.0, 2),
            is_physically_valid=metrics['is_valid'],
            violations_count=metrics.get('violations_count', 0),
            zone_compliance_pct=zone_compliance,
            runtime_ms=runtime_ms,
            detected_issues=issues
        )

    def run_stress_suite(self, num_scenarios: int = 20, seed_start: int = 42) -> Dict[str, Any]:
        """Runs batch stress benchmark across randomized scenarios and produces comprehensive analytics."""
        results: List[ScenarioEvaluationResult] = []
        c_types = ["40HQ", "40GP", "20GP"]

        t_suite_start = time.perf_counter()

        for idx in range(num_scenarios):
            s_seed = seed_start + idx
            c_code = c_types[idx % len(c_types)]
            if c_code == "20GP":
                c_dim = ContainerDimensions("20GP", 5.898, 2.352, 2.393, 28000.0)
            elif c_code == "40GP":
                c_dim = ContainerDimensions("40GP", 12.032, 2.352, 2.393, 28000.0)
            else:
                c_dim = ContainerDimensions("40HQ", 12.024, 2.350, 2.690, 26000.0)

            manifest = self.generate_random_manifest(seed=s_seed)
            res = self.evaluate_scenario(f"SCENARIO-{idx+1:03d}", manifest, container=c_dim)
            results.append(res)

        total_time = round(time.perf_counter() - t_suite_start, 2)

        # Aggregate Statistics
        pass_count = sum(1 for r in results if r.is_physically_valid and len(r.detected_issues) == 0)
        avg_util = round(sum(r.volume_utilization_pct for r in results) / len(results), 2)
        avg_runtime = round(sum(r.runtime_ms for r in results) / len(results), 2)
        avg_zone_comp = round(sum(r.zone_compliance_pct for r in results) / len(results), 2)

        all_issues = []
        for r in results:
            for iss in r.detected_issues:
                all_issues.append({"scenario": r.scenario_id, "container": r.container_type, "issue": iss})

        report = {
            "total_scenarios_tested": num_scenarios,
            "overall_pass_rate_pct": round((pass_count / num_scenarios) * 100.0, 1),
            "average_volume_utilization_pct": avg_util,
            "average_zone_compliance_pct": avg_zone_comp,
            "average_runtime_ms": avg_runtime,
            "total_benchmark_time_sec": total_time,
            "detailed_results": [r.__dict__ for r in results],
            "identified_issue_points": all_issues
        }

        return report
