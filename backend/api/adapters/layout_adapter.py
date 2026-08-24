"""Frozen placement layout -> frontend product model."""
from collections import Counter
import re

from backend.solver_v2.structure.wall_model import WallStructureAnalyzer
from src.cargo.intelligence import CargoProfileEngine
from src.cargo.dimension_normalization import DimensionNormalizer


def _color(value):
    return f"#{(value if value is not None else 0x3B82F6):06X}"


class LayoutAdapter:
    @staticmethod
    def container(container):
        dimensions={"length":container.Lx,"width":container.Ly,"height":container.Lz,"unit":"m"}
        return {
            "type":container.code,"dimension":dict(dimensions),"internal":dict(dimensions),
            "door":{"plane_x":container.Lx,"width":container.Ly,"height":container.Lz,"zone_length":container.door_zone_length_m},
            "coordinate_system":{"origin":"container_back_bottom_left","handedness":"right_handed",
                "axis":{"x":"length_back_to_door","y":"width_left_to_right","z":"height_floor_to_roof"},"unit":"m"},
        }

    @staticmethod
    def membership(placements,container):
        result={}
        for wall in WallStructureAnalyzer(container).extract_walls(list(placements)):
            for layer in wall.layers:
                for p in layer.placements:result.setdefault(p.placement_id,{})["layer_id"]=layer.layer_id
            for row in wall.rows:
                for p in row.placements:result.setdefault(p.placement_id,{}).update({"wall_id":wall.wall_id,"row_id":row.row_id})
        return result

    @classmethod
    def cargo(cls,placements,cargo,container,plan,repair_groups,recomposition=None):
        catalog={s.sku_id:s for s in cargo};membership=cls.membership(placements,container)
        intelligence=CargoProfileEngine().profile_all(cargo);dimension_normalizer=DimensionNormalizer()
        step_by_pid={pid:s.step_index for s in plan.steps for pid in s.placement_ids}
        step_meta={pid:s for s in plan.steps for pid in s.placement_ids}
        group_by_pid={pid:g for g in repair_groups for pid in g.placement_ids}
        recomposition_by_id={x["cargo_id"]:x for x in (recomposition or {}).get("selected_swaps",[])}
        rows=[]
        for p in placements:
            sku=catalog[p.sku_id];member=membership.get(p.placement_id,{})
            step=step_meta.get(p.placement_id)
            role=("DOOR_WALL" if p.placement_id.startswith("door_pre_") else
                  "TRANSITION_WALL" if p.placement_id.startswith("transition_wall_") else
                  "CARGO_WALL" if p.placement_id.startswith("cargo_wall_") else
                  "TOP_BRIDGE" if p.placement_id.startswith("top_bridge_") else
                  "LAYER_COMPLETION" if p.placement_id.startswith("layer_complete_") else
                  "REPAIR_GROUP" if p.placement_id in group_by_pid else
                  "TOP_FILL" if p.context.value=="TOP_FILL" else "MAIN_CARGO")
            profile=intelligence[p.sku_id]
            orientation_used=("FLAT" if p.orientation.is_flat else "SIDE" if p.orientation.is_side else "VERTICAL")
            facing=("TOP_FLAT" if p.orientation.is_flat else
                    "SHORT_EDGE_FORWARD" if p.orientation.dx<=p.orientation.dy+1e-9 else "LONG_EDGE_FORWARD")
            top_layer_match=re.search(r"_(\d+)_\d+_\d+$",p.placement_id) if role=="TOP_FILL" else None
            stack_layer=int(top_layer_match.group(1)) if top_layer_match else member.get("layer_id")
            loading_reason={"DOOR_WALL":"DOOR_SAFETY_ANCHOR","CARGO_WALL":"WALL_FORMATION",
                "TRANSITION_WALL":"WALL_TRANSITION","TOP_FILL":"TOP_SPACE_OPTIMIZATION",
                "TOP_BRIDGE":"WALL_BRIDGE","LAYER_COMPLETION":"LAYER_COMPLETION",
                "REPAIR_GROUP":"SEQUENCE_REPAIR"}.get(role,"SOLVER_RESIDUAL")
            direction_reason=("DISPLAY_WALL_STABILITY" if profile.category.value=="DISPLAY" and facing=="SHORT_EDGE_FORWARD" else
                              "DOOR_DIRECTION_POLICY" if role=="DOOR_WALL" else
                              "PROFILE_GATED_TOP_DIRECTION" if role=="TOP_FILL" else "GLOBAL_DIRECTION_SCORE")
            repack_match=re.search(r"(?:cargo_wall_|transition_wall_)(\d{3})",p.placement_id,re.I)
            repack_wall_id=(("TRANSITION_WALL_" if "transition_wall_" in p.placement_id.lower() else "CARGO_WALL_")+repack_match.group(1)) if repack_match else member.get("wall_id")
            pattern_id=("CONTINUOUS_DISPLAY" if profile.category.value=="DISPLAY" and role in {"DOOR_WALL","TRANSITION_WALL"} else
                        "CONTACT_ALIGNED" if p.placement_id.startswith("layer_complete_") else "LAYER_CONTINUOUS" if role=="CARGO_WALL" else None)
            normalized_dimension=dimension_normalizer.normalize_sku(sku,profile.category.value=="DISPLAY")
            short=normalized_dimension.width;long=normalized_dimension.length
            forward_ratio=(short if facing=="SHORT_EDGE_FORWARD" else long)/max(long,1e-12)
            slenderness=normalized_dimension.height/max(long,1e-12)
            transport_score=round(100*(1-min(1,.6*(.45*forward_ratio+.20*slenderness)+.4*(.15*(1-forward_ratio)+.10*slenderness))),4) if facing!="TOP_FLAT" else 95.0
            rows.append({
                "id":p.placement_id,"sku":p.sku_id,"name":sku.name,"weight_kg":p.weight_kg,
                "role":role,
                "category":profile.category.value,"fragility":profile.fragility,
                # BLK-007F-7.7: product dimensions are orientation-independent.  Keep
                # the legacy aliases for BLK-007C clients, but never make a UI infer
                # product dimensions from the placement AABB below.
                "productDimensions":normalized_dimension.to_dict()["dimensions"],
                "occupiedDimensions":{"width":p.orientation.dx,"depth":p.orientation.dy,"height":p.orientation.dz},
                "axisDefinition":normalized_dimension.axisDefinition.to_dict(),
                "dimensions":normalized_dimension.to_dict()["dimensions"],
                "orientationUsed":orientation_used,"stackLayer":stack_layer,"loadingReason":loading_reason,
                "facing":facing,"direction_reason":direction_reason,
                "transport_score":transport_score,
                "wall_score":100.0 if role in {"DOOR_WALL","CARGO_WALL","TRANSITION_WALL"} else 90.0,
                "wall_id":repack_wall_id,"pattern_id":pattern_id,
                "repack_reason":"improve_wall_structure" if pattern_id else None,
                "layer_score":100.0 if pattern_id else None,
                "continuity_score":100.0 if pattern_id=="CONTINUOUS_DISPLAY" else 98.0 if pattern_id else None,
                "layer_id":member.get("layer_id") or (step.layer_id if step else None),
                "orientation_used":("FLAT_HORIZONTAL" if p.orientation.is_flat else "SIDE" if p.orientation.is_side else "VERTICAL"),
                "optimization_reason":loading_reason,
                "structural_role":role,
                "position":{"x":p.position.x,"y":p.position.y,"z":p.position.z},
                "size":{"w":p.orientation.dx,"d":p.orientation.dy,"h":p.orientation.dz},
                "rotation":{"x":0.0,"y":0.0,"z":0.0,"unit":"rad","orientation":p.orientation.name},
                "material":{"color":_color(sku.color_hex),"opacity":1.0},
                "loading":{"wall":member.get("wall_id") or (step.wall_id if step else None),
                           "layer":member.get("layer_id") or (step.layer_id if step else None),
                           "row":member.get("row_id") or (step.row_id if step else None),
                           "step":step_by_pid.get(p.placement_id),"phase":step.phase if step else None},
                "stability":{"group_id":group_by_pid[p.placement_id].id if p.placement_id in group_by_pid else None},
                "context":p.context.value,
                **({"cargo_id":p.placement_id,"original_wall":recomposition_by_id[p.placement_id]["original_wall"],
                    "new_wall":recomposition_by_id[p.placement_id]["new_wall"],
                    "original_position":recomposition_by_id[p.placement_id]["original_position"],
                    "new_position":recomposition_by_id[p.placement_id]["new_position"],
                    "swap_reason":recomposition_by_id[p.placement_id]["swap_reason"],
                    "orientation_change":recomposition_by_id[p.placement_id]["orientation_change"],
                    "recomposition_reason":recomposition_by_id[p.placement_id]["optimization_reason"]}
                   if p.placement_id in recomposition_by_id else {}),
            })
        return rows

    @staticmethod
    def walls(placements,container):
        walls=[]
        for wall in WallStructureAnalyzer(container).extract_walls(list(placements)):
            contexts=Counter(p.context.value for p in wall.placements)
            wall_type="TOP_FILL" if contexts and contexts.most_common(1)[0][0]=="TOP_FILL" else "DOOR" if "DOOR_SEAL" in contexts else "MAIN"
            walls.append({"id":wall.wall_id,"type":wall_type,
                "bounds":{"x":[wall.x_start,wall.x_end],"y":[min((p.min_y for p in wall.placements),default=0),max((p.max_y for p in wall.placements),default=0)],
                          "z":[min((p.min_z for p in wall.placements),default=0),max((p.max_z for p in wall.placements),default=0)]},
                "placements":[p.placement_id for p in wall.placements],"row_count":len(wall.rows),"layer_count":len(wall.layers)})
        return walls
