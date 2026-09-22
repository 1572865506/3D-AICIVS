"""PackingTransformer: 基于 PyTorch 的 3D 装箱自注意力决策大脑

负责变长 SKU 几何关系建模、全局货柜约束感知、动作先验概率预测与装箱状态价值估算 (Actor-Critic Dual Heads)。
针对本地 NVIDIA GeForce GTX 1070 GPU 与 CPU 双环境进行优化。
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple
import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class TransformerConfig:
    """Transformer 决策网络超参数配置"""
    d_model: int = 128
    nhead: int = 4
    num_encoder_layers: int = 3
    dim_feedforward: int = 256
    dropout: float = 0.0
    container_feature_dim: int = 4  # [L, W, H, max_payload]
    sku_feature_dim: int = 9        # [dx, dy, dz, weight, required, max_bearing, max_layers, must_floor, allow_top]
    state_feature_dim: int = 6      # [packed_count, packed_vol_ratio, packed_weight_ratio, max_x_ratio, max_y_ratio, max_z_ratio]
    num_rotations: int = 3          # 姿态类别: [Upright, Flat, Side]


class PackingTransformer(nn.Module):
    """3D-AICIVS 装箱决策大脑网络

    输入:
      - container_features: [B, 4] 货柜全局几何与承载上限
      - sku_matrix: [B, N, 9] 候选 SKU 物理规格特征矩阵
      - state_features: [B, 6] 当前装载进度与空间占用简报 (可选，默认零填充)
      - sku_padding_mask: [B, N] 布尔掩码 (True 表示该位置为填充 padding)

    输出字典:
      - sku_logits: [B, N] 待放置 SKU 先验对数概率
      - pos_guidance: [B, N, 3] 归一化落位坐标指引 (mu_x, mu_y, mu_z) in [0, 1]
      - rot_logits: [B, N, 3] 姿态选择先验对数概率
      - value: [B, 1] 方案金牌质量期望评分预测 (0.0 ~ 100.0)
    """

    def __init__(self, config: Optional[TransformerConfig] = None):
        super().__init__()
        self.config = config or TransformerConfig()
        cfg = self.config

        # 1. 货柜与状态上下文编码
        self.container_encoder = nn.Sequential(
            nn.Linear(cfg.container_feature_dim, cfg.d_model),
            nn.LayerNorm(cfg.d_model),
            nn.GELU(),
            nn.Linear(cfg.d_model, cfg.d_model),
        )

        self.state_encoder = nn.Sequential(
            nn.Linear(cfg.state_feature_dim, cfg.d_model),
            nn.LayerNorm(cfg.d_model),
            nn.GELU(),
            nn.Linear(cfg.d_model, cfg.d_model),
        )

        # 2. SKU 序列投射编码
        self.sku_in_proj = nn.Sequential(
            nn.Linear(cfg.sku_feature_dim, cfg.d_model),
            nn.LayerNorm(cfg.d_model),
            nn.GELU(),
            nn.Linear(cfg.d_model, cfg.d_model),
        )

        # 3. 几何关系自注意力编码器
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=cfg.d_model,
            nhead=cfg.nhead,
            dim_feedforward=cfg.dim_feedforward,
            dropout=cfg.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.sku_transformer = nn.TransformerEncoder(
            encoder_layer,
            num_layers=cfg.num_encoder_layers,
        )

        # 4. 跨模态上下文融合层
        self.context_fusion = nn.Sequential(
            nn.Linear(cfg.d_model * 3, cfg.d_model),
            nn.LayerNorm(cfg.d_model),
            nn.GELU(),
        )

        # 5. Actor Policy Heads
        # SKU 挑选 Logits
        self.sku_policy_head = nn.Sequential(
            nn.Linear(cfg.d_model, cfg.d_model // 2),
            nn.GELU(),
            nn.Linear(cfg.d_model // 2, 1),
        )

        # 坐标连续指导 (x, y, z) 归一化预测
        self.pos_guidance_head = nn.Sequential(
            nn.Linear(cfg.d_model, cfg.d_model // 2),
            nn.GELU(),
            nn.Linear(cfg.d_model // 2, 3),
            nn.Sigmoid(),
        )

        # 姿态分类 Logits
        self.rot_policy_head = nn.Sequential(
            nn.Linear(cfg.d_model, cfg.d_model // 2),
            nn.GELU(),
            nn.Linear(cfg.d_model // 2, cfg.num_rotations),
        )

        # 6. Critic Value Head
        self.value_head = nn.Sequential(
            nn.Linear(cfg.d_model, cfg.d_model),
            nn.GELU(),
            nn.Linear(cfg.d_model, 1),
            nn.Sigmoid(),
        )

    def forward(
        self,
        container_features: torch.Tensor,
        sku_matrix: torch.Tensor,
        state_features: Optional[torch.Tensor] = None,
        sku_padding_mask: Optional[torch.Tensor] = None,
    ) -> Dict[str, torch.Tensor]:
        """前向推导

        Args:
            container_features: [B, 4]
            sku_matrix: [B, N, 9]
            state_features: [B, 6] (可省略，自动填 0)
            sku_padding_mask: [B, N] (True 表示 Padding)
        """
        B, N, _ = sku_matrix.shape
        device = sku_matrix.device

        if state_features is None:
            state_features = torch.zeros((B, self.config.state_feature_dim), device=device, dtype=torch.float32)

        # 1. 上下文嵌入
        c_emb = self.container_encoder(container_features)   # [B, d_model]
        s_emb = self.state_encoder(state_features)           # [B, d_model]
        global_context = (c_emb + s_emb) / 2.0               # [B, d_model]

        # 2. SKU 序列编码
        sku_h = self.sku_in_proj(sku_matrix)                # [B, N, d_model]

        # 3. Transformer 自注意力交互
        sku_encoded = self.sku_transformer(
            sku_h,
            src_key_padding_mask=sku_padding_mask,
        )  # [B, N, d_model]

        # 4. 上下文广播融合
        c_broadcast = c_emb.unsqueeze(1).expand(-1, N, -1)   # [B, N, d_model]
        s_broadcast = s_emb.unsqueeze(1).expand(-1, N, -1)   # [B, N, d_model]
        fused_sku = self.context_fusion(
            torch.cat([sku_encoded, c_broadcast, s_broadcast], dim=-1)
        )  # [B, N, d_model]

        # 5. Policy 输出
        sku_logits = self.sku_policy_head(fused_sku).squeeze(-1)  # [B, N]
        if sku_padding_mask is not None:
            sku_logits = sku_logits.masked_fill(sku_padding_mask, -1e9)

        pos_guidance = self.pos_guidance_head(fused_sku)          # [B, N, 3]
        rot_logits = self.rot_policy_head(fused_sku)              # [B, N, 3]

        # 6. Value 输出 (汇聚未 padding 的 SKU 平均向量 + global_context)
        if sku_padding_mask is not None:
            mask_expanded = (~sku_padding_mask).unsqueeze(-1).float()
            pooled_sku = (fused_sku * mask_expanded).sum(dim=1) / mask_expanded.sum(dim=1).clamp(min=1.0)
        else:
            pooled_sku = fused_sku.mean(dim=1)

        summary_vec = (pooled_sku + global_context) / 2.0
        # Value 缩放到 0.0 ~ 100.0 分
        value = self.value_head(summary_vec) * 100.0              # [B, 1]

        return {
            "sku_logits": sku_logits,
            "pos_guidance": pos_guidance,
            "rot_logits": rot_logits,
            "value": value,
        }

    @torch.no_grad()
    def predict_action_prior(
        self,
        container_features: torch.Tensor,
        sku_matrix: torch.Tensor,
        state_features: Optional[torch.Tensor] = None,
        valid_sku_mask: Optional[torch.Tensor] = None,
    ) -> Dict[str, Any]:
        """为引导搜索提供轻量单步动作先验预测

        返回经 Softmax 处理的 SKU 选择概率、姿态概率及三维落位参考点
        """
        self.eval()
        if container_features.dim() == 1:
            container_features = container_features.unsqueeze(0)
        if sku_matrix.dim() == 2:
            sku_matrix = sku_matrix.unsqueeze(0)
        if state_features is not None and state_features.dim() == 1:
            state_features = state_features.unsqueeze(0)

        padding_mask = None
        if valid_sku_mask is not None:
            if valid_sku_mask.dim() == 1:
                valid_sku_mask = valid_sku_mask.unsqueeze(0)
            padding_mask = ~valid_sku_mask

        out = self.forward(
            container_features=container_features,
            sku_matrix=sku_matrix,
            state_features=state_features,
            sku_padding_mask=padding_mask,
        )

        sku_probs = F.softmax(out["sku_logits"], dim=-1)[0].cpu().tolist()
        pos_guidance = out["pos_guidance"][0].cpu().tolist()
        rot_probs = F.softmax(out["rot_logits"], dim=-1)[0].cpu().tolist()
        est_value = float(out["value"][0, 0].item())

        return {
            "sku_probs": sku_probs,
            "pos_guidance": pos_guidance,
            "rot_probs": rot_probs,
            "estimated_value": est_value,
        }
