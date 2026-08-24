"""
Independent Global Validator for Solver V2 (Agent 06).
Strict, clean-room verification pipeline operating independently of solver search logic.
Validates:
1. Container Bounds
2. Pairwise Overlap & Penetration Volume
3. Total Payload & Weight Capacity
4. Orientation Legality & Allowed Contexts
5. Hard Zone & Door Boundary Rules
6. Stacking Limits, Floor-only, and No-top-stacking Rules
7. Bottom Support Ratio & Floating Box Detection
8. Bearing Weight & Compression Limits
9. Quantity Plan & Unknown SKU Checks
10. Topological Enclosed Cavities, Dead Space & Residual Fragmentation

Must reject solutions claiming success if any hard rule is violated.
"""
from typing import List, Dict, Any, Tuple, Optional, Set, Union
from collections import deque
import math

from backend.solver_v2.domain.models import (
    ContainerSpec,
    CargoSKU,
    Placement,
    BoxDim,
    Point3D,
    Orientation3D,
    OrientationMode,
    PlacementContext,
    ZoneType,
    PackingRole,
)
from backend.solver_v2.constraints.rules import (
    ZoneConstraint,
    DoorZoneConstraint,
    StackLimitConstraint,
    BearingConstraint,
    PressureConstraint,
    SupportRatioConstraint,
)
from backend.solver_v2.validation.types import (
    ViolationType,
    ViolationSeverity,
    ViolationDetail,
    ValidationResult,
)

EPSILON = 1e-4


class IndependentGlobalValidator:
    """
    Authoritative independent solution validator for Solver V2.
    Can be used both as an instance and via classmethod `validate`.
    """

    def __init__(
        self,
        geom_epsilon: float = EPSILON,
        grid_resolution: float = 0.1,
        max_allowed_cavity_volume: Optional[float] = None,
    ):
        self.geom_epsilon = geom_epsilon
        self.grid_resolution = grid_resolution
        self.max_allowed_cavity_volume = max_allowed_cavity_volume

    @classmethod
    def validate(
        cls,
        container: Union[ContainerSpec, Tuple[float, float, float], Dict[str, Any]],
        placements: Union[List[Placement], List[Dict[str, Any]]],
        cargo_list: Optional[Union[List[CargoSKU], Dict[str, CargoSKU], List[Dict[str, Any]]]] = None,
        compiled_constraints: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, Any]] = None,
        *,
        geom_epsilon: float = EPSILON,
        grid_resolution: float = 0.1,
        max_allowed_cavity_volume: Optional[float] = None,
    ) -> ValidationResult:
        """
        Validation entry point. Can be invoked on an instance or directly on the class.
        """
        if isinstance(cls, IndependentGlobalValidator):
            validator_inst = cls
        else:
            validator_inst = cls(
                geom_epsilon=geom_epsilon,
                grid_resolution=grid_resolution,
                max_allowed_cavity_volume=max_allowed_cavity_volume,
            )

        return validator_inst._run_validation(
            container=container,
            placements=placements,
            cargo_list=cargo_list,
            compiled_constraints=compiled_constraints,
            options=options,
        )

    def _run_validation(
        self,
        container: Union[ContainerSpec, Tuple[float, float, float], Dict[str, Any]],
        placements: Union[List[Placement], List[Dict[str, Any]]],
        cargo_list: Optional[Union[List[CargoSKU], Dict[str, CargoSKU], List[Dict[str, Any]]]] = None,
        compiled_constraints: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        # 1. Normalize container
        c_lx, c_ly, c_lz, max_payload, door_zone_len, rear_zone_len = self._normalize_container(container)
        if options and "door_zone_length_m" in options:
            door_zone_len = float(options["door_zone_length_m"])
        elif cargo_list:
            door_seal_skus = [
                s for s in (cargo_list.values() if isinstance(cargo_list, dict) else cargo_list)
                if isinstance(s, CargoSKU) and (PackingRole.DOOR_SEAL in s.packing_roles or s.target_zone == ZoneType.DOOR)
            ]
            if door_seal_skus:
                from backend.solver_v2.door.elastic_frontier import ElasticDoorFrontier
                c_spec = container if isinstance(container, ContainerSpec) else ContainerSpec(
                    code="VALID_C", inner_dim=BoxDim(c_lx, c_ly, c_lz), max_payload_kg=max_payload
                )
                frontier = ElasticDoorFrontier(container=c_spec, door_skus=door_seal_skus)
                door_zone_len = frontier.get_metrics().minimum_closure_depth

        # 2. Normalize placements
        norm_placements = self._normalize_placements(placements)

        # 3. Normalize cargo SKU lookup
        sku_map = self._normalize_cargo_skus(cargo_list)

        violations: List[ViolationDetail] = []
        bounds_violations: List[ViolationDetail] = []
        overlap_violations: List[ViolationDetail] = []
        orientation_violations: List[ViolationDetail] = []
        constraint_violations: List[ViolationDetail] = []
        stability_violations: List[ViolationDetail] = []
        quantity_violations: List[ViolationDetail] = []
        rejection_reasons: List[str] = []

        # --- A. Bounds Validation ---
        b_viols = self._validate_bounds(norm_placements, c_lx, c_ly, c_lz)
        if b_viols:
            bounds_violations.extend(b_viols)
            rejection_reasons.append("CONTAINER_BOUNDS_EXCEEDED")

        # --- B. Overlap & Penetration Volume ---
        o_viols, total_overlap_vol, overlap_pairs = self._validate_overlaps(norm_placements)
        if o_viols:
            overlap_violations.extend(o_viols)
            rejection_reasons.append("COLLISION_OVERLAP_DETECTED")

        # --- C. Payload Weight Validation ---
        total_cargo_weight = sum(p["weight_kg"] for p in norm_placements)
        if max_payload > 0 and total_cargo_weight > max_payload + self.geom_epsilon:
            p_viol = ViolationDetail(
                violation_type=ViolationType.PAYLOAD_EXCEEDED,
                severity=ViolationSeverity.FATAL,
                message=f"Total cargo weight ({total_cargo_weight:.2f} kg) exceeds container max payload ({max_payload:.2f} kg)",
                extra_data={"total_weight_kg": total_cargo_weight, "max_payload_kg": max_payload},
            )
            constraint_violations.append(p_viol)
            rejection_reasons.append("MAX_PAYLOAD_EXCEEDED")

        # --- D. Quantity & SKU Check ---
        q_viols = self._validate_quantities(norm_placements, sku_map)
        if q_viols:
            quantity_violations.extend(q_viols)
            for qv in q_viols:
                if qv.severity == ViolationSeverity.FATAL:
                    rejection_reasons.append(qv.violation_type.value)
                    break

        # --- E. Orientation Legality ---
        if sku_map:
            ori_viols = self._validate_orientations(norm_placements, sku_map)
            if ori_viols:
                orientation_violations.extend(ori_viols)
                rejection_reasons.append("FORBIDDEN_ORIENTATION_DETECTED")

        # --- F. Business Rules, Stacking, Support & Bearing ---
        r_viols, stab_viols = self._validate_rules_and_physics(
            norm_placements,
            sku_map,
            c_lx,
            c_ly,
            c_lz,
            door_zone_len,
            rear_zone_len,
            compiled_constraints,
        )
        if r_viols:
            constraint_violations.extend(r_viols)
            for rv in r_viols:
                if rv.severity == ViolationSeverity.FATAL and rv.violation_type.value not in rejection_reasons:
                    rejection_reasons.append(rv.violation_type.value)
        if stab_viols:
            stability_violations.extend(stab_viols)
            for sv in stab_viols:
                if sv.severity == ViolationSeverity.FATAL and sv.violation_type.value not in rejection_reasons:
                    rejection_reasons.append(sv.violation_type.value)

        # --- G. Residual Space, Enclosed Cavities & Fragmentation ---
        space_metrics = self._analyze_cavities_and_space(norm_placements, c_lx, c_ly, c_lz, sku_map)
        if (
            self.max_allowed_cavity_volume is not None
            and space_metrics["enclosed_cavity_volume"] > self.max_allowed_cavity_volume + self.geom_epsilon
        ):
            cav_viol = ViolationDetail(
                violation_type=ViolationType.CAVITY_THRESHOLD_EXCEEDED,
                severity=ViolationSeverity.FATAL,
                message=f"Enclosed cavity volume ({space_metrics['enclosed_cavity_volume']:.3f} m³) exceeds maximum allowed limit ({self.max_allowed_cavity_volume:.3f} m³)",
                extra_data=space_metrics,
            )
            constraint_violations.append(cav_viol)
            rejection_reasons.append("ENCLOSED_CAVITY_LIMIT_EXCEEDED")

        # Collect all violations
        all_violations = (
            bounds_violations
            + overlap_violations
            + orientation_violations
            + constraint_violations
            + stability_violations
            + quantity_violations
        )

        fatal_violations = [v for v in all_violations if v.severity == ViolationSeverity.FATAL]
        is_valid = len(fatal_violations) == 0

        # Compute summary volume metrics
        container_vol = c_lx * c_ly * c_lz
        cargo_vol = sum(p["dx"] * p["dy"] * p["dz"] for p in norm_placements)
        utilization_pct = (cargo_vol / container_vol * 100.0) if container_vol > 0 else 0.0

        metrics = {
            "is_valid": is_valid,
            "placed_count": len(norm_placements),
            "total_cargo_weight_kg": round(total_cargo_weight, 3),
            "max_payload_kg": round(max_payload, 3),
            "container_volume": round(container_vol, 6),
            "cargo_volume": round(cargo_vol, 6),
            "volume_utilization_pct": round(utilization_pct, 4),
            "out_of_bounds_count": len(bounds_violations),
            "overlap_pair_count": len(overlap_pairs),
            "penetration_volume": round(total_overlap_vol, 6),
            "overlap_pairs": overlap_pairs,
            "enclosed_cavity_count": space_metrics.get("enclosed_cavity_count", 0),
            "enclosed_cavity_volume": space_metrics.get("enclosed_cavity_volume", 0.0),
            "reachable_residual_volume": space_metrics.get("reachable_residual_volume", 0.0),
            "dead_space_volume": space_metrics.get("dead_space_volume", 0.0),
            "sliver_volume": space_metrics.get("sliver_volume", 0.0),
            "fragmentation_score": space_metrics.get("fragmentation_score", 0.0),
        }

        summary = self._build_summary_text(is_valid, rejection_reasons, metrics, all_violations)

        return ValidationResult(
            is_valid=is_valid,
            rejection_reasons=rejection_reasons,
            violations=all_violations,
            bounds_violations=bounds_violations,
            overlap_violations=overlap_violations,
            orientation_violations=orientation_violations,
            constraint_violations=constraint_violations,
            stability_violations=stability_violations,
            quantity_violations=quantity_violations,
            metrics=metrics,
            summary=summary,
        )

    # -------------------------------------------------------------------------
    # Sub-Validators
    # -------------------------------------------------------------------------

    def _validate_bounds(
        self,
        placements: List[Dict[str, Any]],
        c_lx: float,
        c_ly: float,
        c_lz: float,
    ) -> List[ViolationDetail]:
        """Validates all boxes are strictly inside container [0, c_lx] x [0, c_ly] x [0, c_lz]."""
        violations = []
        eps = self.geom_epsilon

        for i, p in enumerate(placements):
            x, y, z = p["x"], p["y"], p["z"]
            dx, dy, dz = p["dx"], p["dy"], p["dz"]
            max_x = x + dx
            max_y = y + dy
            max_z = z + dz

            oob_reasons = []
            if x < -eps:
                oob_reasons.append(f"min_x ({x:.4f}) < 0")
            if y < -eps:
                oob_reasons.append(f"min_y ({y:.4f}) < 0")
            if z < -eps:
                oob_reasons.append(f"min_z ({z:.4f}) < 0")
            if max_x > c_lx + eps:
                oob_reasons.append(f"max_x ({max_x:.4f}) > Lx ({c_lx:.4f})")
            if max_y > c_ly + eps:
                oob_reasons.append(f"max_y ({max_y:.4f}) > Ly ({c_ly:.4f})")
            if max_z > c_lz + eps:
                oob_reasons.append(f"max_z ({max_z:.4f}) > Lz ({c_lz:.4f})")

            if oob_reasons:
                violations.append(
                    ViolationDetail(
                        violation_type=ViolationType.OUT_OF_BOUNDS,
                        severity=ViolationSeverity.FATAL,
                        message=f"Placement {p['placement_id']} (SKU: {p['sku_id']}) exceeds container bounds: {', '.join(oob_reasons)}",
                        sku_id=p["sku_id"],
                        placement_id=p["placement_id"],
                        placement_index=i,
                        location=(x, y, z),
                        dimension=(dx, dy, dz),
                        extra_data={"container_dim": (c_lx, c_ly, c_lz), "overflow_reasons": oob_reasons},
                    )
                )

        return violations

    def _validate_overlaps(
        self,
        placements: List[Dict[str, Any]],
    ) -> Tuple[List[ViolationDetail], float, List[Dict[str, Any]]]:
        """Validates 3D box collisions and computes exact pairwise penetration volume."""
        violations = []
        overlap_pairs = []
        total_overlap_vol = 0.0
        eps = self.geom_epsilon
        n = len(placements)

        for i in range(n):
            p1 = placements[i]
            x1, y1, z1 = p1["x"], p1["y"], p1["z"]
            dx1, dy1, dz1 = p1["dx"], p1["dy"], p1["dz"]
            max_x1, max_y1, max_z1 = x1 + dx1, y1 + dy1, z1 + dz1

            for j in range(i + 1, n):
                p2 = placements[j]
                x2, y2, z2 = p2["x"], p2["y"], p2["z"]
                dx2, dy2, dz2 = p2["dx"], p2["dy"], p2["dz"]
                max_x2, max_y2, max_z2 = x2 + dx2, y2 + dy2, z2 + dz2

                ox = max(0.0, min(max_x1, max_x2) - max(x1, x2))
                oy = max(0.0, min(max_y1, max_y2) - max(y1, y2))
                oz = max(0.0, min(max_z1, max_z2) - max(z1, z2))

                if ox > eps and oy > eps and oz > eps:
                    vol = ox * oy * oz
                    total_overlap_vol += vol
                    pair_info = {
                        "pair_indices": (i, j),
                        "pair_ids": (p1["placement_id"], p2["placement_id"]),
                        "sku_pair": (p1["sku_id"], p2["sku_id"]),
                        "overlap_volume": round(vol, 6),
                        "overlap_box": (
                            round(max(x1, x2), 4),
                            round(max(y1, y2), 4),
                            round(max(z1, z2), 4),
                            round(ox, 4),
                            round(oy, 4),
                            round(oz, 4),
                        ),
                    }
                    overlap_pairs.append(pair_info)
                    violations.append(
                        ViolationDetail(
                            violation_type=ViolationType.COLLISION_OVERLAP,
                            severity=ViolationSeverity.FATAL,
                            message=(
                                f"Collision between #{i} ({p1['sku_id']}) and #{j} ({p2['sku_id']}), "
                                f"overlap volume = {vol:.6f} m³"
                            ),
                            sku_id=f"{p1['sku_id']} & {p2['sku_id']}",
                            placement_id=f"{p1['placement_id']} & {p2['placement_id']}",
                            placement_index=i,
                            extra_data=pair_info,
                        )
                    )

        return violations, total_overlap_vol, overlap_pairs

    def _validate_quantities(
        self,
        placements: List[Dict[str, Any]],
        sku_map: Optional[Dict[str, CargoSKU]],
    ) -> List[ViolationDetail]:
        """Validates placed counts against quantity plans and checks for unknown SKUs."""
        violations = []
        if not sku_map:
            return violations

        counts: Dict[str, int] = {}
        for p in placements:
            sku = p["sku_id"]
            counts[sku] = counts.get(sku, 0) + 1

        for sku, count in counts.items():
            if sku not in sku_map:
                violations.append(
                    ViolationDetail(
                        violation_type=ViolationType.UNKNOWN_SKU,
                        severity=ViolationSeverity.FATAL,
                        message=f"Placement contains unknown SKU: '{sku}' not present in problem spec",
                        sku_id=sku,
                        extra_data={"placed_count": count},
                    )
                )
                continue

            cargo = sku_map[sku]
            q_plan = cargo.quantity
            max_allowed = q_plan.max_quantity if q_plan.max_quantity is not None else q_plan.required

            if count > max_allowed:
                violations.append(
                    ViolationDetail(
                        violation_type=ViolationType.QUANTITY_VIOLATION,
                        severity=ViolationSeverity.FATAL,
                        message=f"SKU '{sku}' placed count ({count}) exceeds maximum allowed ({max_allowed})",
                        sku_id=sku,
                        extra_data={"placed_count": count, "max_allowed": max_allowed, "required": q_plan.required},
                    )
                )

        return violations

    def _validate_orientations(
        self,
        placements: List[Dict[str, Any]],
        sku_map: Dict[str, CargoSKU],
    ) -> List[ViolationDetail]:
        """Checks if placed box dimensions match legal rotations according to SKU OrientationPolicy."""
        violations = []
        eps = self.geom_epsilon

        for i, p in enumerate(placements):
            sku_id = p["sku_id"]
            if sku_id not in sku_map:
                continue

            cargo = sku_map[sku_id]
            base_box = cargo.box
            policy = cargo.orientation_policy
            context = p.get("context", PlacementContext.GENERAL)

            dx, dy, dz = p["dx"], p["dy"], p["dz"]
            bx, by, bz = base_box.x, base_box.y, base_box.z

            # Check if (dx, dy, dz) is a permutation of (bx, by, bz)
            dims_p = sorted([dx, dy, dz])
            dims_b = sorted([bx, by, bz])
            if any(abs(dp - db) > eps for dp, db in zip(dims_p, dims_b)):
                violations.append(
                    ViolationDetail(
                        violation_type=ViolationType.FORBIDDEN_ORIENTATION,
                        severity=ViolationSeverity.FATAL,
                        message=f"Placement {p['placement_id']} (SKU: {sku_id}) has illegal dimensions ({dx:.3f}, {dy:.3f}, {dz:.3f}) not matching base SKU dimensions ({bx:.3f}, {by:.3f}, {bz:.3f})",
                        sku_id=sku_id,
                        placement_id=p["placement_id"],
                        placement_index=i,
                        location=(p["x"], p["y"], p["z"]),
                        dimension=(dx, dy, dz),
                    )
                )
                continue

            # Classify rotation type:
            # 1. Upright: dz == bz (height is preserved along vertical axis)
            is_upright = abs(dz - bz) <= eps and (
                (abs(dx - bx) <= eps and abs(dy - by) <= eps) or (abs(dx - by) <= eps and abs(dy - bx) <= eps)
            )

            # 2. Flat: dz == by (or dz == bx if smallest)
            is_flat = abs(dz - by) <= eps and (
                (abs(dx - bx) <= eps and abs(dy - bz) <= eps) or (abs(dx - bz) <= eps and abs(dy - bx) <= eps)
            )

            # 3. Side: dz == bx
            is_side = abs(dz - bx) <= eps and (
                (abs(dx - by) <= eps and abs(dy - bz) <= eps) or (abs(dx - bz) <= eps and abs(dy - by) <= eps)
            )

            legal = False
            reasons = []

            if is_upright:
                rule = policy.rule_for(OrientationMode.UPRIGHT, context)
                if rule and rule.allows(policy.context_region(context), base_height=p["z"]):
                    legal = True
                else:
                    reasons.append("Upright orientation is not allowed by policy")

            if is_flat:
                rule = policy.rule_for(OrientationMode.FLAT, context)
                if rule and rule.allows(policy.context_region(context), base_height=p["z"]):
                    legal = True
                else:
                    reasons.append(f"Flat orientation not allowed by rule in context {context}")

            if is_side:
                rule = policy.rule_for(OrientationMode.SIDE, context)
                if rule and rule.allows(policy.context_region(context), base_height=p["z"]):
                    legal = True
                else:
                    reasons.append(f"Side orientation not allowed by rule in context {context}")

            if not legal:
                violations.append(
                    ViolationDetail(
                        violation_type=ViolationType.FORBIDDEN_ORIENTATION,
                        severity=ViolationSeverity.FATAL,
                        message=f"Placement {p['placement_id']} (SKU: {sku_id}) orientation ({dx:.3f}x{dy:.3f}x{dz:.3f}) is illegal: {'; '.join(reasons) if reasons else 'Orientation not permitted'}",
                        sku_id=sku_id,
                        placement_id=p["placement_id"],
                        placement_index=i,
                        location=(p["x"], p["y"], p["z"]),
                        dimension=(dx, dy, dz),
                        extra_data={"context": str(context), "is_upright": is_upright, "is_flat": is_flat, "is_side": is_side},
                    )
                )

        return violations

    def _validate_rules_and_physics(
        self,
        placements: List[Dict[str, Any]],
        sku_map: Optional[Dict[str, CargoSKU]],
        c_lx: float,
        c_ly: float,
        c_lz: float,
        door_zone_len: float,
        rear_zone_len: float,
        compiled_constraints: Optional[Dict[str, Any]],
    ) -> Tuple[List[ViolationDetail], List[ViolationDetail]]:
        """
        Validates business rules and physical mechanics:
        - Zone restrictions & Door zone lockout
        - Floor-only rules
        - No-top-stacking constraints
        - Stacking layer limits
        - Contact support ratio & floating box detection
        - Upper bearing weight and pressure
        """
        rule_violations = []
        stability_violations = []
        eps = self.geom_epsilon
        n = len(placements)

        # 1. Door zone boundary
        door_start = max(0.0, c_lx - door_zone_len)

        for i, p in enumerate(placements):
            sku_id = p["sku_id"]
            x, y, z = p["x"], p["y"], p["z"]
            dx, dy, dz = p["dx"], p["dy"], p["dz"]
            cargo = sku_map.get(sku_id) if sku_map else None

            # --- Zone Rules ---
            if cargo:
                # Target Zone check
                if cargo.target_zone == ZoneType.REAR and (x + dx > rear_zone_len + 0.5):
                    rule_violations.append(
                        ViolationDetail(
                            violation_type=ViolationType.ZONE_VIOLATION,
                            severity=ViolationSeverity.FATAL,
                            message=f"Placement {p['placement_id']} (SKU: {sku_id}) assigned to REAR zone exceeds rear limit ({x+dx:.2f} > {rear_zone_len+0.5:.2f})",
                            sku_id=sku_id,
                            placement_id=p["placement_id"],
                            placement_index=i,
                        )
                    )

                # Door Lockout check: non-door-seal SKUs must not enter door zone
                is_door_seal = (
                    PackingRole.DOOR_SEAL in cargo.packing_roles
                    or cargo.target_zone == ZoneType.DOOR
                )
                if (not is_door_seal) and (x + dx > door_start + eps):
                    rule_violations.append(
                        ViolationDetail(
                            violation_type=ViolationType.DOOR_LOCKOUT_VIOLATION,
                            severity=ViolationSeverity.FATAL,
                            message=f"Placement {p['placement_id']} (SKU: {sku_id}) violates door lockout: non-door-seal SKU placed in door zone [x_end={x+dx:.2f} > door_start={door_start:.2f}]",
                            sku_id=sku_id,
                            placement_id=p["placement_id"],
                            placement_index=i,
                        )
                    )

                # Floor Only check
                if cargo.stacking_policy.must_be_on_floor and z > eps:
                    rule_violations.append(
                        ViolationDetail(
                            violation_type=ViolationType.FLOOR_ONLY_VIOLATION,
                            severity=ViolationSeverity.FATAL,
                            message=f"Placement {p['placement_id']} (SKU: {sku_id}) must be placed on floor, but placed at z={z:.3f}",
                            sku_id=sku_id,
                            placement_id=p["placement_id"],
                            placement_index=i,
                        )
                    )

            # --- Support Ratio & Floating Box Check ---
            if z > eps:
                # Find supporting boxes directly underneath
                total_support_area = 0.0
                bottom_z = z

                for j in range(n):
                    if i == j:
                        continue
                    p2 = placements[j]
                    top_z2 = p2["z"] + p2["dz"]

                    # Check if top face of p2 matches bottom of p
                    if abs(top_z2 - bottom_z) <= eps:
                        # Compute contact area on XY plane
                        ox = max(0.0, min(x + dx, p2["x"] + p2["dx"]) - max(x, p2["x"]))
                        oy = max(0.0, min(y + dy, p2["y"] + p2["dy"]) - max(y, p2["y"]))
                        if ox > eps and oy > eps:
                            total_support_area += ox * oy

                base_area = dx * dy
                support_ratio = total_support_area / base_area if base_area > 0 else 0.0
                min_ratio = cargo.stacking_policy.min_support_ratio if cargo else 0.70

                if support_ratio < min_ratio - eps:
                    stability_violations.append(
                        ViolationDetail(
                            violation_type=ViolationType.INSUFFICIENT_SUPPORT,
                            severity=ViolationSeverity.FATAL,
                            message=f"Placement {p['placement_id']} (SKU: {sku_id}) at z={z:.2f} has insufficient support ratio ({support_ratio * 100:.1f}% < required {min_ratio * 100:.1f}%)",
                            sku_id=sku_id,
                            placement_id=p["placement_id"],
                            placement_index=i,
                            extra_data={"support_ratio": support_ratio, "min_support_ratio": min_ratio},
                        )
                    )

            # --- Stacking on Top, Bearing & Pressure Limits ---
            # Find boxes pressing onto p
            upper_boxes = []
            upper_weight = 0.0
            top_z = z + dz

            for j in range(n):
                if i == j:
                    continue
                p2 = placements[j]
                if abs(p2["z"] - top_z) <= eps:
                    ox = max(0.0, min(x + dx, p2["x"] + p2["dx"]) - max(x, p2["x"]))
                    oy = max(0.0, min(y + dy, p2["y"] + p2["dy"]) - max(y, p2["y"]))
                    if ox > eps and oy > eps:
                        contact_frac = (ox * oy) / (p2["dx"] * p2["dy"])
                        w = p2["weight_kg"] * contact_frac
                        upper_weight += w
                        upper_boxes.append((j, p2["sku_id"], ox * oy, w))

            # 1. No top stacking allowed check
            if cargo and not cargo.stacking_policy.allow_stacking_on_top and upper_boxes:
                rule_violations.append(
                    ViolationDetail(
                        violation_type=ViolationType.NO_TOP_STACK_VIOLATION,
                        severity=ViolationSeverity.FATAL,
                        message=f"Placement {p['placement_id']} (SKU: {sku_id}) forbids stacking on top, but has {len(upper_boxes)} boxes resting above it",
                        sku_id=sku_id,
                        placement_id=p["placement_id"],
                        placement_index=i,
                        extra_data={"upper_boxes": upper_boxes},
                    )
                )

            # 2. Bearing weight check
            if cargo and cargo.stacking_policy.max_bearing_kg is not None:
                max_bearing = cargo.stacking_policy.max_bearing_kg
                if upper_weight > max_bearing + eps:
                    stability_violations.append(
                        ViolationDetail(
                            violation_type=ViolationType.BEARING_EXCEEDED,
                            severity=ViolationSeverity.FATAL,
                            message=f"Placement {p['placement_id']} (SKU: {sku_id}) upper bearing weight ({upper_weight:.1f} kg) exceeds limit ({max_bearing:.1f} kg)",
                            sku_id=sku_id,
                            placement_id=p["placement_id"],
                            placement_index=i,
                            extra_data={"upper_weight_kg": upper_weight, "max_bearing_kg": max_bearing},
                        )
                    )

            # 3. Pressure check
            if cargo and cargo.stacking_policy.max_pressure_kg_m2 is not None:
                max_pressure = cargo.stacking_policy.max_pressure_kg_m2
                top_area = dx * dy
                pressure = upper_weight / top_area if top_area > 0 else 0.0
                if pressure > max_pressure + eps:
                    stability_violations.append(
                        ViolationDetail(
                            violation_type=ViolationType.PRESSURE_EXCEEDED,
                            severity=ViolationSeverity.FATAL,
                            message=f"Placement {p['placement_id']} (SKU: {sku_id}) top pressure ({pressure:.1f} kg/m²) exceeds limit ({max_pressure:.1f} kg/m²)",
                            sku_id=sku_id,
                            placement_id=p["placement_id"],
                            placement_index=i,
                            extra_data={"pressure_kg_m2": pressure, "max_pressure_kg_m2": max_pressure},
                        )
                    )

            # 4. Vertical Stack layers check
            if cargo and cargo.stacking_policy.max_stack_layers is not None:
                max_layers = cargo.stacking_policy.max_stack_layers
                # ``max_stack_layers`` is a property of this SKU's own stack,
                # not a ban on placing a different, otherwise compatible SKU
                # above it.  Compression / bearing / category policies govern
                # mixed-SKU cargo carried by this carton.
                stack_depth = self._compute_stack_column_depth(i, placements, same_sku_only=True)
                if stack_depth > max_layers:
                    rule_violations.append(
                        ViolationDetail(
                            violation_type=ViolationType.STACK_LIMIT_VIOLATION,
                            severity=ViolationSeverity.FATAL,
                            message=f"Placement {p['placement_id']} (SKU: {sku_id}) in stack column of height {stack_depth} layers, exceeding max_layers ({max_layers})",
                            sku_id=sku_id,
                            placement_id=p["placement_id"],
                            placement_index=i,
                            extra_data={"stack_depth": stack_depth, "max_layers": max_layers},
                        )
                    )

        return rule_violations, stability_violations

    def _compute_stack_column_depth(
        self,
        index: int,
        placements: List[Dict[str, Any]],
        same_sku_only: bool = False,
    ) -> int:
        """Count the contiguous vertical stack containing ``index``.

        When validating a SKU layer limit, only contiguous cartons of that SKU
        participate.  A different SKU terminates the self-stack chain and is
        governed by the lower carton's top-load policies instead.
        """
        p = placements[index]
        x, y, z = p["x"], p["y"], p["z"]
        dx, dy = p["dx"], p["dy"]
        sku_id = p["sku_id"]
        eps = self.geom_epsilon

        # Count layers downwards to floor
        layers = 1
        curr_z = z

        while curr_z > eps:
            found_below = False
            for j, p2 in enumerate(placements):
                if j == index:
                    continue
                if same_sku_only and p2["sku_id"] != sku_id:
                    continue
                if abs(p2["z"] + p2["dz"] - curr_z) <= eps:
                    # Check XY overlap
                    ox = max(0.0, min(x + dx, p2["x"] + p2["dx"]) - max(x, p2["x"]))
                    oy = max(0.0, min(y + dy, p2["y"] + p2["dy"]) - max(y, p2["y"]))
                    if ox > eps and oy > eps:
                        layers += 1
                        curr_z = p2["z"]
                        found_below = True
                        break
            if not found_below:
                break

        return layers

    # -------------------------------------------------------------------------
    # Independent Cavity & Residual Space Topologic Analysis
    # -------------------------------------------------------------------------

    def _analyze_cavities_and_space(
        self,
        placements: List[Dict[str, Any]],
        c_lx: float,
        c_ly: float,
        c_lz: float,
        sku_map: Optional[Dict[str, CargoSKU]],
    ) -> Dict[str, Any]:
        """
        Independent 3D Voxel Flood-Fill reachability analysis from door plane (x = c_lx).
        Identifies enclosed cavity volume, reachable volume, dead space, and fragmentation.
        """
        grid_res = self.grid_resolution
        nx = max(1, int(math.ceil(c_lx / grid_res)))
        ny = max(1, int(math.ceil(c_ly / grid_res)))
        nz = max(1, int(math.ceil(c_lz / grid_res)))
        dx_cell = c_lx / nx
        dy_cell = c_ly / ny
        dz_cell = c_lz / nz
        cell_vol = dx_cell * dy_cell * dz_cell

        total_container_vol = c_lx * c_ly * c_lz
        if not placements:
            return {
                "enclosed_cavity_count": 0,
                "enclosed_cavity_volume": 0.0,
                "reachable_residual_volume": round(total_container_vol, 6),
                "dead_space_volume": 0.0,
                "sliver_volume": 0.0,
                "fragmentation_score": 0.0,
            }

        # 1. Rasterize placements onto 3D grid: 0 = Free, 1 = Occupied
        grid = bytearray(nx * ny * nz)
        eps = self.geom_epsilon

        for p in placements:
            ix_min = max(0, int(p["x"] / dx_cell))
            ix_max = min(nx, int(math.ceil((p["x"] + p["dx"] - eps) / dx_cell)))
            iy_min = max(0, int(p["y"] / dy_cell))
            iy_max = min(ny, int(math.ceil((p["y"] + p["dy"] - eps) / dy_cell)))
            iz_min = max(0, int(p["z"] / dz_cell))
            iz_max = min(nz, int(math.ceil((p["z"] + p["dz"] - eps) / dz_cell)))

            for ix in range(ix_min, ix_max):
                for iy in range(iy_min, iy_max):
                    base = ix * (ny * nz) + iy * nz
                    for iz in range(iz_min, iz_max):
                        grid[base + iz] = 1

        # 2. Door-side Flood Fill (BFS starting from ix = nx - 1)
        # 0 = Unreachable/Cavity, 1 = Occupied, 2 = Reachable Free
        door_ix = nx - 1
        queue = deque()

        for iy in range(ny):
            base = door_ix * (ny * nz) + iy * nz
            for iz in range(nz):
                if grid[base + iz] == 0:
                    grid[base + iz] = 2
                    queue.append((door_ix, iy, iz))

        nx_m1 = nx - 1
        ny_m1 = ny - 1
        nz_m1 = nz - 1

        while queue:
            cx, cy, cz = queue.popleft()

            # -X
            if cx > 0:
                nidx = (cx - 1) * (ny * nz) + cy * nz + cz
                if grid[nidx] == 0:
                    grid[nidx] = 2
                    queue.append((cx - 1, cy, cz))
            # +X
            if cx < nx_m1:
                nidx = (cx + 1) * (ny * nz) + cy * nz + cz
                if grid[nidx] == 0:
                    grid[nidx] = 2
                    queue.append((cx + 1, cy, cz))
            # -Y
            if cy > 0:
                nidx = cx * (ny * nz) + (cy - 1) * nz + cz
                if grid[nidx] == 0:
                    grid[nidx] = 2
                    queue.append((cx, cy - 1, cz))
            # +Y
            if cy < ny_m1:
                nidx = cx * (ny * nz) + (cy + 1) * nz + cz
                if grid[nidx] == 0:
                    grid[nidx] = 2
                    queue.append((cx, cy + 1, cz))
            # -Z
            if cz > 0:
                nidx = cx * (ny * nz) + cy * nz + (cz - 1)
                if grid[nidx] == 0:
                    grid[nidx] = 2
                    queue.append((cx, cy, cz - 1))
            # +Z
            if cz < nz_m1:
                nidx = cx * (ny * nz) + cy * nz + (cz + 1)
                if grid[nidx] == 0:
                    grid[nidx] = 2
                    queue.append((cx, cy, cz + 1))

        # 3. Connected Components Analysis for Enclosed Cavities (grid == 0)
        visited_cavity = bytearray(nx * ny * nz)
        cavity_count = 0
        unreachable_cell_count = 0
        reachable_cell_count = 0

        for ix in range(nx):
            for iy in range(ny):
                base = ix * (ny * nz) + iy * nz
                for iz in range(nz):
                    idx = base + iz
                    if grid[idx] == 2:
                        reachable_cell_count += 1
                    elif grid[idx] == 0:
                        unreachable_cell_count += 1
                        if visited_cavity[idx] == 0:
                            cavity_count += 1
                            # BFS connected cavity component
                            c_q = deque([(ix, iy, iz)])
                            visited_cavity[idx] = 1
                            while c_q:
                                qx, qy, qz = c_q.popleft()
                                for dx_i, dy_i, dz_i in [(-1,0,0),(1,0,0),(0,-1,0),(0,1,0),(0,0,-1),(0,0,1)]:
                                    nx_i, ny_i, nz_i = qx + dx_i, qy + dy_i, qz + dz_i
                                    if 0 <= nx_i < nx and 0 <= ny_i < ny and 0 <= nz_i < nz:
                                        n_idx = nx_i * (ny * nz) + ny_i * nz + nz_i
                                        if grid[n_idx] == 0 and visited_cavity[n_idx] == 0:
                                            visited_cavity[n_idx] = 1
                                            c_q.append((nx_i, ny_i, nz_i))

        unreachable_vol = unreachable_cell_count * cell_vol
        reachable_vol = reachable_cell_count * cell_vol

        return {
            "enclosed_cavity_count": cavity_count,
            "enclosed_cavity_volume": round(unreachable_vol, 6),
            "reachable_residual_volume": round(reachable_vol, 6),
            "dead_space_volume": round(unreachable_vol, 6),
            "sliver_volume": 0.0,
            "fragmentation_score": round((cavity_count * 0.5), 4),
        }

    # -------------------------------------------------------------------------
    # Normalizers & Helpers
    # -------------------------------------------------------------------------

    def _normalize_container(
        self,
        container: Union[ContainerSpec, Tuple[float, float, float], Dict[str, Any]],
    ) -> Tuple[float, float, float, float, float, float]:
        """Extracts (Lx, Ly, Lz, max_payload_kg, door_zone_len, rear_zone_len)."""
        if isinstance(container, ContainerSpec):
            return (
                container.Lx,
                container.Ly,
                container.Lz,
                container.max_payload_kg,
                container.door_zone_length_m,
                container.rear_zone_length_m,
            )
        elif isinstance(container, (tuple, list)):
            c_lx = float(container[0])
            c_ly = float(container[1])
            c_lz = float(container[2])
            return (c_lx, c_ly, c_lz, 0.0, 1.2, 1.0)
        elif isinstance(container, dict):
            c_lx = float(container.get("x", container.get("dx", container.get("length", 12.0))))
            c_ly = float(container.get("y", container.get("dy", container.get("width", 2.35))))
            c_lz = float(container.get("z", container.get("dz", container.get("height", 2.69))))
            max_payload = float(container.get("max_payload_kg", container.get("maxPayloadKg", 0.0)))
            door_zone_len = float(container.get("door_zone_length_m", 1.2))
            rear_zone_len = float(container.get("rear_zone_length_m", 1.0))
            return (c_lx, c_ly, c_lz, max_payload, door_zone_len, rear_zone_len)
        else:
            raise ValueError(f"Unsupported container type: {type(container)}")

    def _normalize_placements(
        self,
        placements: Union[List[Placement], List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """Normalizes placements into uniform list of canonical dictionaries."""
        norm: List[Dict[str, Any]] = []
        for i, p in enumerate(placements):
            if isinstance(p, Placement):
                norm.append({
                    "placement_id": p.placement_id,
                    "instance_id": p.instance_id,
                    "sku_id": p.sku_id,
                    "x": float(p.position.x),
                    "y": float(p.position.y),
                    "z": float(p.position.z),
                    "dx": float(p.orientation.dx),
                    "dy": float(p.orientation.dy),
                    "dz": float(p.orientation.dz),
                    "weight_kg": float(p.weight_kg),
                    "context": p.context,
                    "step_index": p.step_index,
                })
            elif isinstance(p, dict):
                x = float(p.get("x", 0.0))
                y = float(p.get("y", 0.0))
                z = float(p.get("z", 0.0))
                if "dx" in p:
                    dx, dy, dz = float(p["dx"]), float(p["dy"]), float(p["dz"])
                elif "w" in p:
                    dx, dy, dz = float(p["w"]), float(p.get("h", 0.0)), float(p.get("d", 0.0))
                elif "width" in p:
                    dx = float(p.get("length", p["width"]))
                    dy = float(p["width"])
                    dz = float(p.get("height", 0.0))
                else:
                    dx, dy, dz = 0.0, 0.0, 0.0

                weight_kg = float(p.get("weight_kg", p.get("weight", 0.0)))
                sku_id = str(p.get("sku_id", p.get("sku", f"SKU_{i}")))
                placement_id = str(p.get("placement_id", p.get("id", f"p_{i}")))
                context = p.get("context", PlacementContext.GENERAL)

                norm.append({
                    "placement_id": placement_id,
                    "instance_id": str(p.get("instance_id", f"inst_{i}")),
                    "sku_id": sku_id,
                    "x": x,
                    "y": y,
                    "z": z,
                    "dx": dx,
                    "dy": dy,
                    "dz": dz,
                    "weight_kg": weight_kg,
                    "context": context,
                    "step_index": int(p.get("step_index", i)),
                })
            else:
                raise ValueError(f"Unsupported placement type at index {i}: {type(p)}")
        return norm

    def _normalize_cargo_skus(
        self,
        cargo_list: Optional[Union[List[CargoSKU], Dict[str, CargoSKU], List[Dict[str, Any]]]],
    ) -> Optional[Dict[str, CargoSKU]]:
        """Maps SKU IDs to CargoSKU objects."""
        if cargo_list is None:
            return None
        if isinstance(cargo_list, dict):
            return cargo_list
        sku_map: Dict[str, CargoSKU] = {}
        for c in cargo_list:
            if isinstance(c, CargoSKU):
                sku_map[c.sku_id] = c
            elif isinstance(c, dict):
                pass
        return sku_map

    def _build_summary_text(
        self,
        is_valid: bool,
        rejection_reasons: List[str],
        metrics: Dict[str, Any],
        violations: List[ViolationDetail],
    ) -> str:
        """Constructs human-readable validation summary."""
        if is_valid:
            return (
                f"VALID: {metrics['placed_count']} boxes placed successfully. "
                f"Cargo Vol: {metrics['cargo_volume']:.2f} m³ ({metrics['volume_utilization_pct']:.1f}% util), "
                f"Weight: {metrics['total_cargo_weight_kg']:.1f} kg. 0 overlaps, 0 bounds violations."
            )
        else:
            reasons_str = ", ".join(rejection_reasons)
            fatal_count = sum(1 for v in violations if v.severity == ViolationSeverity.FATAL)
            return (
                f"INVALID (Rejected): {fatal_count} fatal violations detected. "
                f"Rejection Reasons: [{reasons_str}]. "
                f"Overlaps: {metrics['overlap_pair_count']}, OOB: {metrics['out_of_bounds_count']}."
            )


# Compatibility Alias for existing code
IndependentSolutionValidator = IndependentGlobalValidator
