"""
Solver V2 Package Root
Clean-room implementation of 3D-AICIVS Container Loading Engine.
"""
from typing import List, Optional, Any, Dict
from backend.solver_v2.domain.models import ContainerSpec, CargoSKU
from backend.solver_v2.solver.baseline_solver import SolverSolution
from backend.solver_v2.solver.unified_solver import UnifiedSolver

__version__ = "2.0.0-dev"


def solve(
    container: ContainerSpec,
    cargo_list: List[CargoSKU],
    options: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> SolverSolution:
    """
    Main entry point for Solver V2.
    Executes 3D packing solver using the UnifiedSolver engine.
    """
    merged_options = dict(options or {})
    merged_options.update(kwargs)
    solver = UnifiedSolver(container)
    return solver.solve(cargo_list, options=merged_options)


__all__ = [
    "solve",
    "UnifiedSolver",
]
