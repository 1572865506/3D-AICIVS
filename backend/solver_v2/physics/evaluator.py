"""
Unified Physics & Stability Evaluator for Solver V2 (Agent 07).
Orchestrates:
1. ContactGraph construction (3D spatial contact network + boundary walls)
2. SupportGraph construction (DAG for vertical load paths)
3. LoadPropagationEngine (fractional load distribution and compression check)
4. ItemStabilityEvaluator (single item COM projection, overhang, slenderness)
5. ClusterStabilityEvaluator (interlocked cargo groups & collective COM)
6. WallStabilityEvaluator (transverse wall slices, H/T ratio, tipping moments)
7. StabilityDebtTracker (bounded temporary debt policy and zero-debt enforcement)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Set, Any

from backend.solver_v2.domain.models import Placement, CargoSKU, ContainerSpec
from backend.solver_v2.physics.contact_graph import ContactGraph, ContactEdge
from backend.solver_v2.physics.support_graph import SupportGraph, SupportEdge
from backend.solver_v2.physics.load_propagation import (
    LoadPropagationEngine,
    GlobalLoadReport,
    ItemLoadReport,
)
from backend.solver_v2.stability.models import (
    StabilityState,
    ItemStabilityReport,
    ClusterStabilityReport,
    WallStabilityReport,
    StabilityDebtItem,
)
from backend.solver_v2.stability.item_stability import ItemStabilityEvaluator
from backend.solver_v2.stability.cluster_stability import ClusterStabilityEvaluator
from backend.solver_v2.stability.wall_stability import WallStabilityEvaluator
from backend.solver_v2.stability.debt import StabilityDebtTracker
from backend.solver_v2.geometry.aabb import DEFAULT_GEOM_EPSILON


@dataclass
class PhysicsStabilityReport:
    """Consolidated physical integrity and stability report."""
    is_valid: bool
    load_report: GlobalLoadReport
    item_stability_reports: Dict[str, ItemStabilityReport]
    cluster_stability_reports: List[ClusterStabilityReport]
    wall_stability_reports: List[WallStabilityReport]
    unresolved_debts: List[StabilityDebtItem]
    compression_violations: List[str] = field(default_factory=list)
    stability_violations: List[str] = field(default_factory=list)
    summary: str = ""


class PhysicsStabilityEngine:
    """
    Unified clean-room Physics & Stability Engine for Solver V2.
    """

    def __init__(self, geom_epsilon: float = DEFAULT_GEOM_EPSILON):
        self.geom_epsilon = geom_epsilon
        self.load_engine = LoadPropagationEngine(geom_epsilon=geom_epsilon)
        self.item_evaluator = ItemStabilityEvaluator(geom_epsilon=geom_epsilon)
        self.cluster_evaluator = ClusterStabilityEvaluator(geom_epsilon=geom_epsilon)
        self.wall_evaluator = WallStabilityEvaluator(geom_epsilon=geom_epsilon)

    def evaluate_system(
        self,
        container: ContainerSpec,
        placements: List[Placement],
        cargo_catalog: Dict[str, CargoSKU],
        debt_tracker: Optional[StabilityDebtTracker] = None,
    ) -> PhysicsStabilityReport:
        """
        Runs comprehensive physical verification across all cargo placements.
        """
        # 1. Build ContactGraph and SupportGraph
        contact_graph = ContactGraph(container=container, geom_epsilon=self.geom_epsilon)
        support_graph = SupportGraph(container=container, geom_epsilon=self.geom_epsilon)

        for p in placements:
            contact_graph.add_placement(p)
            support_graph.add_placement(p)

        # 2. Compute Load Propagation and Compression
        load_report = self.load_engine.compute_loads(support_graph, cargo_catalog)

        # 3. Compute Item-level Stability
        item_reports: Dict[str, ItemStabilityReport] = {}
        item_stability_violations: List[str] = []

        for p in placements:
            sku = cargo_catalog.get(p.sku_id)
            report = self.item_evaluator.evaluate_placement(
                placement=p,
                sku=sku,
                support_graph=support_graph,
                contact_graph=contact_graph,
                container=container,
            )
            item_reports[p.placement_id] = report
            if not report.is_stable:
                item_stability_violations.append(
                    f"Item '{p.placement_id}' ({p.sku_id}) unstable: {'; '.join(report.reasons)}"
                )

        # 4. Compute Cluster-level Stability
        cluster_reports = self.cluster_evaluator.evaluate_clusters(
            placements=placements,
            contact_graph=contact_graph,
            container=container,
        )
        for cr in cluster_reports:
            if not cr.is_stable:
                item_stability_violations.append(
                    f"Cluster '{cr.cluster_id}' unstable: {'; '.join(cr.reasons)}"
                )

        # 5. Compute Wall-level Stability
        wall_reports = self.wall_evaluator.evaluate_walls(
            placements=placements,
            contact_graph=contact_graph,
            container=container,
        )
        for wr in wall_reports:
            if not wr.is_stable:
                item_stability_violations.append(
                    f"Wall '{wr.wall_id}' unstable: {'; '.join(wr.reasons)}"
                )

        # 6. Check Stability Debts
        unresolved_debts: List[StabilityDebtItem] = []
        if debt_tracker:
            unresolved_debts = debt_tracker.get_unresolved_debts()
            for d in unresolved_debts:
                item_stability_violations.append(
                    f"Unresolved stability debt for placement '{d.placement_id}' (cause: {d.cause})"
                )

        # Global validity
        is_valid = (
            load_report.is_valid and
            len(item_stability_violations) == 0 and
            len(unresolved_debts) == 0
        )

        compression_viols = list(load_report.violations)
        all_stab_viols = list(item_stability_violations)

        summary_lines = [
            f"Physics Evaluation: {'PASS' if is_valid else 'FAIL'}",
            f"- Total Cargo Weight: {load_report.total_cargo_weight_kg:.2f} kg",
            f"- Floor Support Load: {load_report.total_floor_load_kg:.2f} kg",
            f"- Placed Items Evaluated: {len(placements)}",
            f"- Cargo Clusters: {len(cluster_reports)}",
            f"- Transverse Walls: {len(wall_reports)}",
            f"- Compression Violations: {len(compression_viols)}",
            f"- Stability Violations: {len(all_stab_viols)}",
            f"- Unresolved Debts: {len(unresolved_debts)}",
        ]

        return PhysicsStabilityReport(
            is_valid=is_valid,
            load_report=load_report,
            item_stability_reports=item_reports,
            cluster_stability_reports=cluster_reports,
            wall_stability_reports=wall_reports,
            unresolved_debts=unresolved_debts,
            compression_violations=compression_viols,
            stability_violations=all_stab_viols,
            summary="\n".join(summary_lines),
        )
