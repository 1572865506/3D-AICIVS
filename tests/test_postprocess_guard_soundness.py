import unittest
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.domain.models import (
    ContainerSpec, BoxDim, CargoSKU, StackingPolicy, QuantityPlan, Placement, Point3D, Orientation3D, PlacementContext
)
from backend.solver_v2.solver.compaction import CompactionPass
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


class TestPostprocessGuardSoundness(unittest.TestCase):
    """
    Test suite for post-processing operators (CompactionPass).
    Ensures that compaction moves NEVER bypass topology support, bearing limits,
    or stacking rules, and that all post-processed configurations remain 100% valid.
    """

    def setUp(self):
        self.container = ContainerSpec(
            code="TestContainer",
            inner_dim=BoxDim(x=5.0, y=2.0, z=2.0),
            max_payload_kg=10000.0
        )
        self.compactor = CompactionPass(container=self.container)

    def test_compaction_rejects_bearing_overload(self):
        """
        Moving a heavy box on top of a low-bearing base must be strictly rejected.
        """
        sku_heavy_base = CargoSKU(
            sku_id="SKU_BASE",
            name="Fragile Base",
            box=BoxDim(1.0, 1.0, 0.5),
            weight_kg=10.0,
            quantity=QuantityPlan(required=1),
            stacking_policy=StackingPolicy(max_bearing_kg=30.0) # only 30kg bearing!
        )
        sku_top = CargoSKU(
            sku_id="SKU_TOP",
            name="Overweight Top",
            box=BoxDim(1.0, 1.0, 0.5),
            weight_kg=80.0, # 80kg > 30kg!
            quantity=QuantityPlan(required=1)
        )
        catalog = [sku_heavy_base, sku_top]

        # Base at (0, 0, 0)
        p_base = Placement(
            placement_id="plc_base",
            instance_id="inst_base",
            sku_id="SKU_BASE",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(1.0, 1.0, 0.5),
            weight_kg=10.0,
            context=PlacementContext.MAIN_WALL
        )
        # Top box initially at (0.0, 0.0, 0.8) in air or separated
        p_top = Placement(
            placement_id="plc_top",
            instance_id="inst_top",
            sku_id="SKU_TOP",
            position=Point3D(2.0, 0.0, 0.0),
            orientation=Orientation3D(1.0, 1.0, 0.5),
            weight_kg=80.0,
            context=PlacementContext.MAIN_WALL
        )

        res = self.compactor.compact([p_base, p_top], cargo_catalog=catalog)
        val = IndependentGlobalValidator.validate(self.container, res.placements, catalog)
        self.assertTrue(val.is_valid, f"Compaction must preserve 0 violations: {val.violations}")

    def test_compaction_rejects_hollow_bridge_diagonal_support(self):
        """
        Compacting into a hollow-span or diagonal two-point contact must be rejected.
        """
        sku_pill = CargoSKU(
            sku_id="SKU_PILL",
            name="Pillar",
            box=BoxDim(0.2, 0.2, 0.5),
            weight_kg=10.0,
            quantity=QuantityPlan(required=2)
        )
        sku_span = CargoSKU(
            sku_id="SKU_SPAN",
            name="Span Carton",
            box=BoxDim(1.0, 0.4, 0.5),
            weight_kg=20.0,
            quantity=QuantityPlan(required=1)
        )
        catalog = [sku_pill, sku_span]

        # Two pillars at diagonal corners leaving a hollow span > 10cm
        p1 = Placement("p1", "i1", "SKU_PILL", Point3D(0.0, 0.0, 0.0), Orientation3D(0.2, 0.2, 0.5), 10.0, PlacementContext.MAIN_WALL)
        p2 = Placement("p2", "i2", "SKU_PILL", Point3D(0.8, 0.2, 0.0), Orientation3D(0.2, 0.2, 0.5), 10.0, PlacementContext.MAIN_WALL)
        
        # Span carton initially on floor
        p_span = Placement("p_span", "is", "SKU_SPAN", Point3D(2.0, 0.0, 0.0), Orientation3D(1.0, 0.4, 0.5), 20.0, PlacementContext.MAIN_WALL)

        res = self.compactor.compact([p1, p2, p_span], cargo_catalog=catalog)
        val = IndependentGlobalValidator.validate(self.container, res.placements, catalog)
        self.assertTrue(val.is_valid, f"Compaction must not create bridge/unsupported violation: {val.violations}")


if __name__ == "__main__":
    unittest.main()
