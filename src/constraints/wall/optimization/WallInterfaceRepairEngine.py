"""Conservative wall-to-wall interface compaction.

The repair operates on vertical wall columns, never on individual cartons. A
single deep carton therefore cannot force neighbouring columns to inherit its
longitudinal frontier. Columns move only toward the locked door structure and
only until exact contact is made.
"""
from collections import defaultdict
from dataclasses import dataclass, replace
import re

from backend.solver_v2.domain.models import PlacementContext, Point3D
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


@dataclass(frozen=True)
class WallInterfaceRepairResult:
    status: str
    placements: tuple
    moved_columns: int
    moved_placements: int
    total_compaction_m: float
    maximum_compaction_m: float
    single_box_frontier_poisoning_removed: int
    rollback_reason: str
    validation: object

    def to_dict(self):
        return {
            "status": self.status,
            "moved_columns": self.moved_columns,
            "moved_placements": self.moved_placements,
            "total_compaction_m": self.total_compaction_m,
            "maximum_compaction_m": self.maximum_compaction_m,
            "single_box_frontier_poisoning_removed": self.single_box_frontier_poisoning_removed,
            "rollback_reason": self.rollback_reason,
            "validation": {"is_valid": self.validation.is_valid, "violations": len(self.validation.violations)},
        }


class WallInterfaceRepairEngine:
    """Close accidental longitudinal wall gaps without moving locked anchors."""

    _WALL_ID = re.compile(r"(cargo_wall|transition_wall)_(\d{3})", re.I)

    def __init__(self, min_gap_m=0.005, max_shift_m=.45, poisoning_delta_m=.05):
        self.min_gap_m = float(min_gap_m)
        self.max_shift_m = float(max_shift_m)
        self.poisoning_delta_m = float(poisoning_delta_m)

    @classmethod
    def _wall_id(cls, placement):
        match = cls._WALL_ID.search(placement.placement_id)
        return match.group(0).upper() if match else None

    @classmethod
    def _column_key(cls, placement):
        wall_id = cls._wall_id(placement)
        if wall_id is None or placement.context == PlacementContext.TOP_FILL:
            return None
        return (wall_id, round(placement.min_x, 6), round(placement.min_y, 6),
                round(placement.orientation.dx, 6), round(placement.orientation.dy, 6))

    @staticmethod
    def _overlap(a1, a2, b1, b2):
        return min(a2, b2) - max(a1, b1) > 1e-7

    def _forward_clearance(self, column, fixed, door_start):
        limit = min(door_start - max(p.max_x for p in column), self.max_shift_m)
        if limit <= self.min_gap_m:
            return 0.0
        found_contact = False
        for moving in column:
            for other in fixed:
                if not self._overlap(moving.min_y, moving.max_y, other.min_y, other.max_y):
                    continue
                if not self._overlap(moving.min_z, moving.max_z, other.min_z, other.max_z):
                    continue
                gap = other.min_x - moving.max_x
                if gap < -1e-7:
                    continue
                found_contact = True
                limit = min(limit, max(0.0, gap))
        return round(limit, 6) if found_contact and limit >= 0 else None

    def repair(self, container, cargo, placements, door_start=None):
        original = tuple(placements)
        door = tuple(p for p in original if p.placement_id.startswith("door_pre_"))
        if door_start is None:
            door_start = min((p.min_x for p in door), default=container.Lx)
        groups = defaultdict(list)
        movable_ids = set()
        for placement in original:
            key = self._column_key(placement)
            if key is not None:
                groups[key].append(placement)
                movable_ids.add(placement.placement_id)
        current = {p.placement_id: p for p in original}
        by_wall=defaultdict(list)
        for key,column in groups.items():by_wall[key[0]].append(column)
        ordered_walls=sorted(by_wall.values(),key=lambda cols:-max(p.max_x for col in cols for p in col))
        # Only the locked door wall and already processed doorward wall columns
        # define the adjacent interface. Unrelated solver placements must not
        # turn a local interface repair into global longitudinal compaction.
        fixed=list(door)
        moved_columns = moved_placements = 0
        shifts = []
        for wall_columns in ordered_walls:
            live_columns=[[current[p.placement_id] for p in column] for column in wall_columns]
            original_wall=[p for column in live_columns for p in column]
            clearances=[self._forward_clearance(column,fixed,door_start) for column in live_columns]
            comparable=[gap for gap in clearances if gap is not None]
            # Uniform spacing is not frontier poisoning. Repair only interfaces
            # where one local obstruction holds some columns back while the
            # neighbouring shoulder columns have materially larger clearance.
            base=min(comparable,default=0.0)
            # A real local interface has at least one contact/near-contact
            # column.  If neighbouring columns sit materially farther back,
            # compact only those shoulders.  Uniform spacing remains intact.
            blocker_count=sum(gap<=base+.01 for gap in comparable)
            blocker_ratio=blocker_count/max(len(comparable),1)
            poisoned=(len(comparable)>=4 and base<=.02
                      and blocker_ratio<=.25
                      and max(comparable)-base>self.poisoning_delta_m
                      and max(comparable)<=self.max_shift_m)
            new_wall=[]
            for live,gap in zip(live_columns,clearances):
                shift=gap if poisoned and gap is not None and gap>self.min_gap_m and gap<=self.max_shift_m else 0.0
                if shift>0:
                    moved_columns+=1;moved_placements+=len(live);shifts.append(shift)
                    live=[replace(p,position=Point3D(round(p.position.x+shift,6),p.position.y,p.position.z)) for p in live]
                    for placement in live:current[placement.placement_id]=placement
                new_wall.extend(live)
            # Interface detection is based on the original adjacent planes.
            # Feeding repaired geometry into the next interface would cascade a
            # local shoulder correction through the whole wall chain.
            fixed.extend(original_wall)
        repaired = tuple(current[p.placement_id] for p in original)
        validation = IndependentGlobalValidator.validate(container, list(repaired), list(cargo))
        if not validation.is_valid:
            rollback = IndependentGlobalValidator.validate(container, list(original), list(cargo))
            return WallInterfaceRepairResult("ROLLED_BACK", original, 0, 0, 0.0, 0.0, 0,
                                             "FULL_GLOBAL_VALIDATION_FAILED", rollback)
        return WallInterfaceRepairResult("SUCCESS", repaired, moved_columns, moved_placements,
                                         round(sum(shifts), 6), round(max(shifts, default=0.0), 6),
                                         moved_columns, "", validation)
