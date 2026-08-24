import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.api.adapters.layout_adapter import LayoutAdapter
from backend.api.adapters.scene_adapter import SceneAdapter
from backend.api.schemas.cargo_schema import validate_cargo
from backend.solver_v2.domain.models import (
    BoxDim, CargoSKU, ContainerSpec, Orientation3D, Placement,
    PlacementContext, Point3D, QuantityPlan,
)


ROOT = Path(__file__).resolve().parents[1]


class TestBLK007F77FrontendDimensionSchema(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec("40HQ", BoxDim(12.032, 2.350, 2.690), 26500)
        self.sku = CargoSKU(
            "SKU-14", "19寸 显示器 BG (DA)", BoxDim(0.488, 0.080, 0.336), 2.15,
            QuantityPlan(674),
        )
        # Physical L/W are 488/80 mm; this placed orientation intentionally swaps
        # its occupied horizontal AABB to prove the two schemas can coexist.
        self.placement = Placement(
            "sku14_rotated", "sku14_instance", "SKU-14", Point3D(1, 0, 0),
            Orientation3D(0.080, 0.488, 0.336, "UPRIGHT_ROTATED"), 2.15,
            PlacementContext.MAIN_WALL,
        )
        self.cargo = LayoutAdapter.cargo(
            [self.placement], [self.sku], self.container,
            SimpleNamespace(steps=[]), [],
        )

    def test_product_and_occupied_dimensions_are_distinct(self):
        item = self.cargo[0]
        self.assertEqual(item["productDimensions"], {"length": 0.488, "width": 0.080, "height": 0.336})
        self.assertEqual(item["occupiedDimensions"], {"width": 0.080, "depth": 0.488, "height": 0.336})
        self.assertEqual(item["axisDefinition"], {"lengthAxis": "X", "widthAxis": "Y", "heightAxis": "Z"})
        self.assertTrue(validate_cargo({"cargo": self.cargo}))

    def test_renderer_scale_remains_occupied_aabb(self):
        scene = SceneAdapter.scene(self.cargo, self.container)
        self.assertEqual(scene["objects"][0]["scale"], [0.080, 0.488, 0.336])

    def test_frontend_detail_and_export_use_product_dimensions(self):
        source = (ROOT / "index.html").read_text(encoding="utf-8")
        switch = (ROOT / "frontend/src/backendSwitch.js").read_text(encoding="utf-8")
        self.assertIn("规格尺寸(长×宽×高)", source)
        self.assertIn("占用空间", source)
        self.assertIn("cargo.productDimensions.length", source)
        self.assertIn("cargo.occupiedDimensions.width", source)
        self.assertNotIn("dimensions: `${Math.round(object.scale[0]", source)
        self.assertIn("cargoExportRows", switch)
        self.assertIn("cargo.productDimensions.length", switch)

    def test_mock_contract_has_both_dimension_views(self):
        fixture = json.loads((ROOT / "frontend/mock/demo_loading_result.json").read_text(encoding="utf-8"))
        for item in fixture["cargo"]:
            self.assertIn("productDimensions", item)
            self.assertIn("occupiedDimensions", item)
            self.assertIn("axisDefinition", item)


if __name__ == "__main__":
    unittest.main()
