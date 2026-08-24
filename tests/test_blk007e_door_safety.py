import dataclasses
import unittest

from backend.solver_v2.domain.models import (
    BoxDim, CargoSKU, ContainerSpec, PackingRole, QuantityPlan, ZoneType,
)
from run_blk003_benchmark import load_dataset
from src.constraints.door import (
    CargoRiskClassifier, DoorSafetyConfig, DoorSafetyEngine, DoorWallValidator,
    LONG_EDGE_FORWARD, SHORT_EDGE_FORWARD, TransportForceConfig,
)


DATASET = "devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"


def sku(sku_id="DISPLAY", box=BoxDim(.55, .08, .35), weight=8.0, quantity=100, door=True):
    return CargoSKU(
        sku_id=sku_id, name="Generic Cargo", box=box, weight_kg=weight,
        quantity=QuantityPlan(quantity, 0, is_elastic=True),
        packing_roles=((PackingRole.DOOR_SEAL,) if door else (PackingRole.MAIN_WALL,)),
        target_zone=(ZoneType.DOOR if door else ZoneType.MIDDLE),
    )


class TestBLK007EDoorSafety(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec("40HQ", BoxDim(12.032, 2.350, 2.690), 28600, door_zone_length_m=1.2)

    def test_door_001_display_door_wall(self):
        container, cargo = load_dataset(DATASET)
        plan = DoorSafetyEngine().plan(container, cargo)
        self.assertEqual(plan.status, "READY")
        self.assertIsNotNone(plan.wall)
        self.assertGreaterEqual(plan.wall.coverage, .75)
        self.assertTrue(plan.validation.valid)
        self.assertTrue(plan.validation.stable)
        self.assertEqual({p.orientation for p in plan.wall.placements}, {LONG_EDGE_FORWARD})
        self.assertTrue(plan.validation.transport["door_open_valid"])
        candidates = {sid for sid, risk in plan.classifications.items() if risk.door_candidate}
        self.assertEqual(candidates, {"SKU-02", "SKU-03", "SKU-04", "SKU-14"})

    def test_door_002_shallow_tall_column_is_rejected_when_door_opens(self):
        container,cargo=load_dataset(DATASET);plan=DoorSafetyEngine().plan(container,cargo)
        target=plan.wall.placements[0].column
        changed=tuple(dataclasses.replace(p,orientation=SHORT_EDGE_FORWARD,dx=.08)
                      if p.column==target else p for p in plan.wall.placements)
        bad_wall = dataclasses.replace(plan.wall, placements=changed)
        result = DoorWallValidator(.90,.20,.70,.95,.80,TransportForceConfig()).validate(bad_wall, plan.zone, container)
        self.assertFalse(result.valid)
        self.assertEqual(result.forbidden_orientation_count, 0)
        self.assertIn("DOOR_OPEN_UNRESTRAINED_TIPPING_RISK", result.issues)

    def test_door_003_wall_continuity(self):
        container,cargo=load_dataset(DATASET);plan=DoorSafetyEngine().plan(container,cargo)
        self.assertEqual(plan.wall.continuity.gap_count, 1)
        self.assertLessEqual(plan.wall.continuity.max_gap, .20)
        self.assertGreater(plan.wall.continuity.continuity_score, 90)

    def test_door_004_high_risk_cargo_forbidden(self):
        heavy = sku("HEAVY_TOWER", BoxDim(.3, .3, 1.8), weight=250.0)
        risk = CargoRiskClassifier().classify(heavy, self.container.Ly, self.container.Lz)
        self.assertFalse(risk.door_candidate)
        self.assertEqual(risk.rejection_reason, "HIGH_UNIT_WEIGHT_FOR_DOOR_ZONE")
        plan = DoorSafetyEngine().plan(self.container, [heavy])
        self.assertEqual(plan.status, "FAILED")

    def test_door_005_insufficient_door_wall_inventory(self):
        ordinary = sku("ORDINARY", door=False)
        plan = DoorSafetyEngine().plan(self.container, [ordinary])
        self.assertEqual(plan.status, "FAILED")
        self.assertEqual(plan.reason, "NO_VALID_DOOR_WALL")
        self.assertEqual(plan.constraints.reason, "NO_VALID_DOOR_WALL")

    def test_door_zone_is_configurable_and_dual_coordinate(self):
        plan = DoorSafetyEngine(DoorSafetyConfig(door_zone_depth=.8)).plan(self.container, [sku()])
        self.assertEqual(plan.zone.start_x, 0.0)
        self.assertEqual(plan.zone.end_x, .8)
        self.assertAlmostEqual(plan.zone.solver_start_x, self.container.Lx - .8)
        self.assertEqual(plan.zone.solver_end_x, self.container.Lx)

    def test_prepacking_layer_does_not_mutate_solver_input(self):
        cargo = (sku(),)
        prepared = DoorSafetyEngine().prepare_solver_input(self.container, cargo)
        self.assertIs(prepared.container, self.container)
        self.assertIs(prepared.cargo[0], cargo[0])
        self.assertTrue(prepared.door_constraints.reserved_zone.reserved)
        self.assertEqual(prepared.door_constraints.forced_orientation["DISPLAY"], LONG_EDGE_FORWARD)

    def test_classification_does_not_depend_on_sku_id_or_name(self):
        first = sku("SKU-02")
        second = dataclasses.replace(first, sku_id="UNRELATED-ID", name="No product-name hint")
        classifier = CargoRiskClassifier()
        a = classifier.classify(first, self.container.Ly, self.container.Lz)
        b = classifier.classify(second, self.container.Ly, self.container.Lz)
        self.assertEqual(
            (a.thin, a.door_candidate, a.risk_level, a.thin_ratio),
            (b.thin, b.door_candidate, b.risk_level, b.thin_ratio),
        )


if __name__ == "__main__":
    unittest.main()
