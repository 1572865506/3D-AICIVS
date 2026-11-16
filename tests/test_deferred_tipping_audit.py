"""Phase B：低稳定纸箱的同图案前向支撑墙 + 提交前审计。

覆盖：
1. 图案引擎对风险前排追加稳定支撑列；无支撑时丢弃风险图案；
2. 门禁默认仍拒绝无支撑 CUBE，只有 allow_deferred 才挂 SUSPECT；
3. 支撑列真实接触通过、偏移失败；
4. CUBE 高密度虚拟单端到端 202/202、0 违规、审计统计闭环；
5. 产品层只对无刚性封门件货单默认开启。
"""

import collections
import json
import os
import sys
from types import SimpleNamespace

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.evaluation.product import build_product_options
from backend.solver_v2.solver.composite_strip import WidthPatternEngine
from backend.solver_v2.solver.unified_solver import UnifiedSolver

CUBE_CASE = os.path.join(
    PROJECT_ROOT, "tests", "cases", "virtual",
    "virtual_nodoor_highfill_40hq.json")
PRODUCTION_15SKU = os.path.join(
    PROJECT_ROOT, "tests", "fixtures", "production_15sku.json")


def _load_case(path):
    case = json.load(open(path, encoding="utf-8"))
    container = InputAdapter.parse_container(case["container"])
    cargo = InputAdapter.parse_cargo_list(case["cargo"])
    return container, cargo


def _risk_variant(v):
    return v.dz > 1e-6 and (2.0 * v.dx) / v.dz < 1.5 - 1e-4


def _cube_engine_and_variants():
    container, cargo = _load_case(CUBE_CASE)
    engine = WidthPatternEngine(
        container_width=container.Ly,
        container_height=container.Lz,
        container_length=container.Lx,
    )
    remaining = {c.sku_id: c.quantity.required for c in cargo}
    variants = engine.extract_orientation_variants(
        cargo, remaining, max_depth_limit=1.2)
    support = [
        v for v in variants
        if v.is_upright and (2.0 * v.dx) / v.dz >= 1.5 - 1e-4
    ]
    return engine, variants, support, remaining, container


class TestSupportedPatterns:
    def test_cube_risky_core_gets_forward_support_column(self):
        engine, variants, support, remaining, container = _cube_engine_and_variants()
        patterns = engine.generate_patterns(
            variants, remaining, available_x=10.8,
            target_width=container.Ly, support_variants=support)

        supported = [p for p in patterns if p.support_depth > 0]
        assert supported, "CUBE 风险图案没有生成支撑列"
        assert any("V02-CUBE_BOX" in p.sku_counts for p in supported)

        for pat in patterns:
            risky_cols = [c for c in pat.columns if _risk_variant(c.variant)]
            if not risky_cols:
                continue
            # 不允许裸风险图案进入候选池
            assert pat.support_depth > 0, pat.pattern_id
            assert pat.support_sku_id, pat.pattern_id
            cap_cols = [c for c in pat.columns if c.x_offset > 1e-6]
            assert len(cap_cols) == 1, pat.pattern_id
            cap = cap_cols[0]
            assert cap.x_offset == pytest.approx(pat.support_depth, abs=1e-4)
            assert cap.col_depth > 1e-6
            assert cap.total_cartons > 0
            assert pat.flush_depth == pytest.approx(
                pat.support_depth + cap.col_depth, abs=1e-4)
            # 风险列必须在支撑墙前表面 3cm 容差内，否则支撑贴不到
            for col in risky_cols:
                assert pat.support_depth - col.col_depth <= 0.03 + 1e-6

    def test_risky_patterns_dropped_without_support_pool(self):
        engine, variants, _, remaining, container = _cube_engine_and_variants()
        patterns = engine.generate_patterns(
            variants, remaining, available_x=10.8,
            target_width=container.Ly, support_variants=[])
        for pat in patterns:
            assert not any(_risk_variant(c.variant) for c in pat.columns), pat.pattern_id


class TestDeferredGate:
    def _solver(self, deferred=True, door_ids=None):
        s = UnifiedSolver.__new__(UnifiedSolver)
        s.cL = 12.032
        s.cW = 2.352
        s._door_step_depth = 0.0
        s._door_open_stability = False
        s._door_sku_ids = set(door_ids or ())
        s._deferred_tipping_audit = deferred
        s._current_rejection_counts = {}
        s._spatial_idx = None
        s._tipping_audit_stats = {
            "suspects": 0, "verified": 0,
            "support_patterns": 0, "rollbacks": 0,
        }
        return s

    @staticmethod
    def _cube(x=5.0, sku="V02-CUBE_BOX"):
        return {
            "sku_id": sku, "x": x, "y": 0.0, "z": 0.0,
            "dx": 0.378, "dy": 0.377, "dz": 0.536,
            "weight_kg": 8.4,
        }

    def test_default_gate_still_rejects_unbraced_cube(self):
        s = self._solver()
        assert s._is_placement_tipping_safe(self._cube(), []) is False

    def test_deferred_gate_is_separate_from_stability_gate(self):
        s = self._solver()
        cand = self._cube()
        # 稳定性门禁语义不变；延迟放行是 PASS1 图案站点的独立判定
        assert s._is_placement_tipping_safe(cand, []) is False
        assert s._can_defer_pattern_tipping(cand) is True

    def test_door_cargo_never_deferred(self):
        s = self._solver(door_ids={"D"})
        assert s._can_defer_pattern_tipping(self._cube(sku="D")) is False

    def test_door_step_band_never_deferred(self):
        s = self._solver()
        s._door_step_depth = 0.25
        assert s._can_defer_pattern_tipping(self._cube(x=11.60)) is False


class TestSupportAudit:
    @staticmethod
    def _solver():
        s = UnifiedSolver.__new__(UnifiedSolver)
        s.cL = 12.032
        s._tipping_audit_stats = {
            "suspects": 0, "verified": 0,
            "support_patterns": 0, "rollbacks": 0,
        }
        return s

    @staticmethod
    def _suspect():
        return {
            "sku_id": "V02-CUBE_BOX", "x": 5.0, "y": 0.0, "z": 0.0,
            "dx": 0.378, "dy": 0.377, "dz": 0.536,
            "weight_kg": 8.4, "tipping_status": "SUSPECT_UNLOCKED",
        }

    @staticmethod
    def _cap(x=5.378, y=0.0):
        return {
            "sku_id": "V04-MICRO_CUBE", "x": x, "y": y, "z": 0.0,
            "dx": 0.165, "dy": 0.186, "dz": 0.152,
            "weight_kg": 1.91, "tag": "SUPPORT_WALL",
        }

    def test_forward_support_verifies_all_suspects(self):
        s = self._solver()
        suspect = self._suspect()
        cap = self._cap()
        pat = SimpleNamespace(support_depth=0.378)
        assert s._audit_supported_pattern(pat, [suspect, cap], 0, 5.0) is True
        assert suspect["tipping_status"] == "VERIFIED_SAFE"
        assert s._tipping_audit_stats == {
            "suspects": 1, "verified": 1,
            "support_patterns": 0, "rollbacks": 0,
        }

    def test_offset_support_fails_and_counts_rollback(self):
        s = self._solver()
        suspect = self._suspect()
        cap = self._cap(y=2.0)  # Y 完全错开，无 20% 搭接
        pat = SimpleNamespace(support_depth=0.378)
        assert s._audit_supported_pattern(pat, [suspect, cap], 0, 5.0) is False
        assert suspect["tipping_status"] == "SUSPECT_UNLOCKED"
        assert s._tipping_audit_stats["rollbacks"] == 1
        assert s._tipping_audit_stats["verified"] == 0


class TestCubeEndToEnd:
    def test_highfill_cube_202_and_no_violations(self):
        container, cargo = _load_case(CUBE_CASE)
        sol = UnifiedSolver(container).solve(
            cargo, time_budget=45,
            options={"deferred_tipping_audit": True})
        by_sku = collections.Counter(p.sku_id for p in sol.placements)
        assert by_sku["V02-CUBE_BOX"] == 202
        assert sol.placed_count == 1518
        assert not sol.validation_result.violations
        assert int(getattr(sol.validation_result, "overlap_pair_count", 0) or 0) == 0
        assert sol.volume_utilization_pct >= 63.75

        audit = sol.telemetry.tipping_audit or {}
        assert audit["support_patterns"] >= 1
        assert audit["suspects"] > 0
        assert audit["verified"] == audit["suspects"]
        assert audit["rollbacks"] == 0


class TestProductDefault:
    def test_no_door_manifest_defaults_on(self):
        _, cargo = _load_case(CUBE_CASE)
        assert build_product_options(cargo)["deferred_tipping_audit"] is True

    def test_rigid_door_manifest_defaults_off_and_payload_can_override(self):
        _, cargo = _load_case(PRODUCTION_15SKU)
        assert build_product_options(cargo)["deferred_tipping_audit"] is False
        assert build_product_options(
            cargo, payload={"deferredTippingAudit": True}
        )["deferred_tipping_audit"] is True
        assert build_product_options(
            cargo, payload={"deferredTippingAudit": False}
        )["deferred_tipping_audit"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
