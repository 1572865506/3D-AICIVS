"""
Unit test for OPT-04: Multi-Strategy Trial Expansion (Step 4.1).
Verifies that 8+ strategy configurations are evaluated and at least 2 new strategies
outperform all original/legacy strategies (BALANCED_WALL, DENSITY_FIRST, MODULAR_SLAB).
"""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoSKU,
    ContainerSpec,
    QuantityPlan,
)
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


class TestMultiStrategyTrialExpansion(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.024, 2.350, 2.690),
            max_payload_kg=26000.0,
        )
        self.solver = UnifiedSolver(self.container)

    def _eval_strategy(self, cargo_list, strategy_cfg):
        tensors = self.solver._convert_cargo_skus_to_tensors(cargo_list)
        placements, _ = self.solver._solve_single_trial(tensors, strategy_cfg)
        val = IndependentGlobalValidator.validate(
            container=self.container,
            placements=placements,
            cargo_list=cargo_list,
        )
        util = val.metrics.get("volume_utilization_pct", 0.0)
        placed_vol = val.metrics.get("cargo_volume", 0.0)
        return {
            "name": strategy_cfg["name"],
            "is_valid": val.is_valid,
            "utilization": util,
            "placed_vol": placed_vol,
            "placed_count": len(placements),
        }

    def test_new_strategies_outperform_legacy_strategies(self):
        """
        Acceptance Criteria: At least 2 new strategies outperform all 3 legacy strategies
        (BALANCED_WALL, DENSITY_FIRST, MODULAR_SLAB) on specific test cases.
        """
        legacy_strategies = [
            {"name": "BALANCED_WALL", "volume_weight": 0.6, "density_weight": 0.4, "min_sec_vol": 0.40},
            {"name": "DENSITY_FIRST", "volume_weight": 0.3, "density_weight": 0.7, "min_sec_vol": 0.30},
            {"name": "MODULAR_SLAB",  "volume_weight": 0.8, "density_weight": 0.2, "min_sec_vol": 0.50},
        ]

        # --- Case A: Dense High-Qty Packaging ---
        cargo_case_a = [
            CargoSKU(
                sku_id="SKU_A",
                name="Box A",
                box=BoxDim(0.58, 0.38, 0.42),
                weight_kg=15.0,
                quantity=QuantityPlan(required=600),
            ),
            CargoSKU(
                sku_id="SKU_B",
                name="Box B",
                box=BoxDim(0.40, 0.55, 0.35),
                weight_kg=12.0,
                quantity=QuantityPlan(required=400),
            ),
            CargoSKU(
                sku_id="SKU_C",
                name="Box C",
                box=BoxDim(0.32, 0.28, 0.22),
                weight_kg=4.0,
                quantity=QuantityPlan(required=600),
            ),
        ]

        legacy_results_a = [self._eval_strategy(cargo_case_a, s) for s in legacy_strategies]
        max_legacy_util_a = max(r["utilization"] for r in legacy_results_a if r["is_valid"])

        wide_wall_strat = {"name": "WIDE_WALL", "max_rows": 8, "min_sec_vol": 0.50}
        res_wide_wall = self._eval_strategy(cargo_case_a, wide_wall_strat)

        qty_first_strat = {"name": "QTY_FIRST", "sort": "quantity_desc", "min_sec_vol": 0.40}
        res_qty_first = self._eval_strategy(cargo_case_a, qty_first_strat)

        print(f"\n[Case A Results] Max Legacy Util: {max_legacy_util_a:.2f}%")
        print(f"  WIDE_WALL:  {res_wide_wall['utilization']:.2f}% (Valid: {res_wide_wall['is_valid']})")
        print(f"  QTY_FIRST:  {res_qty_first['utilization']:.2f}% (Valid: {res_qty_first['is_valid']})")

        # --- Case B: Mixed Long & Flat Profiles ---
        cargo_case_b = [
            CargoSKU(
                sku_id="SKU_LONG",
                name="Long Box",
                box=BoxDim(1.40, 0.40, 0.40),
                weight_kg=25.0,
                quantity=QuantityPlan(required=150),
            ),
            CargoSKU(
                sku_id="SKU_FLAT",
                name="Flat Box",
                box=BoxDim(0.60, 0.60, 0.25),
                weight_kg=10.0,
                quantity=QuantityPlan(required=400),
            ),
            CargoSKU(
                sku_id="SKU_CUBE",
                name="Cube Box",
                box=BoxDim(0.45, 0.45, 0.45),
                weight_kg=15.0,
                quantity=QuantityPlan(required=300),
            ),
        ]

        legacy_results_b = [self._eval_strategy(cargo_case_b, s) for s in legacy_strategies]
        max_legacy_util_b = max(r["utilization"] for r in legacy_results_b if r["is_valid"])

        small_fill_strat = {"name": "SMALL_FILL", "sort": "volume_asc", "min_sec_vol": 0.25}
        res_small_fill = self._eval_strategy(cargo_case_b, small_fill_strat)

        print(f"\n[Case B Results] Max Legacy Util: {max_legacy_util_b:.2f}%")
        print(f"  SMALL_FILL: {res_small_fill['utilization']:.2f}% (Valid: {res_small_fill['is_valid']})")

        # Count wins
        winning_strategies = []
        if res_wide_wall["is_valid"] and res_wide_wall["utilization"] > max_legacy_util_a:
            winning_strategies.append(f"WIDE_WALL (+{res_wide_wall['utilization'] - max_legacy_util_a:.2f}%)")
        if res_qty_first["is_valid"] and res_qty_first["utilization"] > max_legacy_util_a:
            winning_strategies.append(f"QTY_FIRST (+{res_qty_first['utilization'] - max_legacy_util_a:.2f}%)")
        if res_small_fill["is_valid"] and res_small_fill["utilization"] > max_legacy_util_b:
            winning_strategies.append(f"SMALL_FILL (+{res_small_fill['utilization'] - max_legacy_util_b:.2f}%)")

        print(f"\n[Winning New Strategies vs Legacy]: {winning_strategies}")
        self.assertGreaterEqual(
            len(winning_strategies), 2,
            f"Expected at least 2 new strategies to outperform legacy strategies, got {len(winning_strategies)}"
        )

    def test_unified_solver_end_to_end_multi_trial(self):
        """
        Verify end-to-end solve() runs all 8 trials smoothly and returns valid high-utilization solution.
        """
        cargo_list = [
            CargoSKU(
                sku_id="SKU_A",
                name="Box A",
                box=BoxDim(0.40, 0.60, 0.50),
                weight_kg=15.0,
                quantity=QuantityPlan(required=350),
            ),
            CargoSKU(
                sku_id="SKU_B",
                name="Box B",
                box=BoxDim(0.40, 0.45, 0.60),
                weight_kg=12.0,
                quantity=QuantityPlan(required=300),
            ),
        ]
        solution = self.solver.solve(cargo_list)
        self.assertTrue(solution.validation_result.is_valid)
        self.assertGreaterEqual(solution.volume_utilization_pct, 80.0)
        self.assertGreater(solution.placed_count, 0)
        print(f"\n[End-to-End Solve] Placed: {solution.placed_count}, Util: {solution.volume_utilization_pct:.2f}%, Status: {solution.status}")


if __name__ == "__main__":
    unittest.main()
