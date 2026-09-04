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


class _HybridValidatorMethod:
    """Descriptor allowing .validate() to work seamlessly on both class and instance invocations."""

    def __get__(self, obj, cls=None):
        if obj is not None:
            def instance_validate(
                container: Union[ContainerSpec, Tuple[float, float, float], Dict[str, Any]],
                placements: Union[List[Placement], List[Dict[str, Any]]],
                cargo_list: Optional[Union[List[CargoSKU], Dict[str, CargoSKU], List[Dict[str, Any]]]] = None,
                compiled_constraints: Optional[Dict[str, Any]] = None,
                options: Optional[Dict[str, Any]] = None,
                **kwargs,
            ) -> ValidationResult:
                if "geom_epsilon" in kwargs and kwargs["geom_epsilon"] is not None:
                    obj.geom_epsilon = kwargs["geom_epsilon"]
                if "grid_resolution" in kwargs and kwargs["grid_resolution"] is not None:
                    obj.grid_resolution = kwargs["grid_resolution"]
                if "max_allowed_cavity_volume" in kwargs and kwargs["max_allowed_cavity_volume"] is not None:
                    obj.max_allowed_cavity_volume = kwargs["max_allowed_cavity_volume"]
                return obj._run_validation(
                    container=container,
                    placements=placements,
                    cargo_list=cargo_list,
                    compiled_constraints=compiled_constraints,
                    options=options,
                )
            return instance_validate
        else:
            def class_validate(
                container: Union[ContainerSpec, Tuple[float, float, float], Dict[str, Any]],
                placements: Union[List[Placement], List[Dict[str, Any]]],
                cargo_list: Optional[Union[List[CargoSKU], Dict[str, CargoSKU], List[Dict[str, Any]]]] = None,
                compiled_constraints: Optional[Dict[str, Any]] = None,
                options: Optional[Dict[str, Any]] = None,
                *,
                geom_epsilon: float = EPSILON,
                grid_resolution: float = 0.1,
                max_allowed_cavity_volume: Optional[float] = None,
                **kwargs,
            ) -> ValidationResult:
                inst = cls(
                    geom_epsilon=geom_epsilon,
                    grid_resolution=grid_resolution,
                    max_allowed_cavity_volume=max_allowed_cavity_volume,
                )
                return inst._run_validation(
                    container=container,
                    placements=placements,
                    cargo_list=cargo_list,
                    compiled_constraints=compiled_constraints,
                    options=options,
                )
            return class_validate


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

    validate = _HybridValidatorMethod()

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
            options=options,
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
        """Validates 3D box collisions and computes exact pairwise penetration volume using Sweep-and-Prune."""
        violations = []
        overlap_pairs = []
        total_overlap_vol = 0.0
        eps = self.geom_epsilon
        n = len(placements)
        if n <= 1:
            return violations, total_overlap_vol, overlap_pairs

        # 1D Sweep-and-Prune along X axis
        sorted_indices = sorted(range(n), key=lambda idx: placements[idx]["x"])

        for idx_i, i in enumerate(sorted_indices):
            p1 = placements[i]
            x1 = p1["x"]
            max_x1 = x1 + p1["dx"]
            y1 = p1["y"]
            max_y1 = y1 + p1["dy"]
            z1 = p1["z"]
            max_z1 = z1 + p1["dz"]

            for idx_j in range(idx_i + 1, n):
                j = sorted_indices[idx_j]
                p2 = placements[j]
                x2 = p2["x"]
                if x2 >= max_x1 - eps:
                    # Since list is sorted by X, no further placement can overlap along X with p1
                    break

                max_x2 = x2 + p2["dx"]
                ox = min(max_x1, max_x2) - max(x1, x2)
                if ox <= eps:
                    continue

                y2 = p2["y"]
                max_y2 = y2 + p2["dy"]
                oy = min(max_y1, max_y2) - max(y1, y2)
                if oy <= eps:
                    continue

                z2 = p2["z"]
                max_z2 = z2 + p2["dz"]
                oz = min(max_z1, max_z2) - max(z1, z2)
                if oz <= eps:
                    continue

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

            # Classify rotation type and match against allowed rules (robust to equal dimensions):
            legal = False
            matching_allowed_modes = []

            # 1. Upright: dz == bz
            if abs(dz - bz) <= eps and (
                (abs(dx - bx) <= eps and abs(dy - by) <= eps) or (abs(dx - by) <= eps and abs(dy - bx) <= eps)
            ):
                rule = policy.rule_for(OrientationMode.UPRIGHT, context)
                if rule and rule.allows(policy.context_region(context), base_height=p["z"]):
                    legal = True
                    matching_allowed_modes.append("UPRIGHT")

            # 2. Flat: dz == by
            if abs(dz - by) <= eps and (
                (abs(dx - bx) <= eps and abs(dy - bz) <= eps) or (abs(dx - bz) <= eps and abs(dy - bx) <= eps)
            ):
                rule = policy.rule_for(OrientationMode.FLAT, context)
                if rule and rule.allows(policy.context_region(context), base_height=p["z"]):
                    legal = True
                    matching_allowed_modes.append("FLAT")

            # 3. Side: dz == bx
            if abs(dz - bx) <= eps and (
                (abs(dx - by) <= eps and abs(dy - bz) <= eps) or (abs(dx - bz) <= eps and abs(dy - by) <= eps)
            ):
                rule = policy.rule_for(OrientationMode.SIDE, context)
                if rule and rule.allows(policy.context_region(context), base_height=p["z"]):
                    legal = True
                    matching_allowed_modes.append("SIDE")

            if not legal:
                violations.append(
                    ViolationDetail(
                        violation_type=ViolationType.FORBIDDEN_ORIENTATION,
                        severity=ViolationSeverity.FATAL,
                        message=f"Placement {p['placement_id']} (SKU: {sku_id}) orientation ({dx:.3f}x{dy:.3f}x{dz:.3f}) is illegal under policy for context {context}",
                        sku_id=sku_id,
                        placement_id=p["placement_id"],
                        placement_index=i,
                        location=(p["x"], p["y"], p["z"]),
                        dimension=(dx, dy, dz),
                        extra_data={"context": str(context)},
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
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[ViolationDetail], List[ViolationDetail]]:
        """
        Validates business rules and physical mechanics using vertical Z-spatial indexing:
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
        if n == 0:
            return rule_violations, stability_violations

        # 1. Door zone boundary
        door_start = max(0.0, c_lx - door_zone_len)
        has_door_skus = any(
            (s.target_zone == ZoneType.DOOR or PackingRole.DOOR_SEAL in s.packing_roles)
            for s in (sku_map.values() if sku_map else [])
        )

        # 2. Build Z-level spatial indices with continuous bin-interval querying (robust against float rounding drift)
        from collections import defaultdict
        import math
        z_bin_size = 0.01  # 10mm bin buckets
        z_contact_tol = max(1e-3, eps * 2)  # 1mm physical contact tolerance

        z_top_bins = defaultdict(list)
        z_bottom_bins = defaultdict(list)
        for idx, p in enumerate(placements):
            z_top_bins[int(math.floor((p["z"] + p["dz"]) / z_bin_size))].append(idx)
            z_bottom_bins[int(math.floor(p["z"] / z_bin_size))].append(idx)

        def get_supporting_candidates(target_z: float) -> List[int]:
            min_bin = int(math.floor((target_z - z_contact_tol) / z_bin_size))
            max_bin = int(math.floor((target_z + z_contact_tol) / z_bin_size))
            candidates = []
            for b in range(min_bin, max_bin + 1):
                for idx in z_top_bins.get(b, []):
                    p_cand = placements[idx]
                    if abs((p_cand["z"] + p_cand["dz"]) - target_z) <= z_contact_tol:
                        candidates.append(idx)
            return candidates

        def get_supported_candidates(target_top_z: float) -> List[int]:
            min_bin = int(math.floor((target_top_z - z_contact_tol) / z_bin_size))
            max_bin = int(math.floor((target_top_z + z_contact_tol) / z_bin_size))
            candidates = []
            for b in range(min_bin, max_bin + 1):
                for idx in z_bottom_bins.get(b, []):
                    p_cand = placements[idx]
                    if abs(p_cand["z"] - target_top_z) <= z_contact_tol:
                        candidates.append(idx)
            return candidates

        stack_depth_memo: Dict[int, int] = {}
        for i, p in enumerate(placements):
            sku_id = p["sku_id"]
            x, y, z = p["x"], p["y"], p["z"]
            dx, dy, dz = p["dx"], p["dy"], p["dz"]
            cargo = sku_map.get(sku_id) if sku_map else None

            # --- Zone Rules ---
            if cargo:
                # Explicit forbidden zones from CargoProfile
                if cargo.cargo_profile is not None:
                    for forbidden in cargo.cargo_profile.zone_policy.forbidden:
                        if forbidden == ZoneType.DOOR and (x + dx > door_start + eps):
                            rule_violations.append(
                                ViolationDetail(
                                    violation_type=ViolationType.ZONE_VIOLATION,
                                    severity=ViolationSeverity.FATAL,
                                    message=f"Placement {p['placement_id']} (SKU: {sku_id}) violates explicit forbidden zone DOOR",
                                    sku_id=sku_id,
                                    placement_id=p["placement_id"],
                                    placement_index=i,
                                )
                            )
                        elif forbidden == ZoneType.REAR and (x <= rear_zone_len + eps):
                            rule_violations.append(
                                ViolationDetail(
                                    violation_type=ViolationType.ZONE_VIOLATION,
                                    severity=ViolationSeverity.FATAL,
                                    message=f"Placement {p['placement_id']} (SKU: {sku_id}) violates explicit forbidden zone REAR",
                                    sku_id=sku_id,
                                    placement_id=p["placement_id"],
                                    placement_index=i,
                                )
                            )

                # Door Zone Lockout: Non-DOOR_SEAL items cannot enter [Lx - door_zone_len, Lx]
                if (
                    has_door_skus
                    and cargo.target_zone != ZoneType.DOOR
                    and PackingRole.DOOR_SEAL not in cargo.packing_roles
                    and (x + dx > door_start + eps)
                    and (cargo.cargo_profile is None or (ZoneType.DOOR not in cargo.cargo_profile.zone_policy.allowed and ZoneType.DOOR not in cargo.cargo_profile.zone_policy.preferred))
                ):
                    rule_violations.append(
                        ViolationDetail(
                            violation_type=ViolationType.DOOR_LOCKOUT_VIOLATION,
                            severity=ViolationSeverity.FATAL,
                            message=f"Placement {p['placement_id']} (SKU: {sku_id}) violates door lockout: non-door item placed in door zone [{door_start:.3f}, {c_lx:.3f}]",
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
                total_support_area = 0.0
                candidate_lowers = get_supporting_candidates(z)

                for j in candidate_lowers:
                    if i == j:
                        continue
                    p2 = placements[j]
                    ox = min(x + dx, p2["x"] + p2["dx"]) - max(x, p2["x"])
                    if ox > eps:
                        oy = min(y + dy, p2["y"] + p2["dy"]) - max(y, p2["y"])
                        if oy > eps:
                            total_support_area += ox * oy

                base_area = dx * dy
                support_ratio = min(1.0, round(total_support_area / base_area, 6)) if base_area > 0 else 0.0
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
            upper_boxes = []
            upper_weight = 0.0
            candidate_uppers = get_supported_candidates(z + dz)

            for j in candidate_uppers:
                if i == j:
                    continue
                p2 = placements[j]
                ox = min(x + dx, p2["x"] + p2["dx"]) - max(x, p2["x"])
                if ox > eps:
                    oy = min(y + dy, p2["y"] + p2["dy"]) - max(y, p2["y"])
                    if oy > eps:
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
                            message=f"Placement {p['placement_id']} (SKU: {sku_id}) bearing weight ({upper_weight:.1f} kg) exceeds limit ({max_bearing:.1f} kg)",
                            sku_id=sku_id,
                            placement_id=p["placement_id"],
                            placement_index=i,
                            extra_data={"upper_weight_kg": upper_weight, "max_bearing_kg": max_bearing},
                        )
                    )

            # 3. Surface Pressure Limit check
            if cargo and cargo.stacking_policy.max_pressure_kg_m2 is not None:
                max_pressure = cargo.stacking_policy.max_pressure_kg_m2
                pressure = upper_weight / (dx * dy) if (dx * dy) > 0 else 0.0
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

            # 4. Vertical Stack layers check (Exact DAG Longest Path DP)
            if cargo and cargo.stacking_policy.max_stack_layers is not None:
                max_layers = cargo.stacking_policy.max_stack_layers
                stack_depth = self._compute_stack_column_depth(
                    i, placements, same_sku_only=True,
                    get_supporting_fn=get_supporting_candidates, memo=stack_depth_memo
                )
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

            # 5. Gate 11: Tipping Moment and Overturning Safety Check (TIP-03)
            # Check if carton is at the exposed front (no forward neighbor) and lacks overturning stability
            check_tipping = True
            if options is not None and "tipping_moment_constraint" in options:
                check_tipping = bool(options["tipping_moment_constraint"])
            elif compiled_constraints is not None and "tipping_moment_constraint" in compiled_constraints:
                check_tipping = bool(compiled_constraints["tipping_moment_constraint"])

            if check_tipping:
                is_at_door = (x + dx >= c_lx - 0.04 - eps)
                if not is_at_door:
                    # Fast pre-check: if carton itself has SF >= 1.5, it is self-stable under 0.5g deceleration!
                    sf = (2.0 * dx / dz) if dz > 1e-6 else float("inf")
                    if sf < 1.5 - eps:
                        # Check for physical forward support from another carton touching in +X
                        has_forward_support = False
                        min_y_ov = 0.20 * dy
                        min_z_ov = 0.20 * dz
                        target_x = x + dx
                        for j, p2 in enumerate(placements):
                            if i == j:
                                continue
                            if abs(p2["x"] - target_x) <= 0.03:
                                y_ov = min(y + dy, p2["y"] + p2["dy"]) - max(y, p2["y"])
                                z_ov = min(z + dz, p2["z"] + p2["dz"]) - max(z, p2["z"])
                                if y_ov >= min_y_ov - eps and z_ov >= min_z_ov - eps:
                                    has_forward_support = True
                                    break

                        if not has_forward_support:
                            stability_violations.append(
                                ViolationDetail(
                                    violation_type=ViolationType.UNSTABLE_PLACEMENT,
                                    severity=ViolationSeverity.FATAL,
                                    message=(
                                        f"Placement {p['placement_id']} (SKU: {sku_id}) has no forward support and "
                                        f"fails tipping moment safety factor check (SF={sf:.2f} < 1.50)"
                                    ),
                                    sku_id=sku_id,
                                    placement_id=p["placement_id"],
                                    placement_index=i,
                                    extra_data={"safety_factor": sf, "min_safety_factor": 1.5},
                                )
                            )

        return rule_violations, stability_violations

    def _compute_stack_column_depth(
        self,
        index: int,
        placements: List[Dict[str, Any]],
        same_sku_only: bool = False,
        get_supporting_fn: Optional[Any] = None,
        memo: Optional[Dict[int, int]] = None,
    ) -> int:
        """
        Computes the maximum continuous vertical same-SKU stack chain height supporting ``index``
        via DAG dynamic programming (longest path traversal).
        """
        if memo is not None and index in memo:
            return memo[index]

        p = placements[index]
        x, y, z = p["x"], p["y"], p["z"]
        dx, dy = p["dx"], p["dy"]
        sku_id = p["sku_id"]
        eps = self.geom_epsilon

        if z <= eps:
            if memo is not None:
                memo[index] = 1
            return 1

        max_lower_depth = 0
        candidates = get_supporting_fn(z) if get_supporting_fn is not None else range(len(placements))
        for j in candidates:
            if j == index:
                continue
            p2 = placements[j]
            if same_sku_only and p2["sku_id"] != sku_id:
                continue
            ox = min(x + dx, p2["x"] + p2["dx"]) - max(x, p2["x"])
            if ox > eps:
                oy = min(y + dy, p2["y"] + p2["dy"]) - max(y, p2["y"])
                if oy > eps:
                    overlap_area = ox * oy
                    min_base = min(dx * dy, p2["dx"] * p2["dy"])
                    if overlap_area >= 0.15 * min_base:
                        depth_j = self._compute_stack_column_depth(
                            j, placements, same_sku_only=same_sku_only,
                            get_supporting_fn=get_supporting_fn, memo=memo
                        )
                        if depth_j > max_lower_depth:
                            max_lower_depth = depth_j

        res = 1 + max_lower_depth
        if memo is not None:
            memo[index] = res
        return res

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
        Fast-paths when enclosed cavity constraint is not active.
        """
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

        # 1. Define 3D voxel grid resolution and dimensions
        res_step = max(0.01, float(self.grid_resolution))
        nx = max(1, int(math.ceil(c_lx / res_step)))
        ny = max(1, int(math.ceil(c_ly / res_step)))
        nz = max(1, int(math.ceil(c_lz / res_step)))
        dx_cell = c_lx / nx
        dy_cell = c_ly / ny
        dz_cell = c_lz / nz
        cell_vol = dx_cell * dy_cell * dz_cell

        # 2. Rasterize placements onto 3D grid: 0 = Free, 1 = Occupied
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
        if hasattr(container, "Lx") and hasattr(container, "Ly") and hasattr(container, "Lz"):
            return (
                float(container.Lx),
                float(container.Ly),
                float(container.Lz),
                float(getattr(container, "max_payload_kg", 26000.0)),
                float(getattr(container, "door_zone_length_m", 1.2)),
                float(getattr(container, "rear_zone_length_m", 1.0)),
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
            if hasattr(p, "position") and hasattr(p, "orientation"):
                raw_ctx = getattr(p, "context", PlacementContext.GENERAL)
                if isinstance(raw_ctx, str):
                    upper_ctx = raw_ctx.upper()
                    if "TOP" in upper_ctx:
                        context = PlacementContext.TOP_FILL
                    elif "DOOR" in upper_ctx:
                        context = PlacementContext.DOOR_SEAL
                    elif "GAP" in upper_ctx or "CAVITY" in upper_ctx:
                        context = PlacementContext.GAP_FILL
                    else:
                        context = PlacementContext.GENERAL
                else:
                    context = raw_ctx
                norm.append({
                    "placement_id": getattr(p, "placement_id", f"p_{i}"),
                    "instance_id": getattr(p, "instance_id", f"inst_{i}"),
                    "sku_id": getattr(p, "sku_id", ""),
                    "x": float(p.position.x),
                    "y": float(p.position.y),
                    "z": float(p.position.z),
                    "dx": float(p.orientation.dx),
                    "dy": float(p.orientation.dy),
                    "dz": float(p.orientation.dz),
                    "weight_kg": float(getattr(p, "weight_kg", 0.0)),
                    "context": context,
                    "step_index": getattr(p, "step_index", i + 1),
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
                raw_ctx = p.get("context", p.get("tag", PlacementContext.GENERAL))
                if isinstance(raw_ctx, str):
                    upper_ctx = raw_ctx.upper()
                    if "TOP" in upper_ctx:
                        context = PlacementContext.TOP_FILL
                    elif "DOOR" in upper_ctx:
                        context = PlacementContext.DOOR_SEAL
                    elif "GAP" in upper_ctx or "CAVITY" in upper_ctx:
                        context = PlacementContext.GAP_FILL
                    else:
                        context = PlacementContext.GENERAL
                else:
                    context = raw_ctx

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
