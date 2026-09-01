import json,unittest
from pathlib import Path
from backend.solver_v2.api.adapter import InputAdapter
from src.cargo.dimension_normalization import DimensionAudit,DimensionNormalizer

DATASET=Path("devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json")

class TestBLK000DDimensionNormalization(unittest.TestCase):
    def test_dim_001_sku_dimension_normalization(self):
        result=DimensionNormalizer().normalize_source({"w":.080,"d":.488,"h":.336},"SKU-14",True)
        self.assertEqual((result.normalized.length,result.normalized.width,result.normalized.height),(.488,.080,.336))
        parsed=InputAdapter.parse_cargo_list([{"sku":"SKU-14","name":"Display","source":{"w":.080,"d":.488,"h":.336,"quantity":1}}])[0]
        self.assertEqual((parsed.box.x,parsed.box.y,parsed.box.z),(.488,.080,.336))

    def test_dim_002_display_thickness_detection(self):
        result=DimensionNormalizer().normalize_values(.488,.080,.336,True,"SKU-14")
        self.assertEqual(result.normalized.thicknessAxis,"WIDTH")
        self.assertTrue(any(issue.code=="THICKNESS_AXIS" for issue in result.issues))

    def test_dim_003_axis_swap_detection(self):
        result=DimensionNormalizer().normalize_values(.080,.488,.336,True,"SKU-14")
        self.assertEqual(result.status,"FIXED_AXIS_MAPPING")
        self.assertTrue(any(issue.code=="AXIS_SWAP_WARNING" for issue in result.issues))

    def test_dim_004_full_14_sku_audit_and_sku14(self):
        data=json.loads(DATASET.read_text(encoding="utf-8"))
        audit=DimensionAudit().audit_manifest(data["cargo"])
        self.assertEqual(len(audit), len(data["cargo"]))
        self.assertTrue(all(row.normalized.length>=row.normalized.width for row in audit))
        sku14=next(row for row in audit if row.sku=="SKU-14")
        self.assertEqual((sku14.normalized.length,sku14.normalized.width,sku14.normalized.height),(.488,.080,.336))

    def test_affected_optimizers_do_not_read_ambiguous_box_xyz_or_size_array(self):
        roots=[Path("src/optimization/layer"),Path("src/optimization/direction"),Path("src/optimization/global_rebuild"),Path("src/optimization/cargo_recomposition")]
        content="\n".join(path.read_text(encoding="utf-8") for root in roots for path in root.glob("*.py"))
        for token in (".box.x",".box.y",".box.z",'"size":['):self.assertNotIn(token,content)

if __name__=="__main__":unittest.main()
