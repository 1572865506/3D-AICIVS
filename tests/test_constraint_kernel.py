"""共享约束内核单测（单一规则源）。

确保 UnifiedSolver 生产门禁与 feasibility/HardValidationPipeline（遗留路径）
调用同一份 tipping / 层数 / 压强判定，避免再次出现语义漂移。
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.validation.constraint_kernel import (
    tipping_verdict, tipping_safe, same_sku_chain_depth, pressure_violation,
)


def _box(sku, x, y, z, dx, dy, dz, w=10.0, pid=None, **extra):
    d = {"sku_id": sku, "x": x, "y": y, "z": z, "dx": dx, "dy": dy, "dz": dz,
         "weight_kg": w, "placement_id": pid or f"{sku}_{x}_{y}_{z}"}
    d.update(extra)
    return d


class TestTippingKernel:
    def test_intrinsic_sf_passes(self):
        """SF = 2dx/dz >= 1.5 → 自稳（宽箱）。"""
        cand = _box("A", 1.0, 0, 0, 1.0, 1.0, 1.0)  # SF=2.0
        assert tipping_safe(cand, [], 12.0) is True
        assert tipping_verdict(cand, [], 12.0).reason == "INTRINSIC_SF"

    def test_tall_slender_without_support_fails(self):
        """高瘦箱 SF<1.5 且无前向支承 → 不安全。"""
        cand = _box("B", 1.0, 0, 0, 0.3, 1.0, 1.0)  # SF=0.6
        v = tipping_verdict(cand, [], 12.0)
        assert v.safe is False and v.reason == "NO_FORWARD_SUPPORT"

    def test_door_face_exempts(self):
        """贴近门端面 → 豁免。"""
        cand = _box("C", 11.7, 0, 0, 0.3, 1.0, 1.0)  # x+dx=12.0 >= L-0.04
        assert tipping_verdict(cand, [], 12.0).reason == "DOOR_FACE_SUPPORT"

    def test_forward_support_exempts(self):
        """前方有足够搭接邻箱 → 豁免。"""
        cand = _box("D", 1.0, 0, 0, 0.3, 1.0, 1.0)
        front = _box("E", 1.3, 0, 0, 0.5, 1.0, 1.0)
        assert tipping_verdict(cand, [front], 12.0).reason == "FORWARD_SUPPORT"


class TestChainDepthKernel:
    def test_chain_depth_counts_stacked(self):
        pls = [_box("S", 0, 0, 0.0, 1, 1, 0.5),
               _box("S", 0, 0, 0.5, 1, 1, 0.5)]
        assert same_sku_chain_depth("S", 0, 0, 1.0, 1, 1, pls) == 3

    def test_different_sku_not_counted(self):
        pls = [_box("T", 0, 0, 0.0, 1, 1, 0.5)]
        assert same_sku_chain_depth("S", 0, 0, 0.5, 1, 1, pls) == 1


class TestPressureKernel:
    def test_pressure_exceeds_limit(self):
        """20kg / 0.09m² = 222 > 50 → 违规。"""
        cand = _box("HEAVY", 0.3, 0.3, 0.4, 0.3, 0.3, 0.3, w=20.0)
        under = _box("WEAK", 0, 0, 0, 1.0, 1.0, 0.4)
        viol = pressure_violation([under], cand, {"WEAK": 50.0})
        assert viol is not None and viol[1] > 50.0

    def test_pressure_within_limit(self):
        """10kg / 0.25m² = 40 < 50 → 通过。"""
        cand = _box("LIGHT", 0.2, 0.2, 0.4, 0.5, 0.5, 0.3, w=10.0)
        under = _box("WEAK", 0, 0, 0, 1.0, 1.0, 0.4)
        assert pressure_violation([under], cand, {"WEAK": 50.0}) is None

    def test_no_limit_configured_passes(self):
        cand = _box("X", 0.2, 0.2, 0.4, 0.5, 0.5, 0.3, w=100.0)
        under = _box("Y", 0, 0, 0, 1.0, 1.0, 0.4)
        assert pressure_violation([under], cand, {}) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
