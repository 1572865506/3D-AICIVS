"""API 出口 placement_id 唯一性回归测试。

背景：薄板弹性自由空间扫描引入后，扫描箱与 PASS4.6 锚点通道的步号（step）
不同步，导致 placement_id 重复，API 返回 400 "duplicate cargo id"。
求解器内部（dict 列表）不校验唯一性，只有 OutputAdapter 才会暴露——
因此必须在 API 出口路径上钉住。
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter, OutputAdapter
from backend.solver_v2.solver.unified_solver import UnifiedSolver

CONTAINER = {"usable": {"L": 12.032, "W": 2.352, "H": 2.698}, "maxPayloadTons": 28.6}
# 含弹性薄板 + 刚性短装场景，专门触发弹性扫描与锚点通道混合
CARGO = [
    {"sku": "RIGID-PANEL", "name": "刚性面板", "w": 0.6, "d": 0.5, "h": 0.4, "weight": 10, "quantity": 120},
    {"sku": "ELASTIC-THIN", "name": "弹性薄板", "w": 0.488, "d": 0.08, "h": 0.336, "weight": 2.15,
     "quantity": 300, "requirement": "封柜门; 可以减少点"},
]


def test_api_response_has_unique_placement_ids():
    container = InputAdapter.parse_container(CONTAINER)
    cargo = InputAdapter.parse_cargo_list(CARGO)
    sol = UnifiedSolver(container).solve(cargo)
    # OutputAdapter 在重复 ID 时抛 ValueError（API 400 的根因）
    resp = OutputAdapter.to_legacy_response(solution=sol, container=container, cargo_list=cargo)
    ids = [item["id"] for item in resp["placedBoxes"]]
    assert len(ids) == len(set(ids)), "API 响应存在重复 placement_id"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
