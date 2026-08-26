import unittest
from backend.solver_v2.domain.models import BoxDim, ContainerSpec, Orientation3D, Placement, PlacementContext, Point3D
from src.constraints.transport import BrakingStabilityValidator


class TestBrakingStabilityValidator(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec("40HQ", BoxDim(12.032, 2.350, 2.690), 28600)
        self.validator = BrakingStabilityValidator(braking_acceleration_g=0.80)

    def test_empty_placements_is_safe(self):
        report = self.validator.validate(self.container, ())
        self.assertTrue(report.overall_safe)
        self.assertEqual(report.evaluated_columns_count, 0)

    def test_front_bulkhead_supported_tall_stack_is_safe(self):
        # A tall stack right at the front bulkhead (x=0) is directly supported by the container front wall
        placements = (
            Placement("p1", "p1", "SKU-TALL", Point3D(0.0, 0.0, 0.0), Orientation3D(0.3, 0.3, 1.0, "UPRIGHT"), 20.0, PlacementContext.MAIN_WALL),
            Placement("p2", "p2", "SKU-TALL", Point3D(0.0, 0.0, 1.0), Orientation3D(0.3, 0.3, 1.0, "UPRIGHT"), 20.0, PlacementContext.MAIN_WALL),
        )
        report = self.validator.validate(self.container, placements)
        self.assertTrue(report.overall_safe)
        self.assertTrue(report.columns[0].front_supported)
        self.assertEqual(report.columns[0].risk_level, "SAFE")

    def test_freestanding_tall_unsupported_stack_triggers_braking_tipping_risk(self):
        # A tall slender stack in the middle (x=5.0m) with no front support and H=2.0m, D=0.3m (H/D=6.67 > 1.25)
        placements = (
            Placement("p1", "p1", "SKU-SLENDER", Point3D(5.0, 0.0, 0.0), Orientation3D(0.3, 0.3, 1.0, "UPRIGHT"), 20.0, PlacementContext.MAIN_WALL),
            Placement("p2", "p2", "SKU-SLENDER", Point3D(5.0, 0.0, 1.0), Orientation3D(0.3, 0.3, 1.0, "UPRIGHT"), 20.0, PlacementContext.MAIN_WALL),
        )
        report = self.validator.validate(self.container, placements)
        self.assertFalse(report.overall_safe)
        self.assertEqual(report.at_risk_columns_count, 1)
        self.assertFalse(report.columns[0].front_supported)
        self.assertEqual(report.columns[0].risk_level, "HIGH_RISK")
        self.assertIn("急刹车可能向前倾倒", report.warnings[0])

    def test_adjacent_front_supporting_cargo_wall_prevents_tipping(self):
        # Front wall at x=0..0.5m, rear stack at x=0.5m..0.8m
        front_p = Placement("p_front", "p_front", "SKU-BASE", Point3D(0.0, 0.0, 0.0), Orientation3D(0.5, 0.5, 2.0, "UPRIGHT"), 50.0, PlacementContext.MAIN_WALL)
        rear_p = Placement("p_rear", "p_rear", "SKU-TALL", Point3D(0.5, 0.0, 0.0), Orientation3D(0.3, 0.5, 2.0, "UPRIGHT"), 30.0, PlacementContext.MAIN_WALL)
        report = self.validator.validate(self.container, (front_p, rear_p))
        self.assertTrue(report.overall_safe)
        self.assertEqual(report.at_risk_columns_count, 0)
        self.assertTrue(report.columns[0].front_supported)
        self.assertTrue(report.columns[1].front_supported)

    def test_small_manifest_with_door_sku_packs_continuously_at_front(self):
        from backend.solver_v2.domain.models import CargoSKU, PackingRole, QuantityPlan, ZoneType
        from backend.solver_v2.solver.baseline_solver import BaselineGreedySolver
        from src.solver.integration.door import DoorIntegratedSolver

        # 30 boxes marked DOOR_SEAL, taking only ~1.5m of length
        cargo = [
            CargoSKU("SKU-DOOR", "Door Cargo", BoxDim(0.5, 0.4, 0.3), 10.0,
                     QuantityPlan(30, 0, is_elastic=True),
                     packing_roles=(PackingRole.DOOR_SEAL,), target_zone=ZoneType.DOOR)
        ]
        solver = DoorIntegratedSolver(BaselineGreedySolver())
        solution = solver.solve(self.container, cargo)
        self.assertEqual(len(solution.placements), 30)
        max_x = max(p.max_x for p in solution.placements)
        # All 30 boxes must be packed compactly near the front (max_x < 3.0m) and NOT at the door (x > 11m)
        self.assertLess(max_x, 3.0)
        self.assertTrue(solver.last_braking_report.overall_safe)


if __name__ == "__main__":
    unittest.main()
