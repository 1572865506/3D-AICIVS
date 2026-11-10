"""唯一生产路径守卫测试（AGENTS.md 5.7）。

防止再次出现"多套引擎并行、规则覆盖不一致"：
1. server.py 不得导入/构造除 UnifiedSolver 以外的求解器；
2. 生产放置站点必须走统一门禁；
3. 遗留求解器产物不得被 API 直接使用（以 import 图断言）。
"""
import os
import re

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SERVER = os.path.join(PROJECT_ROOT, "backend", "server.py")
SOLVER = os.path.join(PROJECT_ROOT, "backend", "solver_v2", "solver", "unified_solver.py")


def _src(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestProductionPathGuard:
    def test_server_uses_only_unified_solver(self):
        src = _src(SERVER)
        banned = ["CPSATHybridSolver", "HierarchicalSearchSolver", "GuidedBeamSearch",
                  "BaselineGreedySolver", "LNSOptimizer"]
        found = [b for b in banned if b in src]
        assert not found, f"server.py 引入了非生产求解器: {found}"
        assert "UnifiedSolver" in src, "server.py 必须使用 UnifiedSolver"

    def test_all_placement_sites_share_unified_gate(self):
        src = _src(SOLVER)
        raw_tipping = len(re.findall(r"self\._is_placement_tipping_safe\(", src))
        gate_calls = len(re.findall(r"self\._check_candidate_validity_with_reason\(", src))
        # 收敛后：门禁内部 1 处 + PASS1 倾覆捷径 1 处 = 2
        assert raw_tipping <= 2, f"仍有 {raw_tipping} 处绕过统一门禁的倾覆检查"
        assert gate_calls >= 10, f"统一门禁调用点仅 {gate_calls} 处"

    def test_legacy_modules_marked_non_production(self):
        # 仍在生产目录内但非生产路径的模块：必须带标记
        in_tree = [
            "solver/baseline_solver.py",
            "solver/compaction.py",
        ]
        for rel in in_tree:
            src = _src(os.path.join(PROJECT_ROOT, "backend", "solver_v2", rel))
            assert "非生产路径" in src, f"{rel} 缺少非生产路径标记"

    def test_archived_modules_live_outside_production_tree(self):
        """已归档的模块不得留在生产目录，且归档区有说明文档。"""
        archive = os.path.join(PROJECT_ROOT, "backend", "solver_v2", "_archive")
        for rel in ("search", "physics_kernel", "placement_engine",
                    "cpsat_hybrid_solver.py", "lns_optimizer.py", "gap_filler.py"):
            assert os.path.exists(os.path.join(archive, rel)), f"_archive 缺少 {rel}"
        prod = os.path.join(PROJECT_ROOT, "backend", "solver_v2")
        for rel in ("search", "physics_kernel", "placement_engine"):
            assert not os.path.exists(os.path.join(prod, rel)), f"生产目录仍存在 {rel}"
        assert os.path.exists(os.path.join(archive, "README.md")), "归档区缺少 README 说明"
