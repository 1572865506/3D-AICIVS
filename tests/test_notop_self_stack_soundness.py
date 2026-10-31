import unittest
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.domain.models import (
    ContainerSpec, BoxDim, CargoSKU, StackingPolicy, QuantityPlan
)
from backend.solver_v2.solver.unified_solver import UnifiedSolver


class TestNoTopSelfStackSoundness(unittest.TestCase):
    """
    Test suite for eliminating no_top_stack semantic conflicts & self-stacking false-rejection.
    A SKU with allow_stacking_on_top=False but stack_on_self=True must be allowed
    to stack on identical SKUs up to max_stack_layers, while strictly forbidding foreign SKUs.
    """

    def setUp(self):
        self.container = ContainerSpec(
            code="TestContainer",
            inner_dim=BoxDim(x=3.0, y=2.0, z=2.0),
            max_payload_kg=10000.0
        )
        self.solver = UnifiedSolver(self.container)

    def test_self_stacking_allowed_when_top_stack_forbidden(self):
        """SKU allowing self-stacking must NOT be rejected by support or constraint check."""
        skus = [
            CargoSKU(
                sku_id="SKU_NO_TOP_FOREIGN",
                name="Fragile Display Carton",
                box=BoxDim(1.0, 1.0, 0.5),
                weight_kg=20.0,
                quantity=QuantityPlan(required=2),
                stacking_policy=StackingPolicy(
                    allow_stacking_on_top=False,
                    stack_on_self=True,
                    max_stack_layers=3
                )
            )
        ]
        
        # Test full solve to ensure all 2 cartons are stacked vertically without artificial void
        solution = self.solver.solve(skus)
        self.assertEqual(solution.placed_count, 2, "Both cartons must be placed via self-stacking")
        self.assertEqual(solution.unplaced_count, 0)
        self.assertEqual(len(solution.validation_result.violations), 0)

    def test_foreign_stacking_strictly_rejected(self):
        """Foreign SKU must be strictly rejected from stacking on SKU_NO_TOP_FOREIGN."""
        skus = [
            CargoSKU(
                sku_id="SKU_BASE",
                name="No Top Cargo",
                box=BoxDim(1.0, 1.0, 0.5),
                weight_kg=20.0,
                quantity=QuantityPlan(required=1),
                stacking_policy=StackingPolicy(
                    allow_stacking_on_top=False,
                    stack_on_self=True,
                    max_stack_layers=2
                )
            ),
            CargoSKU(
                sku_id="SKU_FOREIGN",
                name="Foreign Heavy Carton",
                box=BoxDim(1.0, 1.0, 0.5),
                weight_kg=30.0,
                quantity=QuantityPlan(required=1),
                stacking_policy=StackingPolicy(max_stack_layers=2)
            )
        ]
        
        # Convert skus to tensors to initialize _sku_tensor_map
        tensors = self.solver._convert_cargo_skus_to_tensors(skus)
        self.solver._sku_tensor_map = {t.sku_id: t for t in tensors}

        base_placement = {
            "sku_id": "SKU_BASE",
            "x": 0.0, "y": 0.0, "z": 0.0,
            "dx": 1.0, "dy": 1.0, "dz": 0.5,
            "weight_kg": 20.0,
            "context": "MAIN_WALL",
            "step": 0
        }

        # 1. Foreign candidate directly on top of base must be rejected
        foreign_cand = {
            "sku_id": "SKU_FOREIGN",
            "x": 0.0, "y": 0.0, "z": 0.5,
            "dx": 1.0, "dy": 1.0, "dz": 0.5,
            "weight_kg": 30.0
        }
        self.assertFalse(
            self.solver._check_placement_constraints(foreign_cand, [base_placement]),
            "Foreign SKU must be rejected by _check_placement_constraints"
        )

        # 2. Identical SKU on top of base must be accepted
        same_cand = {
            "sku_id": "SKU_BASE",
            "x": 0.0, "y": 0.0, "z": 0.5,
            "dx": 1.0, "dy": 1.0, "dz": 0.5,
            "weight_kg": 20.0
        }
        self.assertTrue(
            self.solver._has_sufficient_support(same_cand, [base_placement]),
            "_has_sufficient_support must NOT reject same-SKU self stacking"
        )
        self.assertTrue(
            self.solver._check_placement_constraints(same_cand, [base_placement]),
            "_check_placement_constraints must accept same-SKU self stacking"
        )


if __name__ == "__main__":
    unittest.main()
