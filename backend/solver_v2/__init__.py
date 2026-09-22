"""
Solver V2 Package Root
Clean-room implementation of 3D-AICIVS Container Loading Engine.
"""
from typing import List, Optional, Any, Dict
from backend.solver_v2.domain.models import ContainerSpec, CargoSKU
from backend.solver_v2.solver.baseline_solver import SolverSolution
from backend.solver_v2.solver.cpsat_hybrid_solver import CPSATHybridSolver
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from backend.solver_v2.placement_engine import GuidedBeamSearch, SearchConfig

__version__ = "2.0.0-dev"


def solve(
    container: ContainerSpec,
    cargo_list: List[CargoSKU],
    options: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> SolverSolution:
    """
    Main entry point for Solver V2.
    支持新一代深度引导搜索引擎 (engine='guided') 与传统启发式引擎。
    """
    merged_options = dict(options or {})
    merged_options.update(kwargs)

    engine = merged_options.get("engine", "guided")
    if engine in ("guided", "transformer", "beam_search"):
        searcher = GuidedBeamSearch(container)
        return searcher.solve(cargo_list, options=merged_options)

    solver = CPSATHybridSolver(container)
    return solver.solve(cargo_list, options=merged_options)


__all__ = [
    "solve",
    "GuidedBeamSearch",
    "SearchConfig",
    "CPSATHybridSolver",
    "UnifiedSolver",
]
