"""Container-frame transport shock checks for a pre-built door blocking wall."""
from dataclasses import asdict, dataclass
from typing import Any, Dict, Tuple

from backend.solver_v2.domain.models import ContainerSpec
from .types import DoorWall


@dataclass(frozen=True)
class TransportForceConfig:
    longitudinal_acceleration_g: float = 0.80
    lateral_acceleration_g: float = 0.50
    vertical_acceleration_g: float = 0.50
    friction_coefficient: float = 0.30
    max_door_restraint_gap_m: float = 0.12
    max_back_anchor_gap_m: float = 0.01
    min_back_anchor_coverage: float = 0.70
    door_open_perturbation_g: float = 0.15
    min_door_open_tipping_margin: float = 1.0


@dataclass(frozen=True)
class ForceAxisResult:
    vector: str
    acceleration_g: float
    impact_face: str
    support_face: str
    restraint: str
    restraint_available: bool
    sliding_margin: float
    tipping_margin: float
    restraint_coverage: float
    valid: bool

    def to_dict(self) -> Dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class TransportForceResult:
    valid: bool
    coordinate_frame: str
    outward_direction: str
    door_plane_clearance_m: float
    axes: Tuple[ForceAxisResult, ...]
    door_open_valid: bool
    door_open_columns: Tuple[Dict[str,Any], ...]
    rejection_reasons: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        data=asdict(self);data["axes"]=[axis.to_dict() for axis in self.axes];data["door_open_columns"]=[dict(x) for x in self.door_open_columns];return data


class TransportForceDirectionModel:
    """Hard validation; a score can never compensate for a failed axis.

    Canonical X runs from the inner/rear wall toward the doors, therefore +X is
    outward.  A thin blocking wall is accepted longitudinally only when the door
    is close enough to restrain +X motion and the planned main wall anchors -X.
    Exact collision/support semantics remain owned by the frozen validators.
    """

    def __init__(self, config: TransportForceConfig = None):
        self.config=config or TransportForceConfig()

    def evaluate(self, wall: DoorWall, container: ContainerSpec, supporting_placements=(), require_actual_back_anchor: bool = False) -> TransportForceResult:
        c=self.config
        door_gap=max((container.Lx-p.max_x for p in wall.placements),default=container.Lx)
        door_restraint=door_gap<=c.max_door_restraint_gap_m+1e-9
        support_area=0.0;total_area=sum(p.dy*p.dz for p in wall.placements)
        for door in wall.placements:
            if any(0.0<=door.x-main.max_x<=c.max_back_anchor_gap_m+1e-9
                   and min(door.max_y,main.max_y)-max(door.y,main.min_y)>1e-9
                   and min(door.max_z,main.max_z)-max(door.z,main.min_z)>1e-9
                   for main in supporting_placements):
                support_area+=door.dy*door.dz
        back_coverage=support_area/max(total_area,1e-9)
        back_anchor=(back_coverage>=c.min_back_anchor_coverage if require_actual_back_anchor else wall.stability.anchor_required)
        lateral_restraint=(wall.width_coverage>=.90 and wall.continuity.max_gap<=.20)
        vertical_support=wall.stability.supported_ratio>=.70
        columns={}
        for placement in wall.placements:columns.setdefault(placement.column,[]).append(placement)
        open_columns=[]
        for column,items in sorted(columns.items()):
            depth=max(p.dx for p in items);height=max(p.max_z for p in items)-min(p.z for p in items)
            margin=depth/max(c.door_open_perturbation_g*height,1e-9)
            valid=margin+1e-9>=c.min_door_open_tipping_margin and min(p.z for p in items)<=1e-9
            open_columns.append({"column":column,"sku":items[0].sku_id,"orientation":items[0].orientation,
                "base_depth_m":round(depth,6),"stack_height_m":round(height,6),
                "perturbation_g":c.door_open_perturbation_g,"tipping_margin":round(margin,4),"valid":valid})
        door_open_valid=bool(open_columns) and all(x["valid"] for x in open_columns)
        # Margins are dimensionless and descriptive. Restraint availability is
        # the hard condition for thin walls; no heuristic score bypasses it.
        axes=(
            ForceAxisResult("+X",c.longitudinal_acceleration_g,"REAR_FACE","DOOR_FACE","CONTAINER_DOOR",door_restraint,
                            round((c.friction_coefficient/c.longitudinal_acceleration_g),4),1.0 if door_restraint else 0.0,1.0 if door_restraint else 0.0,door_restraint),
            ForceAxisResult("-X",c.longitudinal_acceleration_g,"DOOR_FACE","REAR_FACE","MAIN_WALL_ANCHOR",back_anchor,
                            round((c.friction_coefficient/c.longitudinal_acceleration_g),4),1.0 if back_anchor else 0.0,round(back_coverage,4) if require_actual_back_anchor else 1.0,back_anchor),
            ForceAxisResult("+Y/-Y",c.lateral_acceleration_g,"SIDE_FACE","SIDE_FACE","NEIGHBOR_AND_CONTAINER_SIDE",lateral_restraint,
                            round((c.friction_coefficient/c.lateral_acceleration_g),4),round(wall.width_coverage,4),round(wall.width_coverage,4),lateral_restraint),
            ForceAxisResult("Z",c.vertical_acceleration_g,"TOP_FACE","BOTTOM_FACE","STACK_AND_FLOOR_SUPPORT",vertical_support,
                            1.0,round(wall.stability.supported_ratio,4),round(wall.stability.supported_ratio,4),vertical_support),
        )
        reasons=[]
        if not door_restraint:reasons.append("OUTWARD_DOOR_RESTRAINT_GAP_EXCEEDED")
        if not back_anchor:reasons.append("INWARD_MAIN_WALL_ANCHOR_MISSING")
        if not lateral_restraint:reasons.append("LATERAL_WALL_RESTRAINT_INSUFFICIENT")
        if not vertical_support:reasons.append("VERTICAL_SUPPORT_INSUFFICIENT")
        if not door_open_valid:reasons.append("DOOR_OPEN_UNRESTRAINED_TIPPING_RISK")
        return TransportForceResult(not reasons,"CONTAINER_CANONICAL_X_BACK_TO_DOOR","+X",round(door_gap,6),axes,
                                    door_open_valid,tuple(open_columns),tuple(reasons))
