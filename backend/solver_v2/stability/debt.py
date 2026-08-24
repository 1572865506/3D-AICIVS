"""
Stability Debt Engine for Solver V2 (Agent 07).
Manages temporary stability debts:
- Bounded temporary debt policy: allows conditionally stable items to be temporarily committed
- Tracks debt items, reason, and required resolution
- Automatically resolves debt when adjacent bracing or supporting cargo is placed
- Strictly enforces ZERO unresolved debt before wall close, phase completion, and final commit
- Supports exact atomic rollback
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Set, Any
import copy

from backend.solver_v2.domain.models import Placement, CargoSKU, ContainerSpec
from backend.solver_v2.physics.contact_graph import ContactGraph
from backend.solver_v2.physics.support_graph import SupportGraph
from backend.solver_v2.stability.models import StabilityState, StabilityDebtItem, ItemStabilityReport
from backend.solver_v2.stability.item_stability import ItemStabilityEvaluator


class StabilityDebtLimitExceeded(Exception):
    """Raised when committing a conditionally stable item exceeds the bounded debt policy."""
    pass


class UnresolvedStabilityDebtError(Exception):
    """Raised when closing a wall, phase, or final solution with outstanding stability debt."""
    pass


class StabilityDebtTracker:
    """
    Authoritative tracker for temporary stability debts.
    """

    def __init__(
        self,
        max_active_debts: int = 3,
        max_debt_lifespan_steps: int = 10,
    ):
        self.max_active_debts = max_active_debts
        self.max_debt_lifespan_steps = max_debt_lifespan_steps

        # placement_id -> StabilityDebtItem
        self._debts: Dict[str, StabilityDebtItem] = {}
        
        # History stack for atomic rollback: List[Tuple[action, StabilityDebtItem]]
        self._history: List[Tuple[str, StabilityDebtItem]] = []

    @property
    def active_debt_count(self) -> int:
        return sum(1 for d in self._debts.values() if not d.is_resolved)

    @property
    def has_unresolved_debts(self) -> bool:
        return self.active_debt_count > 0

    def get_unresolved_debts(self) -> List[StabilityDebtItem]:
        return [d for d in self._debts.values() if not d.is_resolved]

    def can_accept_new_debt(self) -> bool:
        """Returns True if the current active debt count is strictly below the limit."""
        return self.active_debt_count < self.max_active_debts

    def record_debt(
        self,
        placement: Placement,
        step_index: int,
        cause: str,
        required_resolution: str = "ADJACENT_LATERAL_SUPPORT",
    ) -> StabilityDebtItem:
        """
        Records a new stability debt under the bounded policy.
        """
        if not self.can_accept_new_debt():
            raise StabilityDebtLimitExceeded(
                f"Cannot accept new stability debt for '{placement.placement_id}': "
                f"active debt quota ({self.active_debt_count}/{self.max_active_debts}) reached."
            )

        debt = StabilityDebtItem(
            placement_id=placement.placement_id,
            sku_id=placement.sku_id,
            step_committed=step_index,
            cause=cause,
            required_resolution=required_resolution,
            is_resolved=False,
        )
        self._debts[placement.placement_id] = debt
        self._history.append(("ADD", copy.deepcopy(debt)))
        return debt

    def on_placement_committed(
        self,
        new_placement: Placement,
        current_step: int,
        support_graph: SupportGraph,
        contact_graph: ContactGraph,
        cargo_catalog: Dict[str, CargoSKU],
        container: ContainerSpec,
        evaluator: Optional[ItemStabilityEvaluator] = None,
    ) -> List[StabilityDebtItem]:
        """
        Checks all active debts to see if new_placement resolves any of them.
        Returns list of newly resolved debt items.
        """
        if not self.has_unresolved_debts:
            return []

        eval_inst = evaluator or ItemStabilityEvaluator()
        resolved_list: List[StabilityDebtItem] = []

        for pid, debt in list(self._debts.items()):
            if debt.is_resolved:
                continue

            # Check lifespan
            if current_step - debt.step_committed > self.max_debt_lifespan_steps:
                # Debt has expired without being resolved
                continue

            target_p = support_graph.placements.get(pid)
            if not target_p:
                continue

            target_sku = cargo_catalog.get(target_p.sku_id)
            report = eval_inst.evaluate_placement(
                placement=target_p,
                sku=target_sku,
                support_graph=support_graph,
                contact_graph=contact_graph,
                container=container,
            )

            # If report is now SELF_STABLE, SUPPORTED_STABLE, or WARNING, debt is resolved!
            if report.stability_state in (StabilityState.SELF_STABLE, StabilityState.SUPPORTED_STABLE, StabilityState.WARNING):
                debt.is_resolved = True
                debt.resolved_step = current_step
                debt.resolved_by_placement_id = new_placement.placement_id
                self._history.append(("RESOLVE", copy.deepcopy(debt)))
                resolved_list.append(debt)

        return resolved_list

    def check_expired_debts(self, current_step: int) -> List[StabilityDebtItem]:
        """Returns list of active debts that have exceeded max lifespan."""
        expired = []
        for debt in self.get_unresolved_debts():
            if current_step - debt.step_committed > self.max_debt_lifespan_steps:
                expired.append(debt)
        return expired

    def enforce_zero_debt(self, phase_or_wall_name: str):
        """
        Asserts that there are zero unresolved stability debts before phase/wall close.
        """
        unresolved = self.get_unresolved_debts()
        if unresolved:
            pids = [d.placement_id for d in unresolved]
            raise UnresolvedStabilityDebtError(
                f"Cannot close '{phase_or_wall_name}': {len(unresolved)} unresolved stability debt(s) "
                f"remain for placements: {', '.join(pids)}"
            )

    def rollback_last_step(self):
        """Reverts the last action recorded in history."""
        if not self._history:
            return

        action, item = self._history.pop()
        pid = item.placement_id

        if action == "ADD":
            if pid in self._debts:
                del self._debts[pid]
        elif action == "RESOLVE":
            if pid in self._debts:
                self._debts[pid].is_resolved = False
                self._debts[pid].resolved_step = None
                self._debts[pid].resolved_by_placement_id = None

    def clear(self):
        self._debts.clear()
        self._history.clear()
