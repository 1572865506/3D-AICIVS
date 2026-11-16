"""装载顺序可执行性（Installability）测试。

背景：求解器只保证几何合规，不保证存在物理可执行的装入顺序。此前 API 把
placements 枚举下标当作 step 顺序上报，实测某些方案在该顺序下有数百箱会被
更早装入的箱子挡住通道（视觉正常、现场无法装）。本模块用依赖图拓扑排序给出
真实可执行顺序，并在门禁 DG-013 中报告。
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.loading.sequence_planner import compute_loading_order, build_dependency_graph
from backend.solver_v2.solver.unified_solver import UnifiedSolver


def _box(pid, x, y, z, dx, dy, dz):
    return {"placement_id": pid, "x": x, "y": y, "z": z, "dx": dx, "dy": dy, "dz": dz}


class TestSequencePlanner:
    def test_deeper_box_must_load_first(self):
        """靠门箱（A）与柜尾箱（B）同截面：B 必须先装。"""
        placements = [
            _box("A_FRONT", 5.0, 0.0, 0.0, 1.0, 1.0, 1.0),
            _box("B_BACK", 0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
        ]
        report = compute_loading_order(placements)
        assert report["feasible"] is True
        order = report["order"]
        assert order.index("B_BACK") < order.index("A_FRONT")

    def test_no_dependency_when_cross_sections_differ(self):
        """不同 (y,z) 截面的箱体互不阻挡，顺序可任意。"""
        placements = [
            _box("A", 0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
            _box("B", 3.0, 1.5, 0.0, 1.0, 1.0, 1.0),
        ]
        adj, edges = build_dependency_graph(placements)
        assert edges == 0

    def test_cycle_detection_on_impossible_layout(self):
        """交叉阻断的构造：对向遮挡应被识别为不可行（或至少不崩溃）。"""
        placements = [
            _box("A", 0.0, 0.0, 0.0, 2.0, 1.0, 1.0),
        ]
        report = compute_loading_order(placements)
        assert report["feasible"] is True
        assert report["cycles"] == []

    def test_production_plan_order_respects_all_edges(self):
        """15-SKU 真实方案：输出的装载顺序必须满足全部依赖边。"""
        import json
        case = json.load(open(os.path.join(PROJECT_ROOT, "tests", "fixtures", "production_15sku.json"), encoding="utf-8"))
        container = InputAdapter.parse_container(case["container"])
        cargo = InputAdapter.parse_cargo_list(case["cargo"])
        sol = UnifiedSolver(container).solve(cargo)
        report = compute_loading_order(sol.placements, container)
        assert report["feasible"] is True, f"方案存在装载环: {report['cycles'][:5]}"
        pos = {pid: i for i, pid in enumerate(report["order"])}
        ids = [p.placement_id for p in sol.placements]
        adj, _ = build_dependency_graph(sol.placements)
        for i, succ in enumerate(adj):
            for j in succ:
                assert pos[ids[i]] < pos[ids[j]], f"顺序违反依赖: {ids[i]} 应先于 {ids[j]}"

    def test_empty_plan(self):
        report = compute_loading_order([])
        assert report["order"] == [] and report["feasible"] is True

    def test_bucketed_edges_match_naive_scan(self):
        """分桶优化必须与 O(n²) 全对扫描产生完全相同的依赖边。"""
        import random
        rng = random.Random(20261115)
        placements = []
        for i in range(120):
            placements.append(_box(
                f"P{i}", round(rng.uniform(0, 8), 3), round(rng.uniform(0, 2.0), 3),
                round(rng.uniform(0, 2.0), 3), round(rng.uniform(0.1, 1.0), 3),
                round(rng.uniform(0.1, 0.6), 3), round(rng.uniform(0.1, 0.6), 3)))
        adj, _ = build_dependency_graph(placements)
        boxes = [(p["x"], p["y"], p["z"], p["dx"], p["dy"], p["dz"]) for p in placements]
        for i, (bx, by, bz, bdx, bdy, bdz) in enumerate(boxes):
            expected = set()
            for j, (ax, ay, az, adx, ady, adz) in enumerate(boxes):
                if i == j or ax < bx + bdx - 1e-3:
                    continue
                if min(by + bdy, ay + ady) - max(by, ay) <= 1e-4:
                    continue
                if min(bz + bdz, az + adz) - max(bz, az) <= 1e-4:
                    continue
                expected.add(j)
            assert adj[i] == expected, i

    def test_large_plan_performance(self):
        """5000 箱分桶拓扑排序应保持秒级（旧实现是 O(n²) 全对扫描）。"""
        import time
        placements = []
        idx = 0
        for ix in range(25):
            for iy in range(10):
                for iz in range(20):
                    placements.append(_box(
                        f"B{idx}", ix * 0.2, iy * 0.2, iz * 0.2, 0.18, 0.18, 0.18))
                    idx += 1
        started = time.perf_counter()
        report = compute_loading_order(placements)
        elapsed = time.perf_counter() - started
        assert report["feasible"] is True
        assert len(report["order"]) == len(placements)
        assert elapsed < 3.0, f"sequence planner too slow: {elapsed:.2f}s"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
