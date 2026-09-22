# -*- coding: utf-8 -*-
"""
训练数据管线 (Training Data Pipeline)

构建 10,000 级多样化工业工况、驱动多策略求解、过滤内部蜂窝空洞、
沉淀金牌示范方案库并转换为 PyTorch 格式，为 Transformer 大脑提供高品质训练数据。

核心组件:
  - ManifestSynthesizer: 多样化参数化工况合成器
  - AntiCavityFilter: 专杀内部蜂窝空洞与烟囱柱的物理质量过滤器
  - SolutionCollector: 高质量金牌方案持久化收集器
  - PackingDataset: PyTorch GPU 格式张量数据集与 DataLoader 构造器

被谁调用:
  - scripts/run_data_factory.py (数据工场批生产控制台)
  - brain/ (Phase 4 深度引导搜索与网络训练)
  - tests/test_data_pipeline.py (数据管线全链路单测)
"""

from .manifest_synthesizer import ManifestSynthesizer, CONTAINER_TEMPLATES
from .anti_cavity_filter import AntiCavityFilter, QualityAuditReport
from .collector import SolutionCollector
from .packing_dataset import PackingDataset, create_dataloader

__all__ = [
    "ManifestSynthesizer",
    "CONTAINER_TEMPLATES",
    "AntiCavityFilter",
    "QualityAuditReport",
    "SolutionCollector",
    "PackingDataset",
    "create_dataloader",
]
