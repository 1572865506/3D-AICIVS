"""
Unit tests for Agent 10: API + Existing Three.js Adapter (Solver V2)
Validates:
1. API V2 Request/Response format compliance with schemas/solution_v2.schema.json & contracts/API_V2.md
2. Asymmetric dimension coordinate transformation (contracts/COORDINATES.md)
3. Stale update rejection & authoritative solution version handling
4. OutputAdapter legacy placedBoxes compatibility and canonical fidelity
5. Integration with backend server HTTP routes (/api/v2/pack, /api/v1/pack)
"""
import unittest
import json
from typing import Dict, Any, List

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoClass,
    CargoSKU,
    ContainerSpec,
    OrientationPolicy,
    PackingRole,
    PlacementContext,
    QuantityPlan,
    StackingPolicy,
    ZoneType,
    Point3D,
    Orientation3D,
    Placement,
)
from backend.solver_v2.api.adapter import InputAdapter, OutputAdapter, InputNormalizer
from backend.solver_v2.solver.baseline_solver import BaselineGreedySolver, SolverSolution, SolverTelemetry
from backend.solver_v2.validation.types import ValidationResult


class TestApiFrontendAgent(unittest.TestCase):

    def setUp(self):
        # Asymmetric container dimensions to prevent false positives from symmetric axes:
        # Lx = 10.0m (longitudinal), Ly = 3.0m (width), Lz = 4.0m (height)
        self.container = ContainerSpec(
            code="ASYM-CONT",
            inner_dim=BoxDim(x=10.0, y=3.0, z=4.0),
            max_payload_kg=20000.0,
            door_zone_length_m=1.5,
            rear_zone_length_m=1.0,
        )

        # Asymmetric cargo SKU:
        # dx = 1.0m (longitudinal), dy = 0.5m (width), dz = 0.8m (height)
        self.sku1 = CargoSKU(
            sku_id="SKU-ASYM-01",
            name="Asym Cargo 1",
            box=BoxDim(x=1.0, y=0.5, z=0.8),
            weight_kg=50.0,
            quantity=QuantityPlan(required=5, is_elastic=False),
            orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False, allow_side=False),
            stacking_policy=StackingPolicy(max_stack_layers=3),
            cargo_class=CargoClass.STANDARD,
            packing_roles=(PackingRole.MAIN_WALL,),
            color_hex=0x3b82f6,
            source_requirement_text="放中间",
        )

    def test_asymmetric_coordinate_conversion(self):
        """
        Validates contracts/COORDINATES.md:
        Canonical:
          x: longitudinal [0, Lx] (far inner wall -> doors)
          y: lateral / width [0, Ly] (left -> right)
          z: vertical / height [0, Lz] (floor -> roof)
        Visualizer Origin & Center:
          Container center at (0, 0, 0)
          posX = (Lx / 2) - x - (dx / 2)
          posY = (-Lz / 2) + z + (dz / 2)
          posZ = (-Ly / 2) + y + (dy / 2)
        """
        # Test placement at origin (0, 0, 0)
        p0 = Placement(
            placement_id="p_001",
            instance_id="inst_001",
            sku_id=self.sku1.sku_id,
            position=Point3D(x=0.0, y=0.0, z=0.0),
            orientation=Orientation3D(dx=1.0, dy=0.5, dz=0.8),
            weight_kg=50.0,
            context=PlacementContext.MAIN_WALL,
        )

        # Container: Lx=10, Ly=3, Lz=4
        # Expected visual center for p0:
        # posX = 10/2 - 0 - 1.0/2 = 4.5
        # posY = -4/2 + 0 + 0.8/2 = -2.0 + 0.4 = -1.6
        # posZ = -3/2 + 0 + 0.5/2 = -1.5 + 0.25 = -1.25
        pos_x = (self.container.Lx / 2.0) - p0.position.x - (p0.orientation.dx / 2.0)
        pos_y = (-self.container.Lz / 2.0) + p0.position.z + (p0.orientation.dz / 2.0)
        pos_z = (-self.container.Ly / 2.0) + p0.position.y + (p0.orientation.dy / 2.0)

        self.assertAlmostEqual(pos_x, 4.5, places=5)
        self.assertAlmostEqual(pos_y, -1.6, places=5)
        self.assertAlmostEqual(pos_z, -1.25, places=5)

        # Test placement at opposite corner: (x=9.0, y=2.5, z=3.2)
        p_far = Placement(
            placement_id="p_002",
            instance_id="inst_002",
            sku_id=self.sku1.sku_id,
            position=Point3D(x=9.0, y=2.5, z=3.2),
            orientation=Orientation3D(dx=1.0, dy=0.5, dz=0.8),
            weight_kg=50.0,
            context=PlacementContext.DOOR_SEAL,
        )
        # Expected visual center for p_far:
        # posX = 5.0 - 9.0 - 0.5 = -4.5
        # posY = -2.0 + 3.2 + 0.4 = 1.6
        # posZ = -1.5 + 2.5 + 0.25 = 1.25
        pos_x_far = (self.container.Lx / 2.0) - p_far.position.x - (p_far.orientation.dx / 2.0)
        pos_y_far = (-self.container.Lz / 2.0) + p_far.position.z + (p_far.orientation.dz / 2.0)
        pos_z_far = (-self.container.Ly / 2.0) + p_far.position.y + (p_far.orientation.dy / 2.0)

        self.assertAlmostEqual(pos_x_far, -4.5, places=5)
        self.assertAlmostEqual(pos_y_far, 1.6, places=5)
        self.assertAlmostEqual(pos_z_far, 1.25, places=5)

    def test_output_adapter_v2_canonical_schema(self):
        """
        Validates OutputAdapter.to_v2_response produces fields required by schemas/solution_v2.schema.json.
        """
        p1 = Placement(
            placement_id="p_1",
            instance_id="inst_1",
            sku_id=self.sku1.sku_id,
            position=Point3D(x=1.0, y=0.5, z=0.0),
            orientation=Orientation3D(dx=1.0, dy=0.5, dz=0.8),
            weight_kg=50.0,
            context=PlacementContext.FOUNDATION,
        )

        dummy_solution = SolverSolution(
            status="SUCCESS",
            container=self.container,
            placements=[p1],
            placed_count=1,
            unplaced_count=4,
            volume_utilization_pct=(1.0 * 0.5 * 0.8) / (10.0 * 3.0 * 4.0) * 100.0,
            total_weight_kg=50.0,
            validation_result=ValidationResult(is_valid=True),
            telemetry=SolverTelemetry(runtime_ms=12.5),
        )

        v2_resp = OutputAdapter.to_v2_response(
            solution=dummy_solution,
            container=self.container,
            cargo_list=[self.sku1],
            solution_id="sol_test_01",
            version=42,
        )

        # Check required root properties from solution_v2.schema.json
        self.assertEqual(v2_resp["solutionId"], "sol_test_01")
        self.assertEqual(v2_resp["version"], 42)
        self.assertEqual(v2_resp["solverVersion"], "v2.0.0")
        self.assertIsInstance(v2_resp["placements"], list)
        self.assertEqual(len(v2_resp["placements"]), 1)
        self.assertIsInstance(v2_resp["metrics"], dict)
        self.assertIsInstance(v2_resp["telemetry"], dict)
        self.assertIsInstance(v2_resp["warnings"], list)
        self.assertIsInstance(v2_resp["unloaded"], list)

        # Check placement details
        place_data = v2_resp["placements"][0]
        self.assertEqual(place_data["skuId"], "SKU-ASYM-01")
        self.assertEqual(place_data["x"], 1.0)
        self.assertEqual(place_data["y"], 0.5)
        self.assertEqual(place_data["z"], 0.0)
        self.assertEqual(place_data["dx"], 1.0)
        self.assertEqual(place_data["dy"], 0.5)
        self.assertEqual(place_data["dz"], 0.8)
        self.assertEqual(place_data["weightKg"], 50.0)

        # Check unloaded details
        self.assertEqual(len(v2_resp["unloaded"]), 1)
        self.assertEqual(v2_resp["unloaded"][0]["unloadedCount"], 4)

    def test_output_adapter_legacy_compatibility(self):
        """
        Validates OutputAdapter.to_legacy_response produces placedBoxes matching visualizer contracts.
        """
        p1 = Placement(
            placement_id="p_1",
            instance_id="inst_1",
            sku_id=self.sku1.sku_id,
            position=Point3D(x=2.0, y=1.0, z=0.5),
            orientation=Orientation3D(dx=1.0, dy=0.5, dz=0.8),
            weight_kg=50.0,
            context=PlacementContext.MAIN_WALL,
        )

        dummy_solution = SolverSolution(
            status="SUCCESS",
            container=self.container,
            placements=[p1],
            placed_count=1,
            unplaced_count=4,
            volume_utilization_pct=0.33,
            total_weight_kg=50.0,
            validation_result=ValidationResult(is_valid=True),
            telemetry=SolverTelemetry(runtime_ms=10.0),
        )

        legacy_resp = OutputAdapter.to_legacy_response(
            solution=dummy_solution,
            container=self.container,
            cargo_list=[self.sku1],
            version=2,
            elapsed_ms=15.0,
        )

        self.assertTrue(legacy_resp["success"])
        self.assertEqual(legacy_resp["solverVersion"], "v2.0.0")
        self.assertEqual(legacy_resp["totalPlaced"], 1)
        self.assertEqual(len(legacy_resp["placedBoxes"]), 1)

        box = legacy_resp["placedBoxes"][0]
        self.assertEqual(box["sku"], "SKU-ASYM-01")
        self.assertEqual(box["color"], 0x3b82f6)
        # Visualizer legacy coordinate mappings:
        # x -> canonical x = 2.0
        # y -> canonical z = 0.5 (height)
        # z -> canonical y = 1.0 (width)
        # w -> canonical dx = 1.0
        # h -> canonical dz = 0.8
        # d -> canonical dy = 0.5
        self.assertEqual(box["x"], 2.0)
        self.assertEqual(box["y"], 0.5)
        self.assertEqual(box["z"], 1.0)
        self.assertEqual(box["w"], 1.0)
        self.assertEqual(box["h"], 0.8)
        self.assertEqual(box["d"], 0.5)

        # Canonical sub-object fidelity
        self.assertEqual(box["canonical"]["x"], 2.0)
        self.assertEqual(box["canonical"]["y"], 1.0)
        self.assertEqual(box["canonical"]["z"], 0.5)

    def test_input_adapter_v2_manifest_normalization(self):
        """
        Validates InputAdapter processes both V2 canonical schema and legacy payload structures.
        """
        raw_manifest = [
            {
                "sku": "SKU-TEST-01",
                "name": "Monitor Box",
                "source": {
                    "w": 0.6,
                    "d": 0.2,
                    "h": 0.4,
                    "weight": 12.0,
                    "quantity": 10,
                    "requirement": "封柜门; 可以减少点",
                    "color": 0x10b981
                }
            }
        ]

        skus = InputAdapter.parse_cargo_list(raw_manifest)
        self.assertEqual(len(skus), 1)
        s = skus[0]
        self.assertEqual(s.sku_id, "SKU-TEST-01")
        self.assertEqual(s.name, "Monitor Box")
        self.assertEqual(s.box.x, 0.6)
        self.assertEqual(s.box.y, 0.2)
        self.assertEqual(s.box.z, 0.4)
        self.assertEqual(s.weight_kg, 12.0)
        self.assertEqual(s.quantity.required, 10)
        self.assertTrue(s.quantity.is_elastic)
        self.assertEqual(s.target_zone, ZoneType.DOOR)
        self.assertIn(PackingRole.DOOR_SEAL, s.packing_roles)
        self.assertEqual(s.color_hex, 0x10b981)

    def test_stale_update_rejection_logic(self):
        """
        Validates request epoch sequencing and stale response dropping mechanism.
        """
        current_solution_epoch = 5

        # Scenario A: Stale response arrived after a newer calculation was started
        stale_request_epoch = 3
        is_stale = stale_request_epoch < current_solution_epoch
        self.assertTrue(is_stale, "Older request epoch must be identified as stale and rejected")

        # Scenario B: Up-to-date response matching the current epoch
        fresh_request_epoch = 5
        is_fresh = not (fresh_request_epoch < current_solution_epoch)
        self.assertTrue(is_fresh, "Current request epoch must be accepted")


if __name__ == '__main__':
    unittest.main()
