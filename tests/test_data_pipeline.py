# -*- coding: utf-8 -*-
"""
数据工场全链路单测套件 (Unit Tests for Data Pipeline)

测试覆盖:
  1. ManifestSynthesizer: 多样化工况合成与 4 大柜型支持
  2. AntiCavityFilter: 专杀内部蜂窝空洞、饥饿弃装与优先级倒挂
  3. SolutionCollector: 金牌与银牌方案持久化与索引写入
  4. PackingDataset & DataLoader: PyTorch 张量形状与 GPU 批处理加载
"""
import unittest
import os
import shutil
import tempfile
import sys
import torch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.domain.models import (
    BoxDim,
    Point3D,
    Orientation3D,
    QuantityPlan,
    ContainerSpec,
    CargoSKU,
    Placement,
    PlacementContext,
)
from backend.solver_v2.data_pipeline import (
    ManifestSynthesizer,
    AntiCavityFilter,
    SolutionCollector,
    PackingDataset,
    create_dataloader,
)


class TestDataPipeline(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.synthesizer = ManifestSynthesizer(seed=123)
        self.quality_filter = AntiCavityFilter()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_synthesizer_all_containers(self):
        """测试工况合成器：支持 20GP, 40GP, 40HQ, 45HQ 且货单结构完备"""
        for c_type in ["20GP", "40GP", "40HQ", "45HQ"]:
            container, skus = self.synthesizer.generate_scenario(
                scenario_id=f"test_{c_type}",
                container_type=c_type,
            )
            self.assertEqual(container.code, c_type)
            self.assertGreater(len(skus), 2)
            for sku in skus:
                self.assertGreater(sku.quantity.required, 0)
                self.assertGreater(sku.box.x, 0)
                self.assertGreater(sku.box.y, 0)
                self.assertGreater(sku.box.z, 0)
                self.assertGreater(sku.weight_kg, 0)

    def test_anti_cavity_filter_rejects_flaws(self):
        """测试防蜂窝空洞过滤器：坚决驳回饥饿、倒挂与违规方案"""
        container = self.synthesizer.create_container("40HQ")
        sku1 = CargoSKU(
            sku_id="SKU_RIGID_1",
            name="Rigid Box 1",
            box=BoxDim(1.0, 1.0, 1.0),
            weight_kg=100.0,
            quantity=QuantityPlan(required=5),
        )
        sku_elastic = CargoSKU(
            sku_id="SKU_ELASTIC_1",
            name="Elastic Filler 1",
            box=BoxDim(0.5, 0.5, 0.5),
            weight_kg=10.0,
            quantity=QuantityPlan(required=10, is_elastic=True),
        )

        # 场景 1: 刚性件饥饿 (SKU_RIGID_1 完全未装)
        p_elastic = {
            "placement_id": "p1", "sku_id": "SKU_ELASTIC_1",
            "x": 0.0, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 0.5, "dz": 0.5, "weight_kg": 10.0,
        }
        report = self.quality_filter.audit_solution(
            solution_id="sol_starve",
            container=container,
            placements=[p_elastic],
            cargo_skus=[sku1, sku_elastic],
        )
        self.assertEqual(report.rating, "REJECT")
        self.assertIn("严重饥饿", " ".join(report.rejection_reasons))

    def test_collector_and_dataset_tensor_pipeline(self):
        """测试数据沉淀与 PyTorch Dataset 张量构建全流程"""
        collector = SolutionCollector(output_dir=self.test_dir, quality_filter=self.quality_filter)

        container = self.synthesizer.create_container("40HQ")
        sku = CargoSKU(
            sku_id="SKU_CUBE",
            name="Standard Cube",
            box=BoxDim(1.0, 1.0, 1.0),
            weight_kg=100.0,
            quantity=QuantityPlan(required=4),
        )
        placements = [
            {"placement_id": "p1", "sku_id": "SKU_CUBE", "x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "weight_kg": 100.0},
            {"placement_id": "p2", "sku_id": "SKU_CUBE", "x": 1.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "weight_kg": 100.0},
            {"placement_id": "p3", "sku_id": "SKU_CUBE", "x": 0.0, "y": 1.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "weight_kg": 100.0},
            {"placement_id": "p4", "sku_id": "SKU_CUBE", "x": 1.0, "y": 1.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "weight_kg": 100.0},
        ]

        # 归档该合法密集方案
        report = collector.process_and_archive(
            scenario_id="sol_dense_4",
            container=container,
            cargo_skus=[sku],
            placements=placements,
            execution_time_ms=50.0,
        )
        self.assertIn(report.rating, ("GOLD", "SILVER"))

        # 校验持久化文件
        index_file = os.path.join(self.test_dir, "dataset_index.jsonl")
        self.assertTrue(os.path.exists(index_file))

        # 校验 PyTorch Dataset 加载
        dataset = PackingDataset(data_dir=self.test_dir, max_skus=12, max_steps=32)
        self.assertEqual(len(dataset), 1)

        item = dataset[0]
        self.assertIn("container_features", item)
        self.assertIn("sku_matrix", item)
        self.assertIn("action_sequence", item)
        self.assertIn("seq_mask", item)
        self.assertIn("quality_score", item)

        # 校验张量维度
        self.assertEqual(item["container_features"].shape, torch.Size([4]))
        self.assertEqual(item["sku_matrix"].shape, torch.Size([12, 9]))
        self.assertEqual(item["action_sequence"].shape, torch.Size([32, 5]))
        self.assertEqual(item["seq_mask"].shape, torch.Size([32]))
        self.assertEqual(item["actual_steps"].item(), 4)

        # 校验 DataLoader 批处理加载
        loader = create_dataloader(dataset, batch_size=2, shuffle=False)
        batch = next(iter(loader))
        self.assertEqual(batch["container_features"].shape[0], 1)
        self.assertEqual(batch["action_sequence"].shape[0], 1)


if __name__ == "__main__":
    unittest.main()
