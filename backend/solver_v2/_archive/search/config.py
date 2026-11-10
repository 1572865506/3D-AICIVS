"""
Search configuration and profile specifications for Solver V2 (Agent 09).
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Dict, Any, List


class SearchProfile(str, Enum):
    """Preset search performance profiles matching docs/SEARCH_STRATEGY.md."""
    FAST = "FAST"
    BALANCED = "BALANCED"
    OPTIMIZE = "OPTIMIZE"
    CUSTOM = "CUSTOM"


@dataclass
class SearchConfig:
    """
    Configuration parameters for HierarchicalSearchSolver.
    """
    profile: SearchProfile = SearchProfile.BALANCED
    time_budget_sec: float = 30.0
    beam_width: int = 3
    multi_start_runs: int = 3
    max_backtrack_depth: int = 3
    enable_local_search: bool = True
    enable_pattern_aggregation: bool = True
    max_candidates_per_step: int = 200
    grid_resolution: float = 0.15
    seed: int = 42
    wall_stall_threshold: int = 5
    # BLK-006A opt-in wall-plan architecture. Legacy remains the default.
    wall_plan_search_mode: str = "LEGACY_GREEDY"
    global_wall_candidates_per_state: int = 12
    global_wall_max_depth: int = 3
    global_runtime_budget_sec: float = 120.0
    global_max_states_generated: int = 96
    global_max_states_expanded: int = 32
    global_beam_diversity_per_key: int = 1
    global_full_topfill_seed_budget: int = 4
    global_incumbent_volume_m3: float = 0.0
    global_incumbent_utilization_pct: float = 0.0
    # BLK-006E opt-in terminal repair.  Kept disabled by default so the
    # production incumbent and all BLK-006A-D baselines remain unchanged.
    terminal_topfill_repair_enabled: bool = False
    terminal_topfill_repair_profile: str = "BALANCED"
    # Callback invoked whenever a strictly better valid solution is found:
    # callback(solution_dict, step_or_run_idx, current_best_score)
    on_improvement_callback: Optional[Callable[[Dict[str, Any], int, float], None]] = None

    @classmethod
    def for_profile(
        cls,
        profile: SearchProfile,
        seed: int = 42,
        on_improvement: Optional[Callable[[Dict[str, Any], int, float], None]] = None,
        **overrides: Any,
    ) -> "SearchConfig":
        """
        Factory method providing tuned defaults for standard profiles.
        """
        if profile == SearchProfile.FAST:
            cfg = cls(
                profile=SearchProfile.FAST,
                time_budget_sec=5.0,
                beam_width=1,
                multi_start_runs=1,
                max_backtrack_depth=1,
                enable_local_search=False,
                enable_pattern_aggregation=True,
                max_candidates_per_step=100,
                grid_resolution=0.20,
                seed=seed,
                on_improvement_callback=on_improvement,
                global_runtime_budget_sec=15.0,
            )
        elif profile == SearchProfile.BALANCED:
            cfg = cls(
                profile=SearchProfile.BALANCED,
                time_budget_sec=30.0,
                beam_width=3,
                multi_start_runs=3,
                max_backtrack_depth=3,
                enable_local_search=True,
                enable_pattern_aggregation=True,
                max_candidates_per_step=200,
                grid_resolution=0.15,
                seed=seed,
                on_improvement_callback=on_improvement,
                global_runtime_budget_sec=45.0,
            )
        elif profile == SearchProfile.OPTIMIZE:
            cfg = cls(
                profile=SearchProfile.OPTIMIZE,
                time_budget_sec=120.0,
                beam_width=6,
                multi_start_runs=6,
                max_backtrack_depth=5,
                enable_local_search=True,
                enable_pattern_aggregation=True,
                max_candidates_per_step=350,
                grid_resolution=0.10,
                seed=seed,
                on_improvement_callback=on_improvement,
                global_runtime_budget_sec=90.0,
            )
        else:
            cfg = cls(
                profile=SearchProfile.CUSTOM,
                seed=seed,
                on_improvement_callback=on_improvement,
            )

        for k, v in overrides.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg
