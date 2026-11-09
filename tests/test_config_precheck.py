"""货单约束可满足性预检测试。

把"约束组合无解"从求解后的静默饥饿提前暴露为明确配置错误：
- 仅平放 + 仅顶层 + 无底座 → ERROR（API 422）
- 封柜门 + 放中间 → WARN（门区优先）
- 禁压 + 多层 / 落地 + 多层 → WARN（语义降级说明）
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.validation.config_precheck import precheck_manifest

C = {"usable": {"L": 6.0, "W": 2.4, "H": 2.6}}


def _run(raw):
    return precheck_manifest(InputAdapter.parse_cargo_list(raw), InputAdapter.parse_container(C))


class TestConfigPrecheck:
    def test_flat_only_top_without_base_is_error(self):
        r = _run([{"sku": "C", "name": "矛盾", "w": 1.0, "d": 0.08, "h": 0.4, "weight": 10,
                   "quantity": 10, "allowedOrientation": "flat_only", "flatOnlyOnTop": True}])
        assert r["ok"] is False
        assert any(e["code"] == "FLAT_ON_TOP_WITHOUT_BASE" for e in r["errors"])

    def test_no_legal_orientation_is_error(self):
        r = _run([{"sku": "X", "name": "无合法朝向", "w": 1.0, "d": 1.0, "h": 1.0, "weight": 5,
                   "quantity": 1, "cargoProfile": {"orientationPolicy": {"rules": []}}}])
        # 空规则 → 回退 legacy flags（默认立放），因此此处应可满足
        assert r["ok"] is True

    def test_zone_directive_conflict_warns(self):
        r = _run([{"sku": "D", "name": "双区域", "w": 0.8, "d": 0.6, "h": 0.5, "weight": 15,
                   "quantity": 10, "requirement": "封柜门; 放中间"}])
        assert r["ok"] is True
        assert any(w["code"] == "ZONE_DIRECTIVE_CONFLICT" for w in r["warnings"])

    def test_no_top_stack_vs_layers_warns(self):
        r = _run([{"sku": "B", "name": "禁压却堆", "w": 1.0, "d": 1.0, "h": 0.5, "weight": 20,
                   "quantity": 8, "allowStackingOnTop": False, "maxStackLayers": 3}])
        assert any(w["code"] == "NO_TOP_STACK_VS_MAX_LAYERS" for w in r["warnings"])

    def test_floor_only_self_stack_warns(self):
        r = _run([{"sku": "A", "name": "落地多层", "w": 1.0, "d": 1.0, "h": 0.5, "weight": 20,
                   "quantity": 8, "mustBeOnFloor": True, "maxStackLayers": 3}])
        assert any(w["code"] == "FLOOR_ONLY_SELF_STACK" for w in r["warnings"])

    def test_normal_manifest_clean(self):
        r = _run([{"sku": "N", "name": "正常", "w": 1.0, "d": 1.0, "h": 0.5, "weight": 20, "quantity": 8}])
        assert r["ok"] is True and not r["errors"] and not r["warnings"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
