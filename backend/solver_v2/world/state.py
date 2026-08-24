"""
Authoritative WorldState Engine for Solver V2.
WorldState is the SINGLE source of truth for 3D container space and placement execution.

Core Invariants:
1. Candidate -> Bounds Check -> Collision Check -> Commit
2. Hard zero-tolerance: any penetration > epsilon is rejected immediately. Never use penalty.
3. Atomic commit and exact rollback.
4. Spatial index always remains in sync with the committed placement store.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Set
import copy
import math

from backend.solver_v2.domain.models import (
    ContainerSpec,
    CargoSKU,
    Placement,
    Point3D,
    Orientation3D,
    PlacementContext,
)
from backend.solver_v2.geometry.aabb import (
    AABB,
    ContactType,
    DEFAULT_GEOM_EPSILON,
)
from backend.solver_v2.geometry.spatial_index import SpatialIndex, SpatialItem
from backend.solver_v2.geometry.overlap import OverlapDetector, OverlapReport
from backend.solver_v2.physics.contact_graph import ContactGraph
from backend.solver_v2.physics.support_graph import SupportGraph
from backend.solver_v2.stability.debt import StabilityDebtTracker


class GeometricIntegrityError(Exception):
    """Raised when a candidate placement violates bounds or penetrates existing cargo."""
    pass


@dataclass(frozen=True)
class StateDelta:
    """
    Tracks state modifications introduced by a single committed Placement.
    Used for exact, atomic rollback.
    """
    placement: Placement
    step_index: int
    prev_remaining_qty: int
    prev_total_weight_kg: float
    prev_center_of_mass: Point3D


class WorldState:
    """
    Authoritative spatial and container world state for Solver V2.
    """

    def __init__(
        self,
        container: ContainerSpec,
        cargo_catalog: Optional[List[CargoSKU]] = None,
        spatial_cell_size: float = 0.5,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container: ContainerSpec = container
        self.geom_epsilon: float = geom_epsilon
        self.spatial_index: SpatialIndex = SpatialIndex(cell_size=spatial_cell_size)

        # Committed placements store
        self._placements: List[Placement] = []
        self._placement_map: Dict[str, Placement] = {}

        # SKU quantity tracking
        self._cargo_catalog: Dict[str, CargoSKU] = {c.sku_id: c for c in (cargo_catalog or [])}
        self._remaining_quantity: Dict[str, int] = {
            c.sku_id: c.quantity.required for c in (cargo_catalog or [])
        }

        # Physical metrics
        self._total_weight_kg: float = 0.0
        self._weighted_com_x: float = 0.0
        self._weighted_com_y: float = 0.0
        self._weighted_com_z: float = 0.0

        # Step and history stack for atomic rollback
        self._step_counter: int = 0
        self._history_stack: List[StateDelta] = []

        # Physical Graphs & Stability Trackers (Agent 07)
        self.contact_graph: ContactGraph = ContactGraph(container=container, geom_epsilon=geom_epsilon)
        self.support_graph: SupportGraph = SupportGraph(container=container, geom_epsilon=geom_epsilon)
        self.stability_debt: StabilityDebtTracker = StabilityDebtTracker()

        # Wall Structure & Cavity Analyzers (BLK-003)
        from backend.solver_v2.structure.wall_model import WallStructureAnalyzer, WallState
        from backend.solver_v2.structure.cavity_classifier import AdvancedCavityClassifier, ComprehensiveCavityReport
        self.wall_analyzer = WallStructureAnalyzer(container=container, geom_epsilon=geom_epsilon)
        self.cavity_classifier = AdvancedCavityClassifier(container=container, geom_epsilon=geom_epsilon)
        self._cached_walls: Optional[List[WallState]] = None
        self._cached_cavity_report: Optional[ComprehensiveCavityReport] = None

    @property
    def placements(self) -> List[Placement]:
        """Returns read-only copy of committed placements."""
        return list(self._placements)

    @property
    def placement_count(self) -> int:
        return len(self._placements)

    @property
    def max_x(self) -> float:
        return max([p.max_x for p in self._placements], default=0.0)

    @property
    def max_y(self) -> float:
        return max([p.max_y for p in self._placements], default=0.0)

    @property
    def max_z(self) -> float:
        return max([p.max_z for p in self._placements], default=0.0)

    @property
    def total_weight_kg(self) -> float:
        return self._total_weight_kg

    @property
    def center_of_mass(self) -> Point3D:
        if self._total_weight_kg <= 1e-9:
            return Point3D(0.0, 0.0, 0.0)
        return Point3D(
            x=self._weighted_com_x / self._total_weight_kg,
            y=self._weighted_com_y / self._total_weight_kg,
            z=self._weighted_com_z / self._total_weight_kg,
        )

    @property
    def remaining_quantities(self) -> Dict[str, int]:
        return dict(self._remaining_quantity)

    def get_remaining_quantity(self, sku_id: str) -> int:
        return self._remaining_quantity.get(sku_id, 0)

    def get_placement(self, placement_id: str) -> Optional[Placement]:
        return self._placement_map.get(placement_id)

    def can_commit(self, candidate: Placement) -> Tuple[bool, Optional[str]]:
        """
        Executes strict candidate validation:
        1. Bounds Check: candidate AABB within container.
        2. Collision Check: candidate AABB does not penetrate any committed item.

        Returns (is_valid, rejection_reason).
        """
        cand_aabb = AABB.from_placement(candidate)

        # 1. Bounds Check
        if not cand_aabb.is_within_bounds(
            self.container.Lx,
            self.container.Ly,
            self.container.Lz,
            eps=self.geom_epsilon
        ):
            return False, (
                f"Bounds violation: Placement {candidate.placement_id} of SKU {candidate.sku_id} "
                f"at min=({cand_aabb.min_x:.4f}, {cand_aabb.min_y:.4f}, {cand_aabb.min_z:.4f}), "
                f"max=({cand_aabb.max_x:.4f}, {cand_aabb.max_y:.4f}, {cand_aabb.max_z:.4f}) "
                f"exceeds container bounds ({self.container.Lx:.4f}, {self.container.Ly:.4f}, {self.container.Lz:.4f})"
            )

        # 2. Collision Check via Spatial Index
        colliding_items = self.spatial_index.query_intersect(cand_aabb, eps=self.geom_epsilon)
        if colliding_items:
            culprits = [
                f"{item.item_id} (pen_vol={cand_aabb.penetration_volume(item.aabb, eps=self.geom_epsilon):.6e}m^3)"
                for item in colliding_items
            ]
            return False, (
                f"Collision violation: Placement {candidate.placement_id} of SKU {candidate.sku_id} "
                f"penetrates committed items: {', '.join(culprits)}"
            )

        # 3. Payload Capacity Check
        if self._total_weight_kg + candidate.weight_kg > self.container.max_payload_kg + self.geom_epsilon:
            return False, (
                f"Payload capacity violation: total weight {self._total_weight_kg + candidate.weight_kg:.2f}kg "
                f"exceeds max payload {self.container.max_payload_kg:.2f}kg"
            )

        return True, None

    def commit(self, placement: Placement) -> StateDelta:
        """
        Atomically commits a placement into WorldState.
        Strictly rejects any placement violating geometry or bounds.
        """
        is_valid, reason = self.can_commit(placement)
        if not is_valid:
            raise GeometricIntegrityError(f"Cannot commit placement {placement.placement_id}: {reason}")

        if placement.placement_id in self._placement_map:
            raise ValueError(f"Placement ID {placement.placement_id} already committed in WorldState.")

        # Record delta for rollback
        sku_id = placement.sku_id
        prev_qty = self._remaining_quantity.get(sku_id, 0)
        delta = StateDelta(
            placement=placement,
            step_index=self._step_counter,
            prev_remaining_qty=prev_qty,
            prev_total_weight_kg=self._total_weight_kg,
            prev_center_of_mass=self.center_of_mass,
        )

        try:
            # 1. Update committed placement lists
            self._placements.append(placement)
            self._placement_map[placement.placement_id] = placement

            # 2. Insert into Spatial Index
            cand_aabb = AABB.from_placement(placement)
            self.spatial_index.insert(
                item_id=placement.placement_id,
                aabb=cand_aabb,
                data=placement,
            )

            # 3. Update ContactGraph and SupportGraph (Agent 07). The spatial
            # hash is a broad phase only: exact graph narrow-phase semantics
            # remain unchanged, but distant historical placements are not
            # rescanned for a wall appended at the active X frontier.
            nearby = [
                item.data for item, _ in self.spatial_index.query_touching(cand_aabb, eps=self.geom_epsilon)
                if item.item_id != placement.placement_id and item.data is not None
            ]
            self.contact_graph.add_placement(placement, existing_placements=nearby)
            self.support_graph.add_placement(placement, existing_placements=nearby)

            # 4. Update Stability Debt resolutions
            self.stability_debt.on_placement_committed(
                new_placement=placement,
                current_step=self._step_counter,
                support_graph=self.support_graph,
                contact_graph=self.contact_graph,
                cargo_catalog=self._cargo_catalog,
                container=self.container,
            )

            # 5. Update remaining quantity
            if sku_id in self._remaining_quantity:
                self._remaining_quantity[sku_id] = prev_qty - 1

            # 6. Update physical metrics (weight & COM)
            w = placement.weight_kg
            center = cand_aabb.center
            self._total_weight_kg += w
            self._weighted_com_x += w * center.x
            self._weighted_com_y += w * center.y
            self._weighted_com_z += w * center.z

            # 7. Push history & increment step
            self._history_stack.append(delta)
            self._step_counter += 1
            self._cached_walls = None
            self._cached_cavity_report = None

            return delta

        except Exception as e:
            # Revert in case of unexpected internal error
            self._safe_rollback_delta(delta)
            raise e

    def rollback(self, delta: Optional[StateDelta] = None) -> Placement:
        """
        Atomically rolls back the last commit (or specified delta).
        Restores exact spatial index, placement store, quantities, weight, and COM.
        """
        if not self._history_stack:
            raise IndexError("Cannot rollback: commit history stack is empty.")

        target_delta = self._history_stack.pop()
        if delta is not None and target_delta != delta:
            self._history_stack.append(target_delta)
            raise ValueError("Mismatched StateDelta provided to rollback; must rollback in LIFO order.")

        return self._safe_rollback_delta(target_delta)

    def _safe_rollback_delta(self, delta: StateDelta) -> Placement:
        placement = delta.placement
        pid = placement.placement_id

        # 1. Remove from spatial index
        self.spatial_index.remove(pid)

        # 2. Remove from Physical Graphs & revert Stability Debt (Agent 07)
        self.contact_graph.remove_placement(pid)
        self.support_graph.remove_placement(pid)
        self.stability_debt.rollback_last_step()

        # 3. Remove from placement lists
        if pid in self._placement_map:
            del self._placement_map[pid]
        self._placements = [p for p in self._placements if p.placement_id != pid]

        # 4. Restore remaining quantity
        sku_id = placement.sku_id
        self._remaining_quantity[sku_id] = delta.prev_remaining_qty

        # 5. Restore physical metrics
        w = placement.weight_kg
        center = AABB.from_placement(placement).center
        self._total_weight_kg = delta.prev_total_weight_kg
        self._weighted_com_x -= w * center.x
        self._weighted_com_y -= w * center.y
        self._weighted_com_z -= w * center.z

        # 6. Decrement step counter
        self._step_counter = delta.step_index
        self._cached_walls = None
        self._cached_cavity_report = None

        return placement

    def get_walls(self) -> List[Any]:
        """Returns structured WallState list representing physical walls in WorldState."""
        if self._cached_walls is None:
            self._cached_walls = self.wall_analyzer.extract_walls(self._placements)
        return self._cached_walls

    def get_cavity_report(self) -> Any:
        """Returns comprehensive 5-type cavity classification report."""
        if self._cached_cavity_report is None:
            self._cached_cavity_report = self.cavity_classifier.classify_cavities(self._placements)
        return self._cached_cavity_report

    def query_overlaps(self, aabb: AABB) -> List[Placement]:
        """Queries all committed placements that have volumetric penetration with aabb."""
        colliding_items = self.spatial_index.query_intersect(aabb, eps=self.geom_epsilon)
        return [item.data for item in colliding_items if item.data is not None]

    def query_touching(self, aabb: AABB) -> List[Tuple[Placement, ContactType]]:
        """Queries all committed placements that have geometric contact with aabb."""
        touching_items = self.spatial_index.query_touching(aabb, eps=self.geom_epsilon)
        return [(item.data, ctype) for item, ctype in touching_items if item.data is not None]

    def verify_integrity(self) -> OverlapReport:
        """
        Authoritative sanity check:
        1. Verifies that placement count matches spatial index size.
        2. Runs independent full sweep via OverlapDetector.
        3. Asserts zero overlap, zero out-of-bounds, zero penetration.
        """
        if len(self._placements) != len(self.spatial_index):
            raise AssertionError(
                f"Integrity error: placement list len ({len(self._placements)}) != "
                f"spatial index len ({len(self.spatial_index)})"
            )

        if len(self._placements) != len(self._placement_map):
            raise AssertionError(
                f"Integrity error: placement list len ({len(self._placements)}) != "
                f"placement map len ({len(self._placement_map)})"
            )

        report = OverlapDetector.run_independent_sweep(
            self.container,
            self._placements,
            eps=self.geom_epsilon,
        )

        if not report.is_valid:
            raise AssertionError(
                f"WorldState geometric integrity compromised: "
                f"overlap_pairs={report.overlap_pair_count}, "
                f"penetration_vol={report.penetration_volume:.6e}, "
                f"out_of_bounds={report.out_of_bounds_count}"
            )

        return report
