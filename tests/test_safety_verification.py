"""独立安全验收测试（用户要求：自写测试、自验证）。

不依赖内部实现细节，从最终放置坐标独立复算安全指标，并与求解器/门禁的
自报结果交叉核对：

1. 显式关闭门端台阶：门面在"开门"工况下 SF<1.5 → DG-020 必须告警（WARN，不阻断）；
2. 实际交付默认（门端台阶开启）：门面 SF≥1.5、DG-020 通过，且不得产生硬违规；
3. 台阶模式不得把弹性件全部锁死（安全例外生效：刚性缺口≤2% 且已证不可放）；
4. `geometry_qa.transport` 的失稳箱数必须与独立复算的 lateral_stable 结果一致；
5. `geometry_qa.door_open.min_sf` 必须与从 placements 独立复算的门面列 SF 一致。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import collections
import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from backend.solver_v2.validation.constraint_kernel import lateral_stable
from backend.solver_v2.validation.delivery_gate import evaluate_delivery

FIXTURE = os.path.join(PROJECT_ROOT, "tests", "fixtures", "production_15sku.json")
TIME_BUDGET = 60.0


def _placements(sol):
    return [
        {"sku_id": p.sku_id, "x": p.position.x, "y": p.position.y, "z": p.position.z,
         "dx": p.orientation.dx, "dy": p.orientation.dy, "dz": p.orientation.dz}
        for p in sol.placements
    ]


def _recompute_face_sf(container, placements):
    """独立复算门面整列 SF：SF = 2·dx / H（H 为同 (x0,y0) 列堆叠总高）。"""
    if not placements:
        return None, 0
    face = max(p["x"] + p["dx"] for p in placements)
    if face < container.Lx - 0.65:
        return None, 0
    cols = collections.defaultdict(lambda: {"h": 0.0, "d": 0.0})
    for p in placements:
        if face - (p["x"] + p["dx"]) > 1e-3:
            continue
        key = (round(p["x"], 3), round(p["y"], 3))
        cols[key]["h"] += p["dz"]
        cols[key]["d"] = max(cols[key]["d"], p["dx"])
    sfs = [(2.0 * e["d"]) / max(e["h"], 1e-6) for e in cols.values()]
    return (min(sfs) if sfs else None), len(sfs)


def _gate_checks(sol, cargo, container):
    rep = evaluate_delivery(sol, cargo, container)
    return rep, {c["id"]: c for c in rep["checks"]}


class TestSafetyVerification:
    @pytest.fixture(scope="class")
    def results(self):
        case = json.load(open(FIXTURE, encoding="utf-8"))
        container = InputAdapter.parse_container(case["container"])
        cargo = InputAdapter.parse_cargo_list(case["cargo"])
        # 实际交付默认（与 server 产品默认一致）：门区限定 + 0.25m 门端台阶
        solver = UnifiedSolver(container)
        delivered = solver.solve(
            cargo,
            options={"door_seal_confine": True, "door_step_depth": 0.25},
            time_budget=TIME_BUDGET,
        )
        door_boundary = getattr(solver, "_door_lockout_x", None)
        # 显式关闭安全策略：用于验证"避免不了必须告警"的兜底
        off = UnifiedSolver(container).solve(
            cargo,
            options={"door_seal_confine": False, "door_step_depth": 0.0},
            time_budget=TIME_BUDGET,
        )
        return container, cargo, delivered, off, door_boundary

    def test_delivered_default_keeps_seal_cargo_at_door(self, results):
        """实际交付默认：所有刚性封柜门件必须落在门区预留段内。"""
        _, _, delivered, _, boundary = results
        assert boundary is not None
        seal = [p for p in delivered.placements if p.sku_id == "SKU-02"]
        assert seal, "封柜门 SKU-02 未装入"
        outside = [p for p in seal if p.position.x + p.orientation.dx < boundary - 1e-6]
        assert not outside, f"{len(outside)} 件封柜门件被放到门区之外"

    def test_delivered_default_is_door_safe(self, results):
        """实际交付默认：门面 SF≥1.5、DG-020 通过、无硬违规、装载率不塌方。"""
        container, cargo, delivered, _, _ = results
        qa = delivered.telemetry.geometry_qa
        assert qa["door_open"]["min_sf"] is not None
        assert qa["door_open"]["min_sf"] >= 1.5, qa["door_open"]
        assert qa["door_open"]["unsafe_columns"] == 0
        assert qa["door_open"]["at_risk_volume_m3"] == pytest.approx(0.0, abs=1e-9)
        rep, checks = _gate_checks(delivered, cargo, container)
        assert checks["DG-020"]["passed"] is True
        assert rep["verdict"] != "REJECT", rep.get("blocked_by")
        assert not delivered.validation_result.violations
        assert delivered.volume_utilization_pct >= 84.0

    def test_disabled_safety_warns_on_door_tipping(self, results):
        """显式关闭安全策略时：门面 SF<1.5，DG-020 必须告警（不阻断交付）。"""
        container, cargo, _, off, _ = results
        qa = off.telemetry.geometry_qa
        assert qa["door_open"]["min_sf"] is not None
        assert qa["door_open"]["min_sf"] < 1.5, qa["door_open"]
        assert qa["door_open"]["unsafe_columns"] > 0
        rep, checks = _gate_checks(off, cargo, container)
        assert checks["DG-020"]["passed"] is False
        assert rep["verdict"] != "REJECT", rep.get("blocked_by")
        assert not off.validation_result.violations

    def test_delivered_default_does_not_lock_all_elastic(self, results):
        """安全策略造成的刚性小缺口不得把弹性件全部锁死。"""
        _, _, delivered, off, _ = results
        delivered_elastic = sum(1 for p in delivered.placements if p.sku_id == "SKU-14")
        assert delivered_elastic > 0, "交付默认把 SKU-14 全部锁死（安全例外未生效）"
        assert delivered.volume_utilization_pct >= off.volume_utilization_pct - 4.0

    def test_transport_audit_matches_independent_recount(self, results):
        """DG-021 的失稳箱数必须等于独立复算 lateral_stable 的结果。"""
        container, _, delivered, off, _ = results
        for sol in (delivered, off):
            pls = _placements(sol)
            independent = sum(
                1 for p in pls if not lateral_stable(p, pls, container.Ly, container.Lx))
            reported = sol.telemetry.geometry_qa["transport"]["unstable_boxes"]
            assert reported == independent, (reported, independent)

    def test_door_face_sf_matches_independent_recount(self, results):
        """几何审计的门面 SF 必须与独立复算一致（口径一致性）。"""
        container, _, delivered, off, _ = results
        for sol in (delivered, off):
            pls = _placements(sol)
            sf, cols = _recompute_face_sf(container, pls)
            reported = sol.telemetry.geometry_qa["door_open"]
            assert reported["column_count"] == cols
            if sf is None:
                assert reported["min_sf"] is None
            else:
                assert reported["min_sf"] == pytest.approx(sf, abs=0.005), (reported, sf)

    def test_gate_door_and_transport_rules_are_warn_not_block(self, results):
        """DG-020/021 是安全提示，不得把可用方案直接判为 REJECT。"""
        container, cargo, delivered, _, _ = results
        rep, checks = _gate_checks(delivered, cargo, container)
        for rid in ("DG-020", "DG-021"):
            assert checks[rid]["severity"] == "WARN"
            assert rid not in (rep.get("blocked_by") or [])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
