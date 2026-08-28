"""
Universal Packing Pipeline Automated Regression Test Suite.

Runs 5 standardized industrial benchmark cases to ensure universal robustness:
- Benchmark 01: Standard 14-SKU Cleanroom Benchmark (40HQ Mixed)
- Benchmark 02: Massive Batch SKU + Minor Residual Tails
- Benchmark 03: 30+ Highly Discrete Multi-SKU Cargo
- Benchmark 04: Strict Business Zone Isolation & Heavy Bottom Loading
- Benchmark 05: Multi-Container Type Adaptability (20GP, 40GP, 40HQ, 45HQ, 53FT)
"""
import json
import time
import unittest
from typing import List

from src.unified_pipeline.model.UniversalCargoTensor import (
    UniversalCargoTensor,
    UniversalZone,
    ContainerDimensions
)
from src.unified_pipeline.engine.UniversalHierarchicalSolver import UniversalHierarchicalSolver


class TestUniversalPipelineRegression(unittest.TestCase):

    def setUp(self):
        with open('devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json', 'r', encoding='utf-8') as f:
            self.cleanroom_case = json.load(f)

    def test_benchmark_01_standard_14_sku_cleanroom(self):
        """Benchmark 01: 14-SKU Cleanroom baseline (1845 cartons, 40HQ container)."""
        cargo_list = []
        for item in self.cleanroom_case['cargo']:
            src = item['source']
            cargo_list.append(UniversalCargoTensor(
                sku_id=item['sku'],
                name=item['name'],
                length=max(src['w'], src['d']),
                width=min(src['w'], src['d']),
                height=src['h'],
                weight_kg=src['weight'],
                quantity_required=src['quantity'],
                raw_requirement=src.get('requirement', '')
            ))

        solver = UniversalHierarchicalSolver()
        placements, metrics = solver.solve(cargo_list)

        self.assertTrue(metrics['is_valid'], f"Benchmark 01 physics validation failed: {metrics.get('violations_count')} violations")
        self.assertEqual(metrics['violations_count'], 0)
        self.assertGreater(metrics['total_boxes'], 1500, "Placed box count should be >= 1500")
        self.assertGreater(metrics['utilization_pct'], 65.0, "Volume utilization should be >= 65%")
        print(f"\n[BENCHMARK 01 PASSED] 14-SKU: Placed {metrics['total_boxes']}/1845 | Vol Util: {metrics['utilization_pct']:.2f}% | Runtime: {metrics['telemetry']['runtime_ms']}ms")

    def test_benchmark_02_massive_batches_plus_tails(self):
        """Benchmark 02: Massive batch SKUs + minor residual tails."""
        cargo_list = [
            UniversalCargoTensor(sku_id="BIG-01", name="大单品A", length=0.60, width=0.40, height=0.45, weight_kg=15.0, quantity_required=400, raw_requirement="最里面"),
            UniversalCargoTensor(sku_id="BIG-02", name="大单品B", length=0.55, width=0.35, height=0.30, weight_kg=10.0, quantity_required=500, raw_requirement="中间"),
            UniversalCargoTensor(sku_id="BIG-03", name="大单品C", length=0.50, width=0.50, height=0.35, weight_kg=12.0, quantity_required=300, raw_requirement="门"),
            UniversalCargoTensor(sku_id="TAIL-01", name="配件散箱X", length=0.30, width=0.20, height=0.20, weight_kg=3.0, quantity_required=15, raw_requirement="中间"),
            UniversalCargoTensor(sku_id="TAIL-02", name="配件散箱Y", length=0.25, width=0.25, height=0.15, weight_kg=2.0, quantity_required=8, raw_requirement="封门")
        ]

        solver = UniversalHierarchicalSolver()
        placements, metrics = solver.solve(cargo_list)

        self.assertTrue(metrics['is_valid'], f"Benchmark 02 validation failed: {metrics['violations_count']} violations")
        self.assertEqual(metrics['violations_count'], 0)
        self.assertGreater(metrics['utilization_pct'], 70.0)
        print(f"[BENCHMARK 02 PASSED] Massive Batches: Placed {metrics['total_boxes']}/1223 | Vol Util: {metrics['utilization_pct']:.2f}%")

    def test_benchmark_03_highly_discrete_32_skus(self):
        """Benchmark 03: 32 highly diverse SKUs with small batches."""
        cargo_list = []
        for i in range(1, 33):
            cargo_list.append(UniversalCargoTensor(
                sku_id=f"DISCRETE-{i:02d}",
                name=f"杂货品类-{i}",
                length=0.40 + (i % 5) * 0.05,
                width=0.30 + (i % 4) * 0.04,
                height=0.25 + (i % 3) * 0.06,
                weight_kg=5.0 + i * 0.8,
                quantity_required=20 + (i % 7) * 10,
                raw_requirement="中间" if i > 5 else "最里面"
            ))

        solver = UniversalHierarchicalSolver()
        placements, metrics = solver.solve(cargo_list)

        self.assertTrue(metrics['is_valid'], f"Benchmark 03 validation failed: {metrics['violations_count']} violations")
        self.assertEqual(metrics['violations_count'], 0)
        print(f"[BENCHMARK 03 PASSED] 32-SKU Discrete: Placed {metrics['total_boxes']} boxes | Vol Util: {metrics['utilization_pct']:.2f}%")

    def test_benchmark_04_strict_zone_isolation(self):
        """Benchmark 04: Strict Zone sequence verification (INNER -> MIDDLE -> DOOR)."""
        cargo_list = [
            UniversalCargoTensor(sku_id="ZONE-IN-01", name="重型核心件", length=0.80, width=0.60, height=0.50, weight_kg=40.0, quantity_required=60, raw_requirement="最里面"),
            UniversalCargoTensor(sku_id="ZONE-MID-01", name="标准货品", length=0.50, width=0.40, height=0.30, weight_kg=12.0, quantity_required=200, raw_requirement="中间"),
            UniversalCargoTensor(sku_id="ZONE-DOOR-01", name="门端轻件", length=0.45, width=0.35, height=0.25, weight_kg=4.0, quantity_required=150, raw_requirement="封柜门")
        ]

        solver = UniversalHierarchicalSolver()
        placements, metrics = solver.solve(cargo_list)

        self.assertTrue(metrics['is_valid'])
        self.assertEqual(metrics['violations_count'], 0)
        
        # Verify X ordering
        inner_max_x = max(p['x'] + p['dx'] for p in placements if p['sku_id'] == "ZONE-IN-01")
        door_min_x = min(p['x'] for p in placements if p['sku_id'] == "ZONE-DOOR-01")
        self.assertLessEqual(inner_max_x, door_min_x + 0.5, "INNER cargo must be placed before DOOR cargo")
        print(f"[BENCHMARK 04 PASSED] Strict Zone Isolation: Inner Max X = {inner_max_x:.2f}m <= Door Min X = {door_min_x:.2f}m")

    def test_benchmark_05_multi_container_adaptability(self):
        """Benchmark 05: Multi-container types (20GP, 40GP, 40HQ, 45HQ, 53FT)."""
        containers = [
            ContainerDimensions("20GP", length=5.898, width=2.352, height=2.393, max_payload_kg=28000.0),
            ContainerDimensions("40GP", length=12.032, width=2.352, height=2.393, max_payload_kg=28000.0),
            ContainerDimensions("40HQ", length=12.024, width=2.350, height=2.690, max_payload_kg=26000.0),
            ContainerDimensions("45HQ", length=13.556, width=2.352, height=2.698, max_payload_kg=29000.0),
            ContainerDimensions("53FT", length=16.154, width=2.591, height=2.794, max_payload_kg=30000.0),
        ]

        for c_dim in containers:
            solver = UniversalHierarchicalSolver(container=c_dim)
            cargo_list = [
                UniversalCargoTensor(sku_id=f"SKU-{i}", name=f"货物{i}", length=0.50, width=0.40, height=0.35, weight_kg=15.0, quantity_required=150)
                for i in range(1, 6)
            ]
            placements, metrics = solver.solve(cargo_list)
            self.assertTrue(metrics['is_valid'], f"Container {c_dim.code} validation failed")
            self.assertEqual(metrics['violations_count'], 0)
            print(f"[BENCHMARK 05 PASSED] Container {c_dim.code:5s} ({c_dim.length:.1f}x{c_dim.width:.1f}x{c_dim.height:.1f}m): Placed {metrics['total_boxes']} boxes | Util: {metrics['utilization_pct']:.2f}%")

    def test_benchmark_06_monte_carlo_synthetic_stress_suite(self):
        """Benchmark 06: Automated Monte-Carlo parametric stress testing across 30 randomized scenarios."""
        from src.unified_pipeline.benchmark.SyntheticStressBenchmark import SyntheticCargoStressBenchmark
        
        benchmark = SyntheticCargoStressBenchmark()
        report = benchmark.run_stress_suite(num_scenarios=30, seed_start=500)

        # Assert zero-defect thresholds
        self.assertGreaterEqual(report['overall_pass_rate_pct'], 90.0, "Pass rate under randomized stress should be >= 90%")
        self.assertEqual(report['average_zone_compliance_pct'], 100.0, "Zone compliance across all scenarios must be 100%")
        self.assertLess(report['average_runtime_ms'], 100.0, "Average solving time should be < 100ms")
        
        print(f"[BENCHMARK 06 PASSED] Monte-Carlo 30-Scenario Suite: Pass Rate {report['overall_pass_rate_pct']}% | Avg Util: {report['average_volume_utilization_pct']:.2f}% | Avg Runtime: {report['average_runtime_ms']}ms | Total Time: {report['total_benchmark_time_sec']}s")


if __name__ == '__main__':
    unittest.main()

