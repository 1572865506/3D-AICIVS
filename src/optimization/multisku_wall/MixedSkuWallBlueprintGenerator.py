from collections import Counter,defaultdict
from dataclasses import replace

from backend.solver_v2.domain.models import Point3D
from backend.solver_v2.domain.models import Placement,PlacementContext
from backend.solver_v2.orientation.manager import OrientationEngine
from .types import MixedWallBlueprint


class MixedSkuWallBlueprintGenerator:
    """Generate bounded structural variants while preserving vertical columns."""
    def __init__(self): self.orientations=OrientationEngine()
    @staticmethod
    def _columns(placements, detector, wall_ids):
        groups=defaultdict(list)
        for p in placements:
            if detector.wall_id(p) not in wall_ids or p.context.value=="TOP_FILL":continue
            groups[(detector.wall_id(p),round(p.min_x,6),round(p.min_y,6),round(p.orientation.dx,6),round(p.orientation.dy,6))].append(p)
        return tuple(tuple(sorted(items,key=lambda p:p.min_z)) for _,items in sorted(groups.items()))

    @staticmethod
    def _move_column(column,x=None,y=None):
        dx=(column[0].min_x if x is None else x)-column[0].min_x
        dy=(column[0].min_y if y is None else y)-column[0].min_y
        return tuple(replace(p,position=Point3D(round(p.min_x+dx,6),round(p.min_y+dy,6),p.min_z)) for p in column)

    def _gap_fill(self,container,placements,region,detector,cargo,remaining):
        """Fill side voids with complete policy-legal columns from inventory."""
        local_remaining=dict(remaining);added=[];serial=0
        for wall_id in region.wall_ids:
            wall=[p for p in placements if detector.wall_id(p)==wall_id and p.context.value!="TOP_FILL"]
            if not wall:continue
            wall_min_x=min(p.min_x for p in wall);wall_max_x=max(p.max_x for p in wall);wall_depth=wall_max_x-wall_min_x
            gaps=[(0.0,min(p.min_y for p in wall)),(max(p.max_y for p in wall),container.Ly)]
            for gap_start,gap_end in gaps:
                cursor=gap_start
                while gap_end-cursor>.01:
                    choices=[]
                    for sku in cargo:
                        if local_remaining.get(sku.sku_id,0)<=0:continue
                        for candidate in self.orientations.get_candidate_orientations(sku,PlacementContext.MAIN_WALL):
                            orientation=candidate.orientation
                            if orientation.dy>gap_end-cursor+1e-9 or orientation.dx>wall_depth+.04+1e-9:continue
                            layers=min(int((container.Lz+1e-9)//orientation.dz),local_remaining[sku.sku_id])
                            policy=sku.stacking_policy
                            if policy.max_stack_layers is not None:layers=min(layers,policy.max_stack_layers)
                            if not policy.stack_on_self or not policy.allow_stacking_on_top:layers=min(layers,1)
                            if policy.max_bearing_kg is not None and sku.weight_kg>0:
                                layers=min(layers,int(policy.max_bearing_kg//sku.weight_kg)+1)
                            if layers<=0:continue
                            residual=gap_end-cursor-orientation.dy;height=layers*orientation.dz
                            choices.append((-residual,height,orientation.dy*height,-orientation.dx,sku.sku_id,orientation.name,sku,orientation,layers))
                    if not choices:break
                    *_,sku,orientation,layers=max(choices,key=lambda row:row[:6])
                    for layer in range(layers):
                        serial+=1
                        added.append(Placement(f"{wall_id.lower()}_jointfill_{serial:04d}",
                            f"jointfill_{sku.sku_id}_{serial:04d}",sku.sku_id,
                            Point3D(round(wall_min_x,6),round(cursor,6),round(layer*orientation.dz,6)),
                            orientation,sku.weight_kg,PlacementContext.MAIN_WALL,len(placements)+len(added)))
                    local_remaining[sku.sku_id]-=layers;cursor=round(cursor+orientation.dy,6)
        if not added:return None
        # Report the resulting joint wall composition, not merely the filler
        # subset. This makes it explicit that the added columns participate in
        # a wall shared with the pre-existing SKU families.
        mix=Counter(p.sku_id for p in placements
                    if detector.wall_id(p) in region.wall_ids and p.context.value!="TOP_FILL")
        mix.update(p.sku_id for p in added)
        blueprint=MixedWallBlueprint(f"{region.region_id}_MIXED_GAP_FILL",region.region_id,"MIXED_GAP_FILL","PRESERVE",
            region.wall_ids,dict(mix),len({round(p.min_z,6) for p in added}),len({(p.min_x,p.min_y) for p in added}),
            round(container.Ly,6),0.0)
        return blueprint,tuple(placements)+tuple(added)

    def generate(self,container,placements,region,detector,cargo=(),remaining=None):
        outside=tuple(p for p in placements if detector.wall_id(p) not in region.wall_ids or p.context.value=="TOP_FILL")
        source=self._columns(placements,detector,region.wall_ids)
        if not source:return ()
        variants=[]
        for family,anchor,align_x in (("LEFT_ANCHORED","LEFT",False),("RIGHT_ANCHORED","RIGHT",False),
                                      ("JOINT_INTERFACE_LEFT","LEFT",True),("JOINT_INTERFACE_RIGHT","RIGHT",True)):
            by_wall=defaultdict(list)
            for column in source:by_wall[detector.wall_id(column[0])].append(column)
            rebuilt=[];cursor_x=region.x_range[0]
            for wall_id in sorted(by_wall,key=lambda wid:min(p.min_x for c in by_wall[wid] for p in c)):
                columns=sorted(by_wall[wall_id],key=lambda c:(c[0].min_y,c[0].sku_id,c[0].placement_id))
                widths=[c[0].orientation.dy for c in columns];total=sum(widths)
                cursor_y=0.0 if anchor=="LEFT" else container.Ly-total
                wall_min=min(p.min_x for c in columns for p in c)
                wall_max=max(p.max_x for c in columns for p in c)
                target_x=cursor_x if align_x else wall_min
                for column,width in zip(columns,widths):
                    rebuilt.extend(self._move_column(column,target_x if align_x else None,cursor_y))
                    cursor_y+=width
                if align_x:cursor_x=round(cursor_x+(wall_max-wall_min),6)
            candidate=outside+tuple(rebuilt)
            selected=[p for p in candidate if detector.wall_id(p) in region.wall_ids and p.context.value!="TOP_FILL"]
            mix=Counter(p.sku_id for p in selected)
            layers=len({round(p.min_z,6) for p in selected})
            blueprint=MixedWallBlueprint(f"{region.region_id}_{family}",region.region_id,family,anchor,region.wall_ids,
                dict(mix),layers,len(source),round(container.Ly,6),0.0)
            variants.append((blueprint,candidate))
        gap_fill=self._gap_fill(container,placements,region,detector,tuple(cargo),remaining or {})
        if gap_fill:variants.append(gap_fill)
        return tuple(variants)
