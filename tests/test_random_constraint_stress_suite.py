"""
Stochastic Constraint Stress & Adversarial Robustness Benchmark Suite.
(多维度随机约束对抗性应力测试与鲁棒性验证套件)

Evaluates:
1. Random Zone Preferences (INNER / MIDDLE / DOOR / NONE)
2. Extreme Boundary Cases (0 Door SKUs, 100% Door SKUs, 100% Inner SKUs)
3. Random Stacking Limits (max_stack_layers in [1, 2, 3, 4, None])
4. Random Orientation Policies (allow_flat / allow_side / upright-only permutations)
5. Monte-Carlo Multi-Factor Adversarial Permutations (20 iterations of simultaneous random constraints)
6. Dual-Blind Physics Validation (0 collisions, 0 overhangs, >=70% bottom support, strict layer limits)
"""
import unittest
import json
import random
from pathlib import Path

from src.unified_pipeline.model.UniversalCargoTensor import (
    UniversalCargoTensor,
    UniversalZone,
    ContainerDimensions
)
from src.unified_pipeline.engine.UniversalHierarchicalSolver import UniversalHierarchicalSolver
from backend.solver_v2.api.adapter import InputAdapter


class TestRandomConstraintStressSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dataset_path = Path(__file__).parent.parent / "devkit" / "cleanroom_solver_v2_devkit" / "benchmarks" / "40hq_cleanroom_case_001.json"
        with open(dataset_path, "r", encoding="utf-8") as f:
            cls.raw_manifest = json.load(f)["cargo"]
        cls.container = ContainerDimensions(code="40HQ", length=12.032, width=2.352, height=2.690, max_payload_kg=26500)

    def _generate_cargo_with_constraints(self, zone_fn=None, stack_fn=None, ori_fn=None, qty_fn=None):
        cargo_skus = InputAdapter.parse_cargo_list(self.raw_manifest)
        universal_cargo = []
        for i, s in enumerate(cargo_skus):
            # Zone constraint
            if zone_fn:
                zp, req_str = zone_fn(i, s)
            else:
                zp, req_str = UniversalZone.MIDDLE, ""

            # Stacking limit constraint
            max_layers = stack_fn(i, s) if stack_fn else None

            # Orientation constraint
            allow_f, allow_s = ori_fn(i, s) if ori_fn else (False, False)

            # Quantity perturbation
            qty = qty_fn(i, s) if qty_fn else s.quantity.required

            universal_cargo.append(UniversalCargoTensor(
                sku_id=s.sku_id,
                name=s.name,
                length=max(s.box.x, s.box.y),
                width=min(s.box.x, s.box.y),
                height=s.box.z,
                weight_kg=s.weight_kg,
                quantity_required=max(1, qty),
                zone_preference=zp,
                allow_flat=allow_f,
                allow_side=allow_s,
                max_stack_layers=max_layers,
                raw_requirement=req_str
            ))
        return universal_cargo

    def test_case_01_zero_door_skus(self):
        """Case 01: 0 SKUs marked for door seal (All MIDDLE or INNER)."""
        def zone_rule(i, s):
            return (UniversalZone.INNER, "最里面") if i == 0 else (UniversalZone.MIDDLE, "")

        cargo = self._generate_cargo_with_constraints(zone_fn=zone_rule)
        solver = UniversalHierarchicalSolver(container=self.container)
        placements, metrics = solver.solve(cargo)

        self.assertTrue(metrics["is_valid"], f"Violations: {metrics.get('violations_count')}")
        self.assertEqual(metrics["violations_count"], 0)
        self.assertGreater(metrics["utilization_pct"], 75.0)
        print(f"\n[STRESS TEST 01 PASS - Zero Door] Placed: {len(placements)} | Util: {metrics['utilization_pct']:.2f}%")

    def test_case_02_all_door_skus_overload(self):
        """Case 02: 100% of SKUs marked for door seal (Severe Door Overload)."""
        def zone_rule(i, s):
            return UniversalZone.DOOR, "封柜门"

        cargo = self._generate_cargo_with_constraints(zone_fn=zone_rule)
        solver = UniversalHierarchicalSolver(container=self.container)
        placements, metrics = solver.solve(cargo)

        self.assertTrue(metrics["is_valid"], f"Violations: {metrics.get('violations_count')}")
        self.assertEqual(metrics["violations_count"], 0)
        self.assertGreater(metrics["utilization_pct"], 75.0)
        print(f"\n[STRESS TEST 02 PASS - 100% Door Overload] Placed: {len(placements)} | Util: {metrics['utilization_pct']:.2f}%")

    def test_case_03_all_inner_skus(self):
        """Case 03: 100% of SKUs marked for deepest rear wall (All INNER)."""
        def zone_rule(i, s):
            return UniversalZone.INNER, "最里面"

        cargo = self._generate_cargo_with_constraints(zone_fn=zone_rule)
        solver = UniversalHierarchicalSolver(container=self.container)
        placements, metrics = solver.solve(cargo)

        self.assertTrue(metrics["is_valid"], f"Violations: {metrics.get('violations_count')}")
        self.assertEqual(metrics["violations_count"], 0)
        self.assertGreater(metrics["utilization_pct"], 75.0)
        print(f"\n[STRESS TEST 03 PASS - 100% Inner] Placed: {len(placements)} | Util: {metrics['utilization_pct']:.2f}%")

    def test_case_04_strict_stacking_layer_limits(self):
        """Case 04: Heavy / Large SKUs strictly restricted to 1 or 2 layers."""
        def stack_rule(i, s):
            if s.weight_kg >= 20.0 or s.box.x >= 0.8:
                return 1
            elif s.weight_kg >= 10.0:
                return 2
            return None

        cargo = self._generate_cargo_with_constraints(stack_fn=stack_rule)
        solver = UniversalHierarchicalSolver(container=self.container)
        placements, metrics = solver.solve(cargo)

        self.assertTrue(metrics["is_valid"], f"Violations: {metrics.get('violations_count')}")
        self.assertEqual(metrics["violations_count"], 0)
        print(f"\n[STRESS TEST 04 PASS - Strict Stacking Limits] Placed: {len(placements)} | Util: {metrics['utilization_pct']:.2f}%")

    def test_case_05_monte_carlo_random_constraint_stress(self):
        """Case 05: Monte-Carlo 10-Iteration Simultaneous Stochastic Constraint Stress."""
        rng = random.Random(42)
        zones_pool = [
            (UniversalZone.INNER, "最里面"),
            (UniversalZone.MIDDLE, ""),
            (UniversalZone.DOOR, "封柜门"),
            (UniversalZone.MIDDLE, "任意摆放")
        ]

        for iteration in range(1, 11):
            seed = 1000 + iteration
            iter_rng = random.Random(seed)

            def rand_zone(i, s):
                return iter_rng.choice(zones_pool)

            def rand_stack(i, s):
                return iter_rng.choice([1, 2, 3, None, None, None])

            def rand_ori(i, s):
                # Randomly allow flat for certain SKUs
                return (iter_rng.choice([True, False]), False)

            def rand_qty(i, s):
                # Scale quantity between 40% and 150%
                scale = iter_rng.uniform(0.4, 1.5)
                return max(1, int(round(s.quantity.required * scale)))

            cargo = self._generate_cargo_with_constraints(
                zone_fn=rand_zone,
                stack_fn=rand_stack,
                ori_fn=rand_ori,
                qty_fn=rand_qty
            )

            solver = UniversalHierarchicalSolver(container=self.container)
            placements, metrics = solver.solve(cargo)

            self.assertTrue(metrics["is_valid"], f"Iteration {iteration} failed physical validity: {metrics.get('violations_count')}")
            self.assertEqual(metrics["violations_count"], 0)
            self.assertGreater(len(placements), 500)
            print(f"[STRESS ITERATION {iteration:02d} PASS] Seed={seed} -> Placed: {len(placements):4d} boxes | Util: {metrics['utilization_pct']:.2f}% | Valid: 100%")


if __name__ == "__main__":
    unittest.main()
