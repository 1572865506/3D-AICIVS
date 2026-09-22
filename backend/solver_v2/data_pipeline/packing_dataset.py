# -*- coding: utf-8 -*-
"""
PyTorch 神经决策训练数据集 (Packing Decision Dataset for Transformer Brain)

将数据工场沉淀的金牌与银牌高质量方案转换为 PyTorch 张量，
为 Phase 4 的 Transformer 决策大脑 (Actor-Critic / Guided MCTS) 提供标准训练数据。

数据张量结构:
  1. container_features: FloatTensor [4] -> 归一化内长、宽、高与最大载重
  2. sku_matrix: FloatTensor [N, F] -> 货物规格矩阵:
       (dx, dy, dz, weight_kg, max_bearing, max_layers, must_floor, no_top, qty)
  3. action_sequence: FloatTensor [T, 5] -> 专家装载动作序列:
       (sku_index, norm_x, norm_y, norm_z, orientation_id)
  4. quality_score: FloatTensor [1] -> 方案质量评定分 (0.0 ~ 1.0)
  5. seq_mask: BoolTensor [T] -> 序列有效步长掩码 (用于变长 Batch Padding)

被谁调用:
  - brain/trainer.py (Phase 4 Transformer 模型训练器)
  - tests/test_data_pipeline.py (数据集张量形状单测)
"""
from __future__ import annotations

import os
import json
import glob
from typing import Any, Dict, List, Optional, Tuple, Union

import torch
from torch.utils.data import Dataset, DataLoader


class PackingDataset(Dataset):
    """3D 装柜专家决策数据集 (PyTorch Dataset)"""

    def __init__(
        self,
        data_dir: Optional[str] = None,
        samples: Optional[List[Dict[str, Any]]] = None,
        max_skus: int = 24,
        max_steps: int = 256,
    ):
        self.max_skus = max_skus
        self.max_steps = max_steps
        self.samples: List[Dict[str, Any]] = []

        if samples is not None:
            self.samples = samples
        elif data_dir is not None and os.path.exists(data_dir):
            pattern = os.path.join(data_dir, "*.json")
            for fp in glob.glob(pattern):
                if fp.endswith("dataset_index.jsonl"):
                    continue
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict) and "placements" in data and "container" in data:
                            self.samples.append(data)
                except Exception:
                    pass

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        sample = self.samples[idx]

        # 1. 提取集装箱特征
        c_spec = sample["container"]
        c_dim = c_spec.get("inner_dim", [12.032, 2.352, 2.698])
        c_payload = float(c_spec.get("max_payload_kg", 28000.0))
        cL, cW, cH = float(c_dim[0]), float(c_dim[1]), float(c_dim[2])

        container_feat = torch.tensor([
            cL / 15.0,
            cW / 3.0,
            cH / 3.0,
            c_payload / 30000.0,
        ], dtype=torch.float32)

        # 2. 提取 SKU 特征矩阵 [max_skus, 9]
        sku_list = sample.get("cargo_skus", [])
        sku_to_idx = {s["sku_id"]: i for i, s in enumerate(sku_list[:self.max_skus])}

        sku_matrix = torch.zeros((self.max_skus, 9), dtype=torch.float32)
        for i, s in enumerate(sku_list[:self.max_skus]):
            bx, by, bz = s["box"]
            w = float(s.get("weight_kg", 0.0))
            bearing = float(s.get("max_bearing_kg") or 2000.0)
            layers = float(s.get("max_stack_layers") or 5.0)
            floor = 1.0 if s.get("must_be_on_floor") else 0.0
            no_top = 1.0 if not s.get("allow_stacking_on_top", True) else 0.0
            qty = float(s.get("required_qty", 1))

            sku_matrix[i] = torch.tensor([
                bx / 3.0, by / 3.0, bz / 3.0,
                w / 500.0,
                bearing / 2000.0,
                layers / 10.0,
                floor,
                no_top,
                qty / 100.0,
            ], dtype=torch.float32)

        # 3. 提取装载决策步骤 [max_steps, 5] 与 seq_mask [max_steps]
        placements = sample.get("placements", [])
        action_seq = torch.zeros((self.max_steps, 5), dtype=torch.float32)
        seq_mask = torch.zeros(self.max_steps, dtype=torch.bool)

        actual_steps = min(len(placements), self.max_steps)
        for t in range(actual_steps):
            p = placements[t]
            sid = p.get("sku_id", "")
            s_idx = float(sku_to_idx.get(sid, 0))
            pos = p.get("position", [0.0, 0.0, 0.0])
            dim = p.get("dimension", [1.0, 1.0, 1.0])

            # 归一化坐标在 [0, 1]
            norm_x = min(1.0, max(0.0, float(pos[0]) / max(cL, 1e-3)))
            norm_y = min(1.0, max(0.0, float(pos[1]) / max(cW, 1e-3)))
            norm_z = min(1.0, max(0.0, float(pos[2]) / max(cH, 1e-3)))

            # 姿态粗分类 ID: 0 (Upright), 1 (Flat), 2 (Side)
            rot_id = 0.0
            if abs(dim[2] - dim[1]) > 0.05:
                rot_id = 1.0

            action_seq[t] = torch.tensor([s_idx, norm_x, norm_y, norm_z, rot_id], dtype=torch.float32)
            seq_mask[t] = True

        # 4. 方案质量标签
        rating = sample.get("rating", "SILVER")
        quality_score = torch.tensor([
            1.0 if rating == "GOLD" else (0.6 if rating == "SILVER" else 0.0)
        ], dtype=torch.float32)

        return {
            "container_features": container_feat,
            "sku_matrix": sku_matrix,
            "action_sequence": action_seq,
            "seq_mask": seq_mask,
            "quality_score": quality_score,
            "actual_steps": torch.tensor(actual_steps, dtype=torch.long),
        }


def create_dataloader(
    dataset: Any,
    batch_size: int = 16,
    shuffle: bool = True,
    num_workers: int = 0,
) -> DataLoader:
    """创建适用于 GPU 训练的高性能 DataLoader (支持传入 PackingDataset 实例或数据目录路径)"""
    if isinstance(dataset, (str, os.PathLike)):
        dataset = PackingDataset(data_dir=str(dataset))
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        pin_memory=torch.cuda.is_available(),
    )
