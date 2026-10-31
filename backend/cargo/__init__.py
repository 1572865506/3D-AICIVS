"""货物情报与维度归一化领域包（backend 内置版）。

用途：为 API 响应构建层提供 SKU 货物类别画像（CargoProfileEngine）与
产品尺寸归一化（DimensionNormalizer）能力。

输入：CargoSKU 领域模型列表（backend.solver_v2.domain.models）；
输出：CargoProfile / NormalizedDimension 等结构化画像与归一化尺寸。

被谁调用：backend/api/adapters/layout_adapter.py（API 货物模型适配）。
来源：自 src/cargo/intelligence 与 src/cargo/dimension_normalization 原样
内置，用于消除 backend/ 对 src/ 的违规导入（AGENTS.md 铁律 1.1），
原 src/ 包保持不动以继续服务既有测试。
"""
