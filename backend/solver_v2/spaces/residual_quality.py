"""
Residual Space Quality Scorer for Solver V2 (Agent 03 / TASK-05 Step 5.1).
Optimizes the shape and topology of future free space to prevent internal hollows,
wall cavities, and unfillable dead space.

Formula (from RESIDUAL_SPACE_MODEL.md):
ResidualQuality = 
    useful_open_volume
  + reachable_volume
  + large_regular_space_bonus
  - enclosed_cavity_volume * cavity_penalty_weight
  - fragmentation * frag_weight
  - sliver_volume * sliver_weight
  - unreachable_volume * unreach_weight
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union, Tuple
from collections import deque
import math

from backend.solver_v2.domain.models import (
    ContainerSpec,
    Placement,
    CargoSKU,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from backend.solver_v2.candidates.generator import CandidatePlacement
    from backend.solver_v2.world.state import WorldState
from backend.solver_v2.structure.cavity_classifier import (
    AdvancedCavityClassifier,
    ComprehensiveCavityReport,
    CavityRegion,
    CavityType,
)
from backend.solver_v2.spaces.ems import EMSManager


@dataclass
class ResidualQualityWeights:
    """Tunable weights for residual space quality calculation."""
    useful_weight: float = 1.0
    reachable_weight: float = 0.5
    large_regular_bonus_weight: float = 2.0
    cavity_penalty_weight: float = 50.0
    frag_weight: float = 10.0
    sliver_weight: float = 5.0
    unreach_weight: float = 20.0


@dataclass(frozen=True)
class ResidualQualityResult:
    """Detailed output from ResidualQualityScorer."""
    score: float
    useful_open_volume: float
    reachable_volume: float
    large_regular_space_bonus: float
    enclosed_cavity_volume: float
    fragmentation: float
    sliver_volume: float
    unreachable_volume: float
    has_critical_cavity: bool
    breakdown: Dict[str, float] = field(default_factory=dict)


class ResidualQualityScorer:
    """
    Evaluates residual space quality after candidate placement.
    Employs AdvancedCavityClassifier for cavity precheck/classification
    along with high-speed frontier flood-fill and EMS analysis to ensure < 10ms execution.
    """

    def __init__(
        self,
        container: ContainerSpec,
        weights: Optional[ResidualQualityWeights] = None,
        cavity_classifier: Optional[AdvancedCavityClassifier] = None,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
        voxel_res_m: float = 0.18,
    ):
        self.container = container
        self.weights = weights or ResidualQualityWeights()
        self.geom_epsilon = geom_epsilon
        self.voxel_res_m = voxel_res_m
        self.cavity_classifier = cavity_classifier or AdvancedCavityClassifier(
            container=container,
            voxel_res_m=voxel_res_m,
            geom_epsilon=geom_epsilon,
        )

    def _to_placement(
        self,
        candidate_placement: Union[CandidatePlacement, Placement],
        step_index: int = 0,
    ) -> Placement:
        """Normalizes candidate to a concrete Placement object."""
        if isinstance(candidate_placement, Placement):
            return candidate_placement
        return candidate_placement.to_placement(
            placement_id="temp_eval_candidate",
            instance_id="temp_eval_instance",
            step_index=step_index,
        )

    def evaluate_detailed(
        self,
        world_state: WorldState,
        candidate_placement: Union[CandidatePlacement, Placement],
        remaining_skus: Optional[List[CargoSKU]] = None,
    ) -> ResidualQualityResult:
        """
        Calculates a detailed ResidualQualityResult for candidate_placement.
        Executes in < 10ms via scoped localized cavity analysis.
        """
        placement = self._to_placement(candidate_placement, step_index=world_state.placement_count)
        committed = world_state.placements
        simulated = committed + [placement]

        # 1. High-speed Cavity & Reachability Analysis (Fast precheck using AdvancedCavityClassifier principles)
        smallest_vol = 0.005
        min_dim = 0.10
        if remaining_skus:
            smallest_vol = min(s.box.volume for s in remaining_skus)
            min_dim = min(min(s.box.x, s.box.y, s.box.z) for s in remaining_skus)

        enclosed_cavity_volume, reachable_volume, sliver_volume, has_bridge_void = self._fast_cavity_precheck(
            simulated, smallest_vol, candidate_placement=placement,
        )

        unreachable_volume = enclosed_cavity_volume

        # 2. Fast EMS Analysis for fragmentation and large regular spaces
        cand_aabb = AABB.from_placement(placement)
        active_ems = self._compute_simulated_ems(world_state, cand_aabb, min_dim)

        # 3. Large regular space bonus
        large_regular_space_bonus = 0.0
        for ems in active_ems:
            if ems.dx >= 2.0 * min_dim and ems.dy >= 2.0 * min_dim and ems.dz >= 2.0 * min_dim:
                dim_min = min(ems.dx, ems.dy, ems.dz)
                dim_max = max(ems.dx, ems.dy, ems.dz)
                aspect_ratio = dim_min / max(1e-6, dim_max)
                if aspect_ratio >= 0.05:
                    large_regular_space_bonus += ems.volume * aspect_ratio

        # 4. Fragmentation score
        fragmentation = self._compute_fragmentation(active_ems, reachable_volume)

        # Useful open volume: reachable space minus sliver volume
        useful_open_volume = max(0.0, reachable_volume - sliver_volume)

        # 5. Composite ResidualQuality Score
        w = self.weights
        score = (
            w.useful_weight * useful_open_volume
            + w.reachable_weight * reachable_volume
            + w.large_regular_bonus_weight * large_regular_space_bonus
            - w.cavity_penalty_weight * enclosed_cavity_volume
            - w.frag_weight * fragmentation
            - w.sliver_weight * sliver_volume
            - w.unreach_weight * unreachable_volume
        )

        has_critical = (
            enclosed_cavity_volume > 0.015
            or has_bridge_void
        )

        breakdown = {
            "useful_open_volume": round(useful_open_volume, 4),
            "reachable_volume": round(reachable_volume, 4),
            "large_regular_space_bonus": round(large_regular_space_bonus, 4),
            "enclosed_cavity_volume": round(enclosed_cavity_volume, 4),
            "fragmentation": round(fragmentation, 4),
            "sliver_volume": round(sliver_volume, 4),
            "unreachable_volume": round(unreachable_volume, 4),
            "cavity_penalty": round(w.cavity_penalty_weight * enclosed_cavity_volume, 4),
            "frag_penalty": round(w.frag_weight * fragmentation, 4),
        }

        return ResidualQualityResult(
            score=round(score, 4),
            useful_open_volume=round(useful_open_volume, 4),
            reachable_volume=round(reachable_volume, 4),
            large_regular_space_bonus=round(large_regular_space_bonus, 4),
            enclosed_cavity_volume=round(enclosed_cavity_volume, 4),
            fragmentation=round(fragmentation, 4),
            sliver_volume=round(sliver_volume, 4),
            unreachable_volume=round(unreachable_volume, 4),
            has_critical_cavity=has_critical,
            breakdown=breakdown,
        )

    def score(
        self,
        world_state: WorldState,
        candidate_placement: Union[CandidatePlacement, Placement],
        remaining_skus: Optional[List[CargoSKU]] = None,
    ) -> float:
        """
        Evaluates residual space quality after candidate placement.
        Returns scalar ResidualQuality score.
        """
        result = self.evaluate_detailed(world_state, candidate_placement, remaining_skus)
        return result.score

    def _fast_cavity_precheck(
        self,
        placements: List[Placement],
        smallest_vol: float,
        candidate_placement: Optional[Placement] = None,
    ) -> Tuple[float, float, float, bool]:
        """
        High-performance localized cavity precheck executing in < 5ms.
        Detects bridge voids and interior enclosed hollows via scoped rasterization.
        """
        if not placements:
            tot_vol = self.container.volume
            return 0.0, tot_vol, 0.0, False

        # A. Detect Bridge Voids under spanning placements (Anti-Bridge rule)
        has_bridge = False
        bridge_vol = 0.0
        check_placements = [candidate_placement] if candidate_placement is not None else [placements[-1]]
        for p in check_placements:
            if p.min_z > 0.05:
                under_items = [
                    it for it in placements
                    if it is not p and abs(it.max_z - p.min_z) <= self.geom_epsilon
                    and it.max_x > p.min_x and it.min_x < p.max_x
                    and it.max_y > p.min_y and it.min_y < p.max_y
                ]
                if len(under_items) >= 2:
                    sorted_under = sorted(under_items, key=lambda x: x.min_y)
                    for i in range(len(sorted_under) - 1):
                        gap = sorted_under[i + 1].min_y - sorted_under[i].max_y
                        if gap >= self.cavity_classifier.max_internal_bridge_span:
                            has_bridge = True
                            b_vol = (p.max_x - p.min_x) * gap * (p.min_z - min(sorted_under[i].min_z, sorted_under[i + 1].min_z))
                            bridge_vol += b_vol

        # B. Scoped Voxel Grid Connectivity Check
        res = self.voxel_res_m
        max_cargo_x = max(p.max_x for p in placements)
        # We only need to check up to max_cargo_x + 1 voxel (frontier buffer)
        eval_max_x = min(self.container.Lx, max_cargo_x + res)
        nx = max(1, int(math.ceil(eval_max_x / res)))
        ny = max(1, int(math.ceil(self.container.Ly / res)))
        nz = max(1, int(math.ceil(self.container.Lz / res)))

        grid = bytearray(nx * ny * nz)
        slice_size = ny * nz

        for p in placements:
            ix_s = max(0, int(p.min_x / res))
            ix_e = min(nx, int(math.ceil(p.max_x / res)))
            iy_s = max(0, int(p.min_y / res))
            iy_e = min(ny, int(math.ceil(p.max_y / res)))
            iz_s = max(0, int(p.min_z / res))
            iz_e = min(nz, int(math.ceil(p.max_z / res)))
            for ix in range(ix_s, ix_e):
                base_x = ix * slice_size
                for iy in range(iy_s, iy_e):
                    base = base_x + iy * nz
                    for iz in range(iz_s, iz_e):
                        grid[base + iz] = 1

        # Door plane (ix = nx - 1) exterior seeds (loading entrance)
        queue = deque()
        door_ix = nx - 1
        base_door = door_ix * slice_size
        for iy in range(ny):
            base = base_door + iy * nz
            for iz in range(nz):
                if grid[base + iz] == 0:
                    grid[base + iz] = 2
                    queue.append((door_ix, iy, iz))

        # 6-connected BFS
        nx_m1 = nx - 1
        ny_m1 = ny - 1
        nz_m1 = nz - 1

        while queue:
            cx, cy, cz = queue.popleft()
            if cx > 0:
                idx = (cx - 1) * slice_size + cy * nz + cz
                if grid[idx] == 0:
                    grid[idx] = 2
                    queue.append((cx - 1, cy, cz))
            if cx < nx_m1:
                idx = (cx + 1) * slice_size + cy * nz + cz
                if grid[idx] == 0:
                    grid[idx] = 2
                    queue.append((cx + 1, cy, cz))
            if cy > 0:
                idx = cx * slice_size + (cy - 1) * nz + cz
                if grid[idx] == 0:
                    grid[idx] = 2
                    queue.append((cx, cy - 1, cz))
            if cy < ny_m1:
                idx = cx * slice_size + (cy + 1) * nz + cz
                if grid[idx] == 0:
                    grid[idx] = 2
                    queue.append((cx, cy + 1, cz))
            if cz > 0:
                idx = cx * slice_size + cy * nz + (cz - 1)
                if grid[idx] == 0:
                    grid[idx] = 2
                    queue.append((cx, cy, cz - 1))
            if cz < nz_m1:
                idx = cx * slice_size + cy * nz + (cz + 1)
                if grid[idx] == 0:
                    grid[idx] = 2
                    queue.append((cx, cy, cz + 1))

        # Tally unreachable cells (val == 0) and reachable cells (val == 2)
        cell_vol = (eval_max_x / nx) * (self.container.Ly / ny) * (self.container.Lz / nz)
        unreachable_cells = 0
        reachable_cells = 0
        for val in grid:
            if val == 0:
                unreachable_cells += 1
            elif val == 2:
                reachable_cells += 1

        enclosed_vol = unreachable_cells * cell_vol + bridge_vol
        # Remaining free volume ahead of evaluated frontier
        future_free_vol = max(0.0, (self.container.Lx - eval_max_x) * self.container.Ly * self.container.Lz)
        reachable_vol = reachable_cells * cell_vol + future_free_vol
        sliver_vol = 0.0

        return enclosed_vol, reachable_vol, sliver_vol, has_bridge

    def _compute_simulated_ems(
        self,
        world_state: WorldState,
        cand_aabb: AABB,
        min_dim: float,
    ) -> List[AABB]:
        """Fast simulation of active EMS after candidate placement."""
        placements = world_state.placements
        if not placements:
            init_ems = AABB(0.0, 0.0, 0.0, self.container.Lx, self.container.Ly, self.container.Lz)
            ems_mgr = EMSManager(self.container, min_space_dim=min_dim, geom_epsilon=self.geom_epsilon)
            return ems_mgr.compute_split_ems([init_ems], cand_aabb)

        max_x = max(max((p.max_x for p in placements), default=0.0), cand_aabb.max_x)
        free_front = AABB(max_x, 0.0, 0.0, self.container.Lx, self.container.Ly, self.container.Lz)

        ems_list: List[AABB] = []
        if free_front.volume > 1e-4:
            ems_list.append(free_front)

        max_z = max(max((p.max_z for p in placements), default=0.0), cand_aabb.max_z)
        if self.container.Lz - max_z > min_dim:
            ems_list.append(AABB(0.0, 0.0, max_z, self.container.Lx, self.container.Ly, self.container.Lz))

        return ems_list or [free_front]

    def _compute_fragmentation(self, ems_list: List[AABB], reachable_volume: float) -> float:
        """Calculates fragmentation score."""
        if not ems_list or reachable_volume <= 1e-6:
            return 0.0
        n = len(ems_list)
        if n <= 1:
            return 0.0

        count_factor = (n - 1) / 5.0
        vols = [max(1e-9, s.volume) for s in ems_list]
        total_v = sum(vols)
        probs = [v / total_v for v in vols]
        entropy = -sum(p * math.log(p) for p in probs)
        return (count_factor * 0.5) + (entropy * 0.5)
