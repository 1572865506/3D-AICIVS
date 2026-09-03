"""
Unit test for OPT-04 Step 4.2: Partition Depth Ratio Parameterization (door_reserve_ratio).
Verifies that door_reserve_ratio controls door zone reservation and achieves >= 72% volume utilization in door-dense scenarios.
"""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoSKU,
    ContainerSpec,
    QuantityPlan,
    ZoneType,
    PackingRole,
)
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


class TestDoorReserveRatioParameterization(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.024, 2.350, 2.690),
            max_payload_kg=26000.0,
        )
        self.solver = UnifiedSolver(self.container)

    def test_door_dense_scenario_utilization(self):
        """
        Acceptance Criteria: Volume utilization >= 72% in door-dense scenario.
        Verifies door_reserve_ratio parameterized trials (0.15, 0.25) pack door-seal items cleanly.
        """
        # Middle items
        sku_mid_1 = CargoSKU(
            sku_id="SKU_MID_A",
            name="Middle Standard Carton",
            box=BoxDim(0.50, 0.40, 0.45),
            weight_kg=12.0,
            quantity=QuantityPlan(required=400),
            target_zone=ZoneType.MIDDLE,
        )
        sku_mid_2 = CargoSKU(
            sku_id="SKU_MID_B",
            name="Middle Filler Carton",
            box=BoxDim(0.35, 0.35, 0.30),
            weight_kg=8.0,
            quantity=QuantityPlan(required=300),
            target_zone=ZoneType.MIDDLE,
        )
        # Door-dense items (~15-20% container volume)
        sku_door_seal = CargoSKU(
            sku_id="SKU_DOOR_SEAL",
            name="Door Seal Plate Box",
            box=BoxDim(0.40, 0.55, 0.30),
            weight_kg=10.0,
            quantity=QuantityPlan(required=220),
            target_zone=ZoneType.DOOR,
            packing_roles=[PackingRole.DOOR_SEAL],
            source_requirement_text="放置于封门区域",
        )

        cargo_list = [sku_mid_1, sku_mid_2, sku_door_seal]

        # 1. Test individual door_reserve_ratio trials
        tensors = self.solver._convert_cargo_skus_to_tensors(cargo_list)

        strat_door_15 = {"name": "DOOR_COMPACT", "door_reserve_ratio": 0.15, "min_sec_vol": 0.35}
        placements_15, _ = self.solver._solve_single_trial(tensors, strat_door_15)
        val_15 = IndependentGlobalValidator.validate(
            container=self.container,
            placements=placements_15,
            cargo_list=cargo_list,
        )

        strat_door_25 = {"name": "DOOR_DEEP", "door_reserve_ratio": 0.25, "min_sec_vol": 0.35}
        placements_25, _ = self.solver._solve_single_trial(tensors, strat_door_25)
        val_25 = IndependentGlobalValidator.validate(
            container=self.container,
            placements=placements_25,
            cargo_list=cargo_list,
        )

        print(f"\n[DOOR_COMPACT 0.15] Util: {val_15.metrics.get('volume_utilization_pct', 0):.2f}%, Placed: {len(placements_15)}, Valid: {val_15.is_valid}")
        print(f"[DOOR_DEEP 0.25]    Util: {val_25.metrics.get('volume_utilization_pct', 0):.2f}%, Placed: {len(placements_25)}, Valid: {val_25.is_valid}")

        self.assertTrue(val_15.is_valid, f"Violations (15%): {val_15.violations}")
        self.assertTrue(val_25.is_valid, f"Violations (25%): {val_25.violations}")

        # 2. Test full solver.solve() on door dense scenario
        solution = self.solver.solve(cargo_list)

        print(f"[Solver Solution] Util: {solution.volume_utilization_pct:.2f}%, Placed: {solution.placed_count}, Status: {solution.status}")
        self.assertTrue(solution.validation_result.is_valid, f"Violations: {solution.validation_result.violations}")
        self.assertGreaterEqual(
            solution.volume_utilization_pct,
            72.0,
            f"Volume utilization {solution.volume_utilization_pct:.2f}% is less than required 72.0%"
        )

        # Verify door items are placed at the door zone
        door_placements = [p for p in solution.placements if p.sku_id == "SKU_DOOR_SEAL"]
        self.assertGreater(len(door_placements), 0, "Door seal items must be placed")
        min_door_x = min(p.position.x for p in door_placements)
        self.assertGreaterEqual(min_door_x, 8.0, f"Door items should be placed in rear/door zone >= 8.0m, got {min_door_x}")


if __name__ == "__main__":
    unittest.main()
