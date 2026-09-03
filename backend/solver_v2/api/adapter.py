"""
Solver V2 Input & Output Adapters
Translates raw legacy/UI manifests into canonical Domain models (CargoSKU, ContainerSpec).
IMPORTANT: Free-text normalization and Chinese requirement string parsing is strictly confined to this adapter layer.
Solver Core receives ONLY strongly typed objects and Enums.
"""
import re
import time
from typing import Dict, Any, List, Optional, Tuple

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoClass,
    CargoProfile,
    CargoSKU,
    CompressionPolicy,
    ContainerSpec,
    GeometryPolicy,
    HandlingPolicy,
    OrientationPolicy,
    OrientationRule,
    OrientationMode,
    OrientationRegion,
    PackingRole,
    PlacementPolicy,
    PlacementContext,
    PolicySource,
    QuantityPlan,
    StackingPolicy,
    StabilityPolicy,
    TopFillPolicy,
    TopFillAdmissionState,
    ZonePolicy,
    ZoneType,
)


class InputNormalizer:
    """
    Normalizes legacy/UI inputs (dimensions, weights, requirements).
    """

    @staticmethod
    def normalize_box_dim(source: Dict[str, Any]) -> BoxDim:
        """
        Normalizes product length/width/height into canonical container axes (x >= y).
        """
        if "dimensions" in source:
            d = source["dimensions"]
            first = float(d["length"])
            second = float(d["width"])
            height = float(d["height"])
        else:
            first = float(source.get("w", source.get("x", 0.1)))
            second = float(source.get("d", source.get("y", 0.1)))
            height = float(source.get("h", source.get("z", 0.1)))
        return BoxDim(
            x=max(first, second),
            y=min(first, second),
            z=height,
        )

    @staticmethod
    def parse_zone_and_roles(requirement_text: str) -> Tuple[Optional[ZoneType], Tuple[PackingRole, ...]]:
        """
        Parses Chinese / English free-text requirements into canonical ZoneType and PackingRoles.
        Core solver must NOT call this function or parse strings directly.
        """
        req = (requirement_text or "").strip()
        zone: Optional[ZoneType] = None
        roles: List[PackingRole] = []

        # 1. Rear / Inner wall detection
        if re.search(r'最里面|最内|后部|rear|deep|inner', req, re.IGNORECASE):
            roles.append(PackingRole.FOUNDATION)
            zone = ZoneType.REAR

        # 2. Door seal detection
        elif re.search(r'封柜门|封门|门端|门区|door|front', req, re.IGNORECASE):
            roles.append(PackingRole.DOOR_SEAL)
            zone = ZoneType.DOOR

        # 3. Middle / Central detection
        elif re.search(r'放中间|中间|中部|mid|middle|center', req, re.IGNORECASE):
            roles.append(PackingRole.MAIN_WALL)
            zone = ZoneType.MIDDLE

        if not roles:
            roles.append(PackingRole.MAIN_WALL)

        return zone, tuple(roles)

    @staticmethod
    def parse_elasticity(requirement_text: str, is_elastic_flag: Optional[bool] = None) -> bool:
        """
        Detects if cargo quantity is flexible / elastic.
        """
        if is_elastic_flag is not None:
            return bool(is_elastic_flag)
        req = (requirement_text or "").strip()
        return bool(re.search(r'可以少放|可以减少|可减少|调节|按需|flexible|elastic', req, re.IGNORECASE))

    @staticmethod
    def parse_orientation_policy(raw_item: Dict[str, Any]) -> OrientationPolicy:
        """
        Constructs canonical OrientationPolicy based on legacy orientation flags.
        """
        allow_flat = bool(raw_item.get('allowFlat', False))
        allow_side = bool(raw_item.get('allowSide', False))
        allowed_ori = raw_item.get('allowedOrientation', 'upright')

        if allowed_ori == 'allow_flat':
            allow_flat = True
        elif allowed_ori == 'allow_side':
            allow_side = True
        elif allowed_ori == 'any':
            allow_flat = True
            allow_side = True

        explicit_rules = []
        for raw_rule in raw_item.get('orientationRules', ()):
            try:
                explicit_rules.append(OrientationRule(
                    orientation=OrientationMode(str(raw_rule['orientation']).upper()),
                    allowed_regions=tuple(
                        OrientationRegion(str(region).upper())
                        for region in raw_rule.get('allowedRegions', ())
                    ),
                    min_support_ratio=(float(raw_rule['minSupportRatio']) if raw_rule.get('minSupportRatio') is not None else None),
                    max_top_fill_layers=(int(raw_rule['maxTopFillLayers']) if raw_rule.get('maxTopFillLayers') is not None else None),
                    max_base_height=(float(raw_rule['maxBaseHeight']) if raw_rule.get('maxBaseHeight') is not None else None),
                    min_base_height=(float(raw_rule['minBaseHeight']) if raw_rule.get('minBaseHeight') is not None else None),
                    condition=str(raw_rule.get('condition', 'ALWAYS')).upper(),
                ))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid orientationRules entry: {raw_rule!r}") from exc

        return OrientationPolicy(
            allow_upright=True,
            allow_flat=allow_flat,
            allow_side=allow_side,
            allowed_contexts_for_flat=(PlacementContext.TOP_FILL, PlacementContext.GAP_FILL, PlacementContext.DOOR_SEAL),
            allowed_contexts_for_side=(PlacementContext.GAP_FILL, PlacementContext.DOOR_SEAL),
            max_flat_stack_layers=int(raw_item.get('maxFlatLayers', 1)),
            rules=tuple(explicit_rules),
        )

    @staticmethod
    def parse_stacking_policy(raw_item: Dict[str, Any]) -> StackingPolicy:
        """
        Constructs canonical StackingPolicy.
        """
        max_layers = raw_item.get('maxStackLayers')
        if max_layers is None:
            max_layers = raw_item.get('max_stack_layers')
        if max_layers is None:
            max_layers = raw_item.get('max_stack')
        if max_layers is not None:
            max_layers = int(max_layers)

        # Legacy maxStackWeight or maxBearingKg
        max_bearing = raw_item.get('maxBearingKg')
        if max_bearing is None:
            max_bearing = raw_item.get('maxStackWeight')
        if max_bearing is not None:
            max_bearing = float(max_bearing)

        max_pressure = raw_item.get('maxPressureKgM2')
        if max_pressure is not None:
            max_pressure = float(max_pressure)

        return StackingPolicy(
            max_stack_layers=max_layers,
            max_bearing_kg=max_bearing,
            max_pressure_kg_m2=max_pressure,
            min_support_ratio=float(raw_item.get('minSupportRatio', 0.70)),
            max_unsupported_span_m=float(raw_item.get('maxUnsupportedSpanM', 0.10)),
            allow_stacking_on_top=bool(raw_item.get('allowStackingOnTop', True)),
            must_be_on_floor=bool(raw_item.get('mustBeOnFloor', False)),
        )

    @staticmethod
    def parse_cargo_profile(raw: Dict[str, Any]) -> CargoProfile:
        """Parse an explicit profile without consulting names, dimensions, or requirement text."""
        def source(policy: Dict[str, Any]) -> PolicySource:
            return PolicySource(str(policy.get("source", "DEFAULT")).upper())

        geometry = raw.get("geometryPolicy", {})
        orientation = raw.get("orientationPolicy", {})
        placement = raw.get("placementPolicy", {})
        stack = raw.get("stackPolicy", {})
        compression = raw.get("compressionPolicy", {})
        stability = raw.get("stabilityPolicy", {})
        topfill = raw.get("topFillPolicy", {})
        zone = raw.get("zonePolicy", {})
        handling = raw.get("handlingPolicy", {})

        source_audit = []
        for policy_name, policy in (
            ("geometryPolicy", geometry), ("orientationPolicy", orientation),
            ("placementPolicy", placement), ("stackPolicy", stack),
            ("compressionPolicy", compression), ("stabilityPolicy", stability),
            ("topFillPolicy", topfill), ("zonePolicy", zone),
            ("handlingPolicy", handling),
        ):
            policy_source = source(policy)
            for key in policy:
                if key not in ("source", "fieldSources"):
                    field_source = policy.get("fieldSources", {}).get(key, policy_source.value)
                    source_audit.append((f"{policy_name}.{key}", PolicySource(str(field_source).upper())))

        rules = []
        for entry in orientation.get("rules", ()):
            raw_regions = entry.get("allowedRegions", ())
            regions = []
            for value in raw_regions:
                normalized = str(value).upper()
                if normalized == "DOOR_SPECIAL":
                    normalized = "DOOR_ZONE"
                regions.append(OrientationRegion(normalized))
            rules.append(OrientationRule(
                orientation=OrientationMode(str(entry["orientation"]).upper()),
                allowed_regions=tuple(regions),
                min_support_ratio=(float(entry["minSupportRatio"]) if entry.get("minSupportRatio") is not None else None),
                max_top_fill_layers=(int(entry["maxTopFillLayers"]) if entry.get("maxTopFillLayers") is not None else None),
                max_base_height=(float(entry["maxBaseHeight"]) if entry.get("maxBaseHeight") is not None else None),
                min_base_height=(float(entry["minBaseHeight"]) if entry.get("minBaseHeight") is not None else None),
                condition=str(entry.get("condition", "ALWAYS")).upper(),
            ))
        orientation_policy = OrientationPolicy(
            rules=tuple(rules),
            max_flat_stack_layers=int(orientation.get("maxFlatLayers", 1)),
            source=source(orientation),
        )

        stability_policy = StabilityPolicy(
            source=source(stability),
            anti_tip_required=bool(stability.get("antiTipRequired", True)),
            min_support_ratio=float(stability.get("minSupportRatio", 0.70)),
            max_unsupported_span_m=float(stability.get("maxUnsupportedSpan", 0.10)),
            group_stability_required=bool(stability.get("groupStabilityRequired", True)),
            wall_stability_required=bool(stability.get("wallStabilityRequired", True)),
        )
        compression_policy = CompressionPolicy(
            source=source(compression),
            max_top_load_kg=(float(compression["maxTopLoad"]) if compression.get("maxTopLoad") is not None else None),
            max_pressure_kg_m2=(float(compression["maxPressureKgM2"]) if compression.get("maxPressureKgM2") is not None else None),
        )
        stack_policy = StackingPolicy(
            max_stack_layers=(int(stack["maxStackLayers"]) if stack.get("maxStackLayers") is not None else None),
            max_bearing_kg=compression_policy.max_top_load_kg,
            max_pressure_kg_m2=compression_policy.max_pressure_kg_m2,
            min_support_ratio=stability_policy.min_support_ratio,
            max_unsupported_span_m=stability_policy.max_unsupported_span_m,
            allow_stacking_on_top=bool(stack.get("allowStackingOnTop", True)),
            must_be_on_floor=bool(stack.get("mustBeOnFloor", False)),
            stack_on_self=bool(stack.get("stackOnSelf", True)),
            allowed_above_categories=tuple(CargoClass(str(v).upper()) for v in stack.get("allowedAboveCategories", ())),
            forbidden_above_categories=tuple(CargoClass(str(v).upper()) for v in stack.get("forbiddenAboveCategories", ())),
            source=source(stack),
        )
        placement_policy = PlacementPolicy(
            source=source(placement),
            load_priority=int(placement.get("loadPriority", 0)),
            reduction_allowed=bool(placement.get("reductionAllowed", False)),
            minimum_quantity=int(placement.get("minimumQuantity", 0)),
            packing_roles=tuple(PackingRole(str(v).upper()) for v in placement.get("packingRoles", ("MAIN_WALL",))),
        )
        zone_policy = ZonePolicy(
            source=source(zone),
            preferred=tuple(ZoneType(str(v).upper()) for v in zone.get("preferred", ())),
            required=tuple(ZoneType(str(v).upper()) for v in zone.get("required", ())),
            forbidden=tuple(ZoneType(str(v).upper()) for v in zone.get("forbidden", ())),
        )
        topfill_policy = TopFillPolicy(
            source=source(topfill),
            admission_state=TopFillAdmissionState(str(topfill.get(
                "state",
                "ALLOW" if topfill.get("enabled", False) else (
                    "AUTO" if source(topfill) == PolicySource.DEFAULT else "DENY"
                ),
            )).upper()),
            enabled=bool(topfill.get("enabled", False)),
            allowed_orientations=tuple(OrientationMode(str(v).upper()) for v in topfill.get("allowedOrientations", ())),
            conditional_orientations=tuple(OrientationMode(str(v).upper()) for v in topfill.get("conditionalOrientations", ())),
            max_layers=int(topfill.get("maxLayers", 0)),
            min_base_height=float(topfill.get("minBaseHeight", 0.0)),
            min_support_ratio=float(topfill.get("minSupportRatio", stability_policy.min_support_ratio)),
            residual_height_target=(float(topfill["residualHeightTarget"]) if topfill.get("residualHeightTarget") is not None else None),
        )
        return CargoProfile(
            geometry_policy=GeometryPolicy(source=source(geometry), clearance_m=float(geometry.get("clearanceM", 0.0))),
            orientation_policy=orientation_policy,
            placement_policy=placement_policy,
            stack_policy=stack_policy,
            compression_policy=compression_policy,
            stability_policy=stability_policy,
            top_fill_policy=topfill_policy,
            zone_policy=zone_policy,
            handling_policy=HandlingPolicy(
                source=source(handling),
                keep_upright=bool(handling.get("keepUpright", True)),
                fragile=bool(handling.get("fragile", False)),
                special_instructions=tuple(str(v) for v in handling.get("specialInstructions", ())),
            ),
            source_audit=tuple(source_audit),
        )


class InputAdapter:
    """
    Translates raw input payload into canonical ContainerSpec and CargoSKUs.
    """

    @staticmethod
    def parse_container(raw_container: Dict[str, Any]) -> ContainerSpec:
        """
        Extracts container dimensions and parameters into canonical ContainerSpec.
        Handles both usable {L, W, H} and inner {x, y, z}.
        Canonical: x = length (L), y = width (W), z = height (H)
        """
        code = raw_container.get('code') or raw_container.get('type') or 'CONTAINER'
        
        # Dimensions
        if 'usable' in raw_container:
            usable = raw_container['usable']
            x = float(usable['L'])
            y = float(usable['W'])
            z = float(usable['H'])
        elif 'inner' in raw_container:
            inner = raw_container['inner']
            x = float(inner['x'])
            y = float(inner['y'])
            z = float(inner['z'])
        else:
            x = float(raw_container.get('L', raw_container.get('x', 12.032)))
            y = float(raw_container.get('W', raw_container.get('y', 2.352)))
            z = float(raw_container.get('H', raw_container.get('z', 2.698)))

        # Max payload
        max_payload_kg = 26500.0
        if 'maxPayloadKg' in raw_container:
            max_payload_kg = float(raw_container['maxPayloadKg'])
        elif 'maxPayloadTons' in raw_container:
            max_payload_kg = float(raw_container['maxPayloadTons']) * 1000.0

        return ContainerSpec(
            code=str(code),
            inner_dim=BoxDim(x=x, y=y, z=z),
            max_payload_kg=max_payload_kg,
            door_zone_length_m=float(raw_container.get('doorZoneLengthM', 1.2)),
            rear_zone_length_m=float(raw_container.get('rearZoneLengthM', 1.0))
        )

    @staticmethod
    def parse_cargo_list(
        raw_manifest: List[Dict[str, Any]],
        cargo_profiles: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[CargoSKU]:
        """
        Extracts and normalizes raw manifest items into a list of canonical CargoSKU instances.
        """
        cargo_skus: List[CargoSKU] = []

        for item in raw_manifest:
            # Handle nested source (devkit format) or flat format (legacy test_suite format)
            src = item.get('source', item)
            sku_id = str(item.get('sku', src.get('sku', f"SKU-{len(cargo_skus)+1:02d}")))
            name = str(item.get('name', src.get('name', sku_id)))

            # Normalize product L/W/H before mapping onto canonical X/Y/Z.
            box = InputNormalizer.normalize_box_dim(src)

            # Weight (in kg)
            weight_kg = float(src.get('weight', src.get('weightKg', 1.0)))

            profile_ref = item.get('cargoProfileRef', src.get('cargoProfileRef'))
            if profile_ref is not None:
                if cargo_profiles is None:
                    # Legacy callers historically pass only the cargo array. Keep that
                    # compatibility path isolated; canonical dataset loaders pass the
                    # profile registry and never consume requirement text.
                    profile_raw = None
                elif profile_ref not in cargo_profiles:
                    raise ValueError(f"Unknown cargoProfileRef for {sku_id}: {profile_ref!r}")
                else:
                    profile_raw = cargo_profiles[profile_ref]
            else:
                profile_raw = item.get('cargoProfile', src.get('cargoProfile'))
            profile = InputNormalizer.parse_cargo_profile(profile_raw) if profile_raw is not None else None

            # Quantity
            req_qty = int(src.get('quantity', src.get('qty', 1)))
            req_text = str(src.get('requirement', ''))
            if profile is not None:
                is_elastic = profile.placement_policy.reduction_allowed
                min_qty = (
                    profile.placement_policy.minimum_quantity
                    if is_elastic else max(profile.placement_policy.minimum_quantity, req_qty)
                )
            else:
                is_elastic = InputNormalizer.parse_elasticity(req_text, item.get('isElastic', src.get('isElastic')))
                min_qty = int(src.get('minQuantity', 0 if is_elastic else req_qty))
            quantity = QuantityPlan(
                required=req_qty,
                min_quantity=min_qty,
                max_quantity=src.get('maxQuantity'),
                is_elastic=is_elastic
            )

            # Parse Requirement Text (Adapter-only!)
            if profile is not None:
                zones = profile.zone_policy.required or profile.zone_policy.preferred
                zone = zones[0] if zones else None
                roles = profile.placement_policy.packing_roles
            else:
                zone, roles = InputNormalizer.parse_zone_and_roles(req_text)
            
            # If explicit door zone allowance was given in legacy flag
            if item.get('allowDoorZone') or src.get('allowDoorZone'):
                if PackingRole.DOOR_SEAL not in roles:
                    roles = roles + (PackingRole.DOOR_SEAL,)

            # Policies
            ori_policy = profile.orientation_policy if profile is not None else InputNormalizer.parse_orientation_policy(src)
            stack_policy = profile.stack_policy if profile is not None else InputNormalizer.parse_stacking_policy(src)

            # Color
            color_hex = item.get('color', src.get('color'))
            if color_hex is not None:
                color_hex = int(color_hex)

            cargo = CargoSKU(
                sku_id=sku_id,
                name=name,
                box=box,
                weight_kg=weight_kg,
                quantity=quantity,
                orientation_policy=ori_policy,
                stacking_policy=stack_policy,
                cargo_class=CargoClass.STANDARD,
                packing_roles=roles,
                target_zone=zone,
                color_hex=color_hex,
                source_requirement_text=req_text,
                cargo_profile=profile,
            )
            cargo_skus.append(cargo)

        return cargo_skus


class OutputAdapter:
    """
    Translates Solver V2 canonical solutions into standard V2 API schemas and frontend / legacy visualizer formats.
    Strictly adheres to contracts/API_V2.md and contracts/COORDINATES.md.
    """

    @staticmethod
    def to_v2_response(
        solution: Any,
        container: Optional[ContainerSpec] = None,
        cargo_list: Optional[List[CargoSKU]] = None,
        solution_id: Optional[str] = None,
        version: int = 1,
        warnings: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Formats Solver V2 Solution according to contracts/API_V2.md and schemas/solution_v2.schema.json.
        Canonical Coordinates:
          x: longitudinal / inner wall -> doors [0, Lx]
          y: lateral / width [0, Ly]
          z: vertical / floor -> roof [0, Lz]
        """
        if solution is None:
            return {
                "solutionId": solution_id or "sol_empty",
                "version": version,
                "solverVersion": "v2.0.0",
                "placements": [],
                "unloaded": [],
                "metrics": {
                    "volumeUtilizationPct": 0.0,
                    "totalWeightKg": 0.0,
                    "placedCount": 0,
                    "unplacedCount": 0,
                },
                "telemetry": {},
                "warnings": warnings or ["Empty solution provided"],
            }

        sid = solution_id or getattr(solution, "solution_id", f"sol_{int(time.time()*1000)}")
        sol_version = version

        placements_data = []
        placed_sku_counts: Dict[str, int] = {}
        total_weight = 0.0
        used_volume = 0.0

        # Compute CoG accumulators
        sum_wx = 0.0
        sum_wy = 0.0
        sum_wz = 0.0

        for p in getattr(solution, "placements", []):
            pos_x = float(p.position.x)
            pos_y = float(p.position.y)
            pos_z = float(p.position.z)
            dx = float(p.orientation.dx)
            dy = float(p.orientation.dy)
            dz = float(p.orientation.dz)
            w_kg = float(p.weight_kg)
            vol = dx * dy * dz

            total_weight += w_kg
            used_volume += vol
            placed_sku_counts[p.sku_id] = placed_sku_counts.get(p.sku_id, 0) + 1

            # Centroid of box
            cx = pos_x + dx / 2.0
            cy = pos_y + dy / 2.0
            cz = pos_z + dz / 2.0
            sum_wx += cx * w_kg
            sum_wy += cy * w_kg
            sum_wz += cz * w_kg

            placements_data.append({
                "placementId": p.placement_id,
                "instanceId": p.instance_id,
                "skuId": p.sku_id,
                "x": round(pos_x, 4),
                "y": round(pos_y, 4),
                "z": round(pos_z, 4),
                "dx": round(dx, 4),
                "dy": round(dy, 4),
                "dz": round(dz, 4),
                "weightKg": round(w_kg, 2),
                "context": p.context.value if hasattr(p.context, "value") else str(p.context),
                "stepIndex": getattr(p, "step_index", 0),
            })

        # Build unloaded list
        unloaded_data = []
        if cargo_list:
            for s in cargo_list:
                placed = placed_sku_counts.get(s.sku_id, 0)
                rem = max(0, s.quantity.required - placed)
                if rem > 0:
                    unloaded_data.append({
                        "skuId": s.sku_id,
                        "name": s.name,
                        "unloadedCount": rem,
                        "requiredCount": s.quantity.required,
                        "isElastic": s.quantity.is_elastic,
                    })

        # Container specs and volume
        cont_vol = container.volume if container else (12.032 * 2.352 * 2.698)
        cont_lx = container.Lx if container else 12.032
        cont_ly = container.Ly if container else 2.352
        cont_lz = container.Lz if container else 2.698
        max_payload = container.max_payload_kg if container else 26500.0

        vol_util = round((used_volume / cont_vol) * 100.0, 2) if cont_vol > 0 else 0.0

        # Center of gravity metrics
        if total_weight > 0:
            cog_x = sum_wx / total_weight
            cog_y = sum_wy / total_weight
            cog_z = sum_wz / total_weight
            mid_y = cont_ly / 2.0
            mid_x = cont_lx / 2.0
            lat_offset_pct = abs((cog_y - mid_y) / cont_ly) * 100.0 if cont_ly > 0 else 0.0
            long_offset_pct = ((cog_x - mid_x) / cont_lx) * 100.0 if cont_lx > 0 else 0.0
        else:
            cog_x, cog_y, cog_z = cont_lx / 2.0, cont_ly / 2.0, cont_lz / 2.0
            lat_offset_pct = 0.0
            long_offset_pct = 0.0

        metrics = {
            "volumeUtilizationPct": vol_util,
            "usedVolumeM3": round(used_volume, 3),
            "containerVolumeM3": round(cont_vol, 3),
            "totalWeightKg": round(total_weight, 2),
            "totalWeightTons": round(total_weight / 1000.0, 2),
            "maxPayloadKg": max_payload,
            "isOverweight": total_weight > max_payload,
            "placedCount": len(placements_data),
            "unplacedCount": sum(item["unloadedCount"] for item in unloaded_data),
            "cog": {
                "x": round(cog_x, 3),
                "y": round(cog_y, 3),
                "z": round(cog_z, 3),
                "latOffsetPercent": round(lat_offset_pct, 1),
                "longOffsetPercent": round(long_offset_pct, 1),
                "isLatBalanced": lat_offset_pct <= 5.0,
                "isLongBalanced": abs(long_offset_pct) <= 10.0,
            },
        }

        # Telemetry
        raw_telemetry = getattr(solution, "telemetry", None)
        telemetry_data = raw_telemetry.to_dict() if hasattr(raw_telemetry, "to_dict") else (raw_telemetry or {})

        val_result = getattr(solution, "validation_result", None)
        warn_list = list(warnings or [])
        if val_result and not getattr(val_result, "is_valid", True):
            for rej in getattr(val_result, "rejection_reasons", []):
                warn_list.append(f"Validation warning: {rej}")

        return {
            "solutionId": sid,
            "version": sol_version,
            "solverVersion": "v2.0.0",
            "placements": placements_data,
            "unloaded": unloaded_data,
            "metrics": metrics,
            "telemetry": telemetry_data,
            "warnings": warn_list,
        }

    @staticmethod
    def to_legacy_response(
        solution: Any,
        container: Optional[ContainerSpec] = None,
        cargo_list: Optional[List[CargoSKU]] = None,
        version: int = 1,
        elapsed_ms: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Converts canonical solution to Three.js visualizer response format.
        Maps canonical placements to legacy 'placedBoxes' with color, name, and visual coords.
        """
        v2_resp = OutputAdapter.to_v2_response(
            solution=solution,
            container=container,
            cargo_list=cargo_list,
            version=version,
        )

        sku_meta_map: Dict[str, Dict[str, Any]] = {}
        if cargo_list:
            for s in cargo_list:
                sku_meta_map[s.sku_id] = {
                    "name": s.name,
                    "color": s.color_hex if s.color_hex is not None else 0x3b82f6,
                    "requirement": s.source_requirement_text or "放中间",
                }

        # Build placedBoxes for Three.js visualizer
        # In legacy format:
        # x: longitudinal [0, Lx]
        # y: vertical / height [0, Lz]  (Note: In legacy packer, item.y was height)
        # z: lateral / width [0, Ly]     (Note: In legacy packer, item.z was width)
        # w: dx (along x)
        # h: dz (along z - height)
        # d: dy (along y - width)
        placed_boxes = []
        for p in getattr(solution, "placements", []):
            meta = sku_meta_map.get(p.sku_id, {})
            # Canonical: x=longitudinal, y=width, z=height, dx, dy, dz
            # Legacy expected placedBox:
            # x = canonical x
            # y = canonical z (height from floor)
            # z = canonical y (lateral from left)
            # w = canonical dx (longitudinal length)
            # h = canonical dz (height)
            # d = canonical dy (lateral width)
            placed_boxes.append({
                "id": p.placement_id,
                "sku": p.sku_id,
                "name": meta.get("name", p.sku_id),
                "color": meta.get("color", 0x3b82f6),
                "weight": round(p.weight_kg, 2),
                "requirement": meta.get("requirement", "放中间"),
                "x": round(p.position.x, 4),
                "y": round(p.position.z, 4),
                "z": round(p.position.y, 4),
                "w": round(p.orientation.dx, 4),
                "h": round(p.orientation.dz, 4),
                "d": round(p.orientation.dy, 4),
                "stepIndex": getattr(p, "step_index", 0),
                "context": p.context.value if hasattr(p.context, "value") else str(p.context),
                # Also include canonical coords for V2-aware visualizers
                "canonical": {
                    "x": round(p.position.x, 4),
                    "y": round(p.position.y, 4),
                    "z": round(p.position.z, 4),
                    "dx": round(p.orientation.dx, 4),
                    "dy": round(p.orientation.dy, 4),
                    "dz": round(p.orientation.dz, 4),
                }
            })

        metrics = v2_resp["metrics"]
        cog = metrics["cog"]

        return {
            "success": True,
            "status": "success",
            "solverVersion": "v2.0.0",
            "solutionId": v2_resp["solutionId"],
            "version": v2_resp["version"],
            "totalCount": metrics["placedCount"],
            "totalPlaced": metrics["placedCount"],
            "totalUnplacedCount": metrics["unplacedCount"],
            "totalCollisions": 0,
            "usedVol": metrics["usedVolumeM3"],
            "utilization": metrics["volumeUtilizationPct"],
            "totalMassKg": metrics["totalWeightKg"],
            "totalWeightTons": metrics["totalWeightTons"],
            "maxPayloadKg": metrics["maxPayloadKg"],
            "isOverweight": metrics["isOverweight"],
            "cog": cog,
            "constraints": {
                "doorZoneViolations": 0,
                "pressureBlocked": 0,
                "supportBlocked": 0,
            },
            "flatness": {
                "maxWallGap": 0.0,
                "topNotchCount": 0,
                "maxTopGap": 0.0,
            },
            "placedBoxes": placed_boxes,
            "placements": v2_resp["placements"],
            "unloaded": v2_resp["unloaded"],
            "metrics": v2_resp["metrics"],
            "telemetry": v2_resp["telemetry"],
            "warnings": v2_resp["warnings"],
            "elapsedMs": round(elapsed_ms if elapsed_ms > 0 else v2_resp["telemetry"].get("runtime_ms", 0.0), 2),
        }
