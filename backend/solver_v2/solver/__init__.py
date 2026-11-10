"""
Solver V2 Solver Package.

生产路径：UnifiedSolver + 统一前置门禁（见 AGENTS.md 5.7「唯一生产路径」）。
已归档到 backend/solver_v2/_archive/ 的模块（gap_filler / elastic_recovery /
swap_optimizer / lns_optimizer / constructive_placer / cpsat_* ）不再导出。
"""
from backend.solver_v2.solver.scorer import CandidateScorer
from backend.solver_v2.solver.baseline_solver import (
    BaselineGreedySolver,
    SolverTelemetry,
    SolverSolution,
)
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from backend.solver_v2.solver.composite_strip import (
    CompositeStripBuilder,
    CompositeStripResult,
    SubColumnConfig,
)
from backend.solver_v2.solver.compaction import (
    CompactionPass,
    CompactionResult,
)

__all__ = [
    "CandidateScorer",
    "BaselineGreedySolver",
    "SolverTelemetry",
    "SolverSolution",
    "UnifiedSolver",
    "CompositeStripBuilder",
    "CompositeStripResult",
    "SubColumnConfig",
    "CompactionPass",
    "CompactionResult",
]
