"""3D-AICIVS Transformer 决策大脑模块

提供基于自注意力机制的装箱状态表征、SKU 挑选策略与最终方案质量价值评估网络 (Actor-Critic)。
"""

from .packing_transformer import PackingTransformer, TransformerConfig

__all__ = [
    "PackingTransformer",
    "TransformerConfig",
]
