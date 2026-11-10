"""
Unit tests for OPT-05 Step 5.3: ElasticRecoveryScanner (Elastic Reduction Recovery Scan).
Verifies:
1. Scanning residual cavity spaces after optimization to recover unplaced elastic SKUs.
2. Dense gap packing into FreeSpaceEngine maximal empty spaces.
3. Strict feasibility verification via IndependentGlobalValidator (bounds, collision, support).
4. Acceptance criteria: Elastic item utilization increases by >= 1.0%.
"""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoSKU,
    ContainerSpec,
    Orientation3D,
    Placement,
    PlacementContext,
    Point3D,
    QuantityPlan,
    StackingPolicy,
)
from backend.solver_v2.solver.elastic_recovery import ElasticRecoveryScanner, ElasticRecoveryResult
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


class TestElasticRecoveryScanner(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.024, 2.350, 2.690),
            max_payload_kg=26000.0,
        )
        self.scanner = ElasticRecoveryScanner(self.container)

    def test_elastic_recovery_increases_elastic_utilization_by_at_least_1_pct(self):
        """
        Acceptance Criteria: Elastic SKU utilization increases by >= 1.0%.
        Scenario: Standard floor cargo is placed up to z=1.8m (leaving 0.89m headspace and side gaps).
        An elastic SKU (0.4m x 0.4m x 0.2m, vol=0.032 m3 each) has 40 unplaced boxes (total vol=1.28 m3).
        1.28 m3 / 76.0 m3 = ~1.68% container volume!
        Recovery scanner packs these unplaced boxes into available headspace/gap spaces.
        """
        sku_main = CargoSKU(
            sku_id="SKU_MAIN",
            name="Main Rigid Box",
            box=BoxDim(1.00, 1.00, 1.80),
            weight_kg=100.0,
            quantity=QuantityPlan(required=4, is_elastic=False),
        )
        sku_elastic = CargoSKU(
            sku_id="SKU_ELASTIC",
            name="Elastic Filler Box",
            box=BoxDim(0.40, 0.40, 0.20),
            weight_kg=8.0,
            quantity=QuantityPlan(required=40, min_quantity=0, is_elastic=True),
        )
        cargo_catalog = [sku_main, sku_elastic]

        # 4 main boxes placed on floor [0..2.0] in x, [0..2.0] in y, [0..1.8] in z
        # Headspace above [0..2.0]x[0..2.0] from z=1.8 to z=2.69 is completely free!
        initial_placements = [
            Placement(
                placement_id="P_MAIN_1",
                instance_id="I_M1",
                sku_id="SKU_MAIN",
                position=Point3D(0.0, 0.0, 0.0),
                orientation=Orientation3D(dx=1.00, dy=1.00, dz=1.80),
                weight_kg=100.0,
                context=PlacementContext.MAIN_WALL,
            ),
            Placement(
                placement_id="P_MAIN_2",
                instance_id="I_M2",
                sku_id="SKU_MAIN",
                position=Point3D(0.0, 1.00, 0.0),
                orientation=Orientation3D(dx=1.00, dy=1.00, dz=1.80),
                weight_kg=100.0,
                context=PlacementContext.MAIN_WALL,
            ),
            Placement(
                placement_id="P_MAIN_3",
                instance_id="I_M3",
                sku_id="SKU_MAIN",
                position=Point3D(1.00, 0.0, 0.0),
                orientation=Orientation3D(dx=1.00, dy=1.00, dz=1.80),
                weight_kg=100.0,
                context=PlacementContext.MAIN_WALL,
            ),
            Placement(
                placement_id="P_MAIN_4",
                instance_id="I_M4",
                sku_id="SKU_MAIN",
                position=Point3D(1.00, 1.00, 0.0),
                orientation=Orientation3D(dx=1.00, dy=1.00, dz=1.80),
                weight_kg=100.0,
                context=PlacementContext.MAIN_WALL,
            ),
        ]

        result: ElasticRecoveryResult = self.scanner.scan_and_recover(
            placements=initial_placements,
            cargo_list=cargo_catalog,
        )

        print(f"\n[Elastic Recovery Test Results]")
        print(f"  Recovered Count: {result.recovered_elastic_count}")
        print(f"  Recovered Volume: {result.recovered_elastic_volume_m3:.4f} m3")
        print(f"  Elastic Util Before: {result.elastic_utilization_before_pct:.2f}%")
        print(f"  Elastic Util After: {result.elastic_utilization_after_pct:.2f}%")
        print(f"  Elastic Util Delta: +{result.elastic_utilization_delta_pct:.2f}%")

        # Verify acceptance criteria: elastic utilization delta >= 1.0%
        self.assertGreaterEqual(
            result.elastic_utilization_delta_pct,
            1.00,
            f"Expected elastic utilization delta >= 1.0%, got {result.elastic_utilization_delta_pct:.2f}%",
        )
        self.assertGreater(result.recovered_elastic_count, 0)
        self.assertGreater(result.recovered_elastic_volume_m3, 0.5)

        # Independent Validator verification
        val_res = IndependentGlobalValidator.validate(
            container=self.container,
            placements=result.placements,
            cargo_list=cargo_catalog,
        )
        self.assertTrue(val_res.is_valid, f"Validation failed: {val_res.rejection_reasons}")


if __name__ == "__main__":
    unittest.main()
