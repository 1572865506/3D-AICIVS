from dataclasses import dataclass
from itertools import product
from math import floor
from typing import Dict,Iterable,Tuple
from backend.solver_v2.domain.models import PackingRole,Placement,PlacementContext,Point3D,Orientation3D
from src.constraints.door import CargoRiskClassifier,DoorOrientationRules

@dataclass(frozen=True)
class ExpansionResult:
    placements:Tuple[Placement,...]
    wall_specs:Tuple[Dict,...]
    consumed_inventory:Dict[str,int]
    original_end_x:float
    expanded_end_x:float
    residual_gap_m:float
    @property
    def coverage_increase(self):return sum(float(spec["x_range"][1])-float(spec["x_range"][0]) for spec in self.wall_specs)

class WallExpansionEngine:
    """Bounded millimetre-space enumeration over explicitly door-eligible inventory."""
    def __init__(self,max_gap_m=.03):self.max_gap_m=max_gap_m;self.risks=CargoRiskClassifier();self.rules=DoorOrientationRules()
    def expand(self,existing_walls,remaining_cargo,container,target_end_x,reserved_inventory=None):
        start=max((w.x_end for w in existing_walls),default=0.0);gap=target_end_x-start;reserved_inventory=reserved_inventory or {}
        variants=[]
        for sku in remaining_cargo:
            risk=self.risks.classify(sku,container.Ly,container.Lz)
            if PackingRole.DOOR_SEAL not in sku.packing_roles or not risk.door_candidate:continue
            o=self.rules.orientation_for(sku,risk);cols=floor((container.Ly+1e-9)/o.wall_width);layers=floor((container.Lz+1e-9)/o.height)
            cap=cols*layers;available=max(0,sku.quantity.required-int(reserved_inventory.get(sku.sku_id,0)))
            max_walls=available//max(cap,1)
            if max_walls:variants.append({"sku":sku,"depth":o.forward_depth,"width":o.wall_width,"height":o.height,
                "concrete":o.concrete_orientation,"cols":cols,"layers":layers,"capacity":cap,"max_walls":max_walls})
        best=None
        for counts in product(*(range(v["max_walls"]+1) for v in variants)):
            length=sum(n*v["depth"] for n,v in zip(counts,variants))
            if length>gap+1e-9:continue
            residual=gap-length;types=sum(n>0 for n in counts);walls=sum(counts)
            key=(round(residual,9),types,walls,tuple(-n for n in counts))
            if best is None or key<best[0]:best=(key,counts)
        if best is None: return ExpansionResult((),(),{},start,start,gap)
        # Smooth deterministic longitudinal ordering: lowest unit weight first,
        # ending with cargo closest in weight to the fixed door anchor.
        selected=sorted(((v,n) for v,n in zip(variants,best[1]) if n),key=lambda item:item[0]["sku"].weight_kg)
        selected_length=sum(n*v["depth"] for v,n in selected)
        # When inventory cannot bridge the whole longitudinal gap, the useful
        # structural placement is a real rear-face restraint immediately behind
        # the door wall.  Appending the same cartons to the remote main wall left
        # an unrestrained door wall and failed the final transport hard gate.
        # Preserve the accepted contiguous-chain coordinates when the remaining
        # gap is already within tolerance. Only sparse manifests switch to the
        # door-adjacent anchor strategy.
        anchor_start=start if best[0][0]<=self.max_gap_m+1e-9 else max(start,target_end_x-selected_length)
        cursor=anchor_start;placements=[];specs=[];consumed={};wall_index=0
        for v,count in selected:
            for _ in range(count):
                # Side-align incomplete walls so the unused width remains one
                # contiguous, packable rectangle. Centering created two narrow
                # strips that neither the wall nor residual solver could use.
                wall_index+=1;used_width=v["cols"]*v["width"];offset_y=0.0;ps=[]
                for layer in range(v["layers"]):
                    for col in range(v["cols"]):
                        idx=layer*v["cols"]+col;raw=v["sku"]
                        p=Placement(f"transition_wall_{wall_index:03d}_{raw.sku_id}_{idx:03d}",f"transition_{raw.sku_id}_{wall_index:03d}_{idx:03d}",raw.sku_id,
                          Point3D(round(cursor,6),round(offset_y+col*v["width"],6),round(layer*v["height"],6)),
                          Orientation3D(v["depth"],v["width"],v["height"],v["concrete"],is_upright=True),raw.weight_kg,PlacementContext.DOOR_SEAL,len(placements)+idx)
                        ps.append(p)
                coverage=used_width/container.Ly;specs.append({"id":f"TRANSITION_WALL_{wall_index:03d}","sku":v["sku"].sku_id,
                    "x_range":(cursor,cursor+v["depth"]),"placements":tuple(ps),"coverage":coverage,
                    "orientation":"SHORT_EDGE_FORWARD","weight":v["sku"].weight_kg})
                placements.extend(ps);consumed[v["sku"].sku_id]=consumed.get(v["sku"].sku_id,0)+len(ps);cursor=round(cursor+v["depth"],6)
        leading_gap=max(0.0,anchor_start-start)
        return ExpansionResult(tuple(placements),tuple(specs),consumed,start,cursor,round(leading_gap,6))
