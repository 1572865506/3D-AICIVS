"""
Adaptive Zones Engine for Solver V2 (Agent 04 / BLK-002).
Dynamically computes and manages 3D spatial zones:
- Rear Zone: Near inner wall (x -> 0)
- Middle / Main Body Zone: Central container body
- Door Zone: Elastic frontier ensuring cooperative door closure without static lockout
- Roof / Top Fill Zone: Upper container headroom (z -> Lz)
- Floor / Foundation Zone: Base floor level (z = 0)
"""
from dataclasses import dataclass
from typing import List, Tuple, Optional, Set, Dict, Any
import math

from backend.solver_v2.domain.models import (
    ContainerSpec,
    CargoSKU,
    ZoneType,
    PackingRole,
    Placement,
    Point3D,
    Orientation3D,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.door.elastic_frontier import ElasticDoorFrontier, ElasticDoorFrontierMetrics


@dataclass(frozen=True)
class ZoneBoundary:
    """3D bounding region of a spatial zone."""
    zone_type: ZoneType
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    min_z: float
    max_z: float

    @property
    def aabb(self) -> AABB:
        return AABB(self.min_x, self.min_y, self.min_z, self.max_x, self.max_y, self.max_z)

    def contains_point(self, x: float, y: float, z: float, eps: float = DEFAULT_GEOM_EPSILON) -> bool:
        return (
            self.min_x - eps <= x <= self.max_x + eps
            and self.min_y - eps <= y <= self.max_y + eps
            and self.min_z - eps <= z <= self.max_z + eps
        )

    def intersects_box(
        self,
        x: float,
        y: float,
        z: float,
        dx: float,
        dy: float,
        dz: float,
        eps: float = DEFAULT_GEOM_EPSILON,
    ) -> bool:
        ox = max(0.0, min(self.max_x, x + dx) - max(self.min_x, x))
        oy = max(0.0, min(self.max_y, y + dy) - max(self.min_y, y))
        oz = max(0.0, min(self.max_z, z + dz) - max(self.min_z, z))
        return ox > eps and oy > eps and oz > eps


class AdaptiveZoneManager:
    """
    Manages dynamic zone boundaries, hard zone gating, and soft zone affinity scoring.
    Equipped with ElasticDoorFrontier cooperative gating.
    """

    def __init__(
        self,
        container: ContainerSpec,
        door_zone_length_m: Optional[float] = None,
        rear_zone_length_m: Optional[float] = None,
        roof_clearance_m: float = 0.5,
        floor_height_m: float = 1.0,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container = container
        self.geom_epsilon = geom_epsilon
        self.roof_clearance_m = roof_clearance_m
        self.floor_height_m = floor_height_m

        # Dynamic longitudinal zone parameters
        self.rear_zone_length_m = (
            rear_zone_length_m if rear_zone_length_m is not None else container.rear_zone_length_m
        )
        self.door_zone_length_m = (
            door_zone_length_m if door_zone_length_m is not None else container.door_zone_length_m
        )
        self.latest_safe_main_x: float = max(0.0, container.Lx - self.door_zone_length_m)
        self.door_closure_start_x: float = max(0.0, container.Lx - self.door_zone_length_m)
        self.transition_start_x: float = max(0.0, self.door_closure_start_x - 0.5)

    @property
    def door_start_x(self) -> float:
        return max(0.0, self.container.Lx - self.door_zone_length_m)

    def adapt_door_zone_to_cargo(self, door_seal_skus: List[CargoSKU]) -> None:
        """
        Dynamically calculates elastic door frontier using ElasticDoorFrontier geometry.
        """
        if not door_seal_skus:
            return

        frontier = ElasticDoorFrontier(container=self.container, door_skus=door_seal_skus)
        metrics = frontier.get_metrics()
        self.door_zone_length_m = metrics.minimum_closure_depth
        self.latest_safe_main_x = metrics.latest_safe_main_x
        self.door_closure_start_x = metrics.door_closure_start_x
        self.transition_start_x = metrics.transition_start_x

    def update_frontier_metrics(self, metrics: ElasticDoorFrontierMetrics) -> None:
        """Applies updated live frontier metrics."""
        self.door_zone_length_m = metrics.minimum_closure_depth
        self.latest_safe_main_x = metrics.latest_safe_main_x
        self.door_closure_start_x = metrics.door_closure_start_x
        self.transition_start_x = metrics.transition_start_x

    def get_zone_boundaries(self) -> Dict[ZoneType, ZoneBoundary]:
        """Computes current 3D zone bounding regions."""
        lx, ly, lz = self.container.Lx, self.container.Ly, self.container.Lz
        door_start = self.latest_safe_main_x

        return {
            ZoneType.REAR: ZoneBoundary(
                zone_type=ZoneType.REAR,
                min_x=0.0,
                max_x=self.rear_zone_length_m,
                min_y=0.0,
                max_y=ly,
                min_z=0.0,
                max_z=lz,
            ),
            ZoneType.MIDDLE: ZoneBoundary(
                zone_type=ZoneType.MIDDLE,
                min_x=self.rear_zone_length_m,
                max_x=door_start,
                min_y=0.0,
                max_y=ly,
                min_z=0.0,
                max_z=lz,
            ),
            ZoneType.DOOR: ZoneBoundary(
                zone_type=ZoneType.DOOR,
                min_x=door_start,
                max_x=lx,
                min_y=0.0,
                max_y=ly,
                min_z=0.0,
                max_z=lz,
            ),
            ZoneType.ROOF_ONLY: ZoneBoundary(
                zone_type=ZoneType.ROOF_ONLY,
                min_x=0.0,
                max_x=lx,
                min_y=0.0,
                max_y=ly,
                min_z=max(0.0, lz - self.roof_clearance_m),
                max_z=lz,
            ),
            ZoneType.FLOOR_ONLY: ZoneBoundary(
                zone_type=ZoneType.FLOOR_ONLY,
                min_x=0.0,
                max_x=lx,
                min_y=0.0,
                max_y=ly,
                min_z=0.0,
                max_z=self.floor_height_m,
            ),
        }

    def check_hard_zone_compliance(
        self,
        sku: CargoSKU,
        x: float,
        y: float,
        z: float,
        dx: float,
        dy: float,
        dz: float,
    ) -> Tuple[bool, Optional[str]]:
        """
        Enforces elastic zone gating:
        1. Elastic door boundary: non-door cargo must not exceed latest_safe_main_x.
        2. Rear lock: SKUs with target_zone == REAR must remain in rear area.
        3. Floor lock: SKUs with must_be_on_floor must have z <= eps.
        """
        eps = self.geom_epsilon
        box_max_x = x + dx
        safe_limit = self.latest_safe_main_x

        # 1. Floor only constraint (physical rule)
        if sku.stacking_policy.must_be_on_floor and z > eps:
            return False, f"Floor only violation: SKU '{sku.sku_id}' must be on floor, but placed at z={z:.3f}"

        # 2. Explicit forbidden zones from CargoProfile (explicit user hard block)
        if sku.cargo_profile is not None:
            boundaries = self.get_zone_boundaries()
            for forbidden in sku.cargo_profile.zone_policy.forbidden:
                boundary = boundaries.get(forbidden)
                if boundary and boundary.intersects_box(x, y, z, dx, dy, dz, eps):
                    return False, f"Forbidden zone violation: SKU '{sku.sku_id}' intersects {forbidden.value}"

        # 3. Door zone lockout: non-door cargo must not exceed latest_safe_main_x
        if (
            PackingRole.DOOR_SEAL not in sku.packing_roles
            and sku.target_zone != ZoneType.DOOR
            and (sku.cargo_profile is None or (ZoneType.DOOR not in sku.cargo_profile.zone_policy.allowed and ZoneType.DOOR not in sku.cargo_profile.zone_policy.preferred))
        ):
            if box_max_x > safe_limit + eps:
                return False, f"Door zone lockout: SKU '{sku.sku_id}' (non-door) penetrates door zone [{safe_limit:.3f}, {self.container.Lx:.3f}]"

        return True, None

    def compute_zone_affinity_score(
        self,
        sku: CargoSKU,
        x: float,
        y: float,
        z: float,
        dx: float,
        dy: float,
        dz: float,
    ) -> float:
        """
        Computes soft affinity score:
        Higher score = better placement alignment with preferred zone and space utilization.
        """
        score = 0.0
        door_closure_start = self.door_closure_start_x

        # Bonus for foundation cargo on floor
        if PackingRole.FOUNDATION in sku.packing_roles and z <= self.geom_epsilon:
            score += 25.0

        # Rear affinity: smooth bonus favoring deeper positions near x=0, allowing smooth outward progression
        if sku.target_zone == ZoneType.REAR or PackingRole.FOUNDATION in sku.packing_roles:
            x_ratio = max(0.0, 1.0 - (x / max(self.container.Lx, 1.0)))
            score += x_ratio * 50.0

        # Door seal affinity: bonus for placing near trailing edge / door zone
        if PackingRole.DOOR_SEAL in sku.packing_roles or sku.target_zone == ZoneType.DOOR:
            if x >= door_closure_start - 0.5:
                score += 50.0
            else:
                score += 15.0

        if PackingRole.TOP_FILL in sku.packing_roles:
            z_ratio = z / self.container.Lz if self.container.Lz > 0 else 0.0
            score += z_ratio * 30.0

        return score
