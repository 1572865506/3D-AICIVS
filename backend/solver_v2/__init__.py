"""
Solver V2 Package Root
Clean-room implementation of 3D-AICIVS Container Loading Engine.

唯一生产入口：UnifiedSolver（含统一前置门禁与交付质检），见 AGENTS.md 5.7。
实验性引擎（guided beam search / CP-SAT hybrid / hierarchical search /
physics_kernel）已归档至 backend/solver_v2/_archive/，不再对外暴露。
"""
from typing import List, Optional, Any, Dict
from backend.solver_v2.domain.models import ContainerSpec, CargoSKU
from backend.solver_v2.solver.baseline_solver import SolverSolution
from backend.solver_v2.solver.unified_solver import UnifiedSolver

__version__ = "2.1.0"


def solve(
    container: ContainerSpec,
    cargo_list: List[CargoSKU],
    options: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> SolverSolution:
    """
    统一求解入口。

    仅保留单一生产引擎（UnifiedSolver）。历史 `engine='guided'|'cpsat'` 参数
    不再生效——如需实验引擎请直接引用 backend/solver_v2/_archive/ 下的模块，
    但禁止在 server/API 请求路径使用（AGENTS.md 5.7）。
    """
    merged_options = dict(options or {})
    merged_options.update(kwargs)
    solver = UnifiedSolver(container)
    return solver.solve(cargo_list, options=merged_options)


__all__ = ["solve", "UnifiedSolver", "SolverSolution"]
