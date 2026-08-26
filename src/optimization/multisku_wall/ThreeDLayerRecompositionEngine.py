from collections import defaultdict
from dataclasses import dataclass,replace

from backend.solver_v2.domain.models import Point3D
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from .WallProblemDetector import WallProblemDetector


@dataclass(frozen=True)
class LayerExchangeCandidate:
    candidate_id:str
    region_id:str
    placements:tuple
    exchanged_columns:int
    moved_placements:int
    raggedness_before_m:float
    raggedness_after_m:float
    incomplete_columns_before:int
    incomplete_columns_after:int
    valid:bool
    rejection_reason:str
    validation:object
    def to_dict(self):return {"candidate_id":self.candidate_id,"region_id":self.region_id,
        "exchanged_columns":self.exchanged_columns,"moved_placements":self.moved_placements,
        "raggedness_before_m":self.raggedness_before_m,"raggedness_after_m":self.raggedness_after_m,
        "incomplete_columns_before":self.incomplete_columns_before,"incomplete_columns_after":self.incomplete_columns_after,
        "valid":self.valid,"rejection_reason":self.rejection_reason}


@dataclass(frozen=True)
class ThreeDLayerRecompositionResult:
    status:str
    placements:tuple
    candidates:tuple
    selected:tuple
    metrics:dict
    validation:object
    def to_dict(self):return {"status":self.status,"candidates":[x.to_dict() for x in self.candidates],
        "selected":[x.candidate_id for x in self.selected],"metrics":self.metrics,
        "validation":{"is_valid":self.validation.is_valid,"violations":len(self.validation.violations)}}


class ThreeDLayerRecompositionEngine:
    """Exchange complete equal-footprint columns to create flatter wall slabs.

    The operation is a permutation: it never invents cargo, orientation rights,
    support shortcuts or inventory. Whole floor-anchored contiguous columns move
    atomically between equal-footprint slots in adjacent problem walls.
    """
    def __init__(self,max_regions=20):self.max_regions=int(max_regions);self.detector=WallProblemDetector()

    def _columns(self,placements,wall_ids):
        groups=defaultdict(list)
        for placement in placements:
            wall_id=self.detector.wall_id(placement)
            if wall_id not in wall_ids or placement.context.value=="TOP_FILL":continue
            key=(wall_id,round(placement.min_x,6),round(placement.min_y,6),
                 round(placement.orientation.dx,6),round(placement.orientation.dy,6))
            groups[key].append(placement)
        columns=[]
        for key,items in groups.items():
            items=tuple(sorted(items,key=lambda p:p.min_z));cursor=0.0;contiguous=True
            for placement in items:
                if abs(placement.min_z-cursor)>1e-5:contiguous=False;break
                cursor=placement.max_z
            if contiguous:columns.append({"key":key,"wall_id":key[0],"x":key[1],"y":key[2],
                "dx":key[3],"dy":key[4],"height":cursor,"placements":items})
        return columns

    @staticmethod
    def _quality(columns):
        by_slab=defaultdict(list)
        for column in columns:by_slab[round(column["x"],4)].append(column["height"])
        ragged=sum(max(values)-min(values) for values in by_slab.values() if len(values)>1)
        incomplete=sum(sum(height<max(values)-1e-5 for height in values) for values in by_slab.values() if values)
        return round(ragged,6),int(incomplete)

    def _candidate(self,container,cargo,current,region,family):
        columns=self._columns(current,region.wall_ids);before_ragged,before_incomplete=self._quality(columns)
        assignments=[]
        by_footprint=defaultdict(list)
        for column in columns:by_footprint[(column["dx"],column["dy"])].append(column)
        for footprint,compatible in sorted(by_footprint.items()):
            if len({c["wall_id"] for c in compatible})<2:continue
            targets=sorted(compatible,key=lambda c:(c["x"],c["wall_id"],c["y"]))
            sources=sorted(compatible,key=lambda c:(c["height"],c["wall_id"],c["y"]),reverse=family=="HIGH_TO_LOW")
            assignments.extend(zip(sources,targets))
        if not assignments:return None
        moved={};exchanged=0
        for source,target in assignments:
            if (source["x"],source["y"])!=(target["x"],target["y"]):exchanged+=1
            shift_x=target["x"]-source["x"];shift_y=target["y"]-source["y"]
            for placement in source["placements"]:
                moved[placement.placement_id]=replace(placement,position=Point3D(
                    round(placement.min_x+shift_x,6),round(placement.min_y+shift_y,6),placement.min_z))
        trial=tuple(moved.get(p.placement_id,p) for p in current)
        after_columns=self._columns(trial,region.wall_ids);after_ragged,after_incomplete=self._quality(after_columns)
        improved=after_ragged<before_ragged-1e-6 or after_incomplete<before_incomplete
        validation=IndependentGlobalValidator.validate(container,list(trial),list(cargo)) if improved else None
        valid=bool(improved and validation.is_valid)
        reason="" if valid else "NO_LAYER_IMPROVEMENT" if not improved else \
            (validation.rejection_reasons[0] if validation and validation.rejection_reasons else "HARD_VALIDATION_FAILED")
        return LayerExchangeCandidate(f"{region.region_id}_{family}",region.region_id,trial,exchanged,len(moved),
            before_ragged,after_ragged,before_incomplete,after_incomplete,valid,reason,validation)

    def recompose(self,container,cargo,placements):
        original=tuple(placements);current=original;candidates=[];selected=[]
        regions=self.detector.detect(container,current)
        # Pair adjacent detector windows so four-wall exchanges can cluster
        # heights that no two-wall permutation can improve.
        expanded=list(regions)
        for index,(left,right) in enumerate(zip(regions,regions[1:]),1):
            if right.x_range[0]-left.x_range[1]>.5:continue
            expanded.append(replace(left,region_id=f"LAYER_WINDOW_{index:03d}",
                wall_ids=tuple(dict.fromkeys(left.wall_ids+right.wall_ids)),
                x_range=(left.x_range[0],right.x_range[1]),
                problem_types=tuple(sorted(set(left.problem_types+right.problem_types))),
                incomplete_layers=left.incomplete_layers+right.incomplete_layers,
                isolated_columns=left.isolated_columns+right.isolated_columns))
        ranked=sorted(expanded,key=lambda r:(r.region_id.startswith("LAYER_WINDOW_"),
            -(r.incomplete_layers+r.isolated_columns),-len(r.wall_ids),r.x_range))[:self.max_regions]
        for region in ranked:
            local=[]
            for family in ("LOW_TO_HIGH","HIGH_TO_LOW"):
                candidate=self._candidate(container,cargo,current,region,family)
                if candidate:candidates.append(candidate);local.append(candidate)
            valid=[candidate for candidate in local if candidate.valid]
            if valid:
                choice=min(valid,key=lambda c:(c.incomplete_columns_after,c.raggedness_after_m,
                    c.moved_placements,c.exchanged_columns,c.candidate_id))
                current=choice.placements;selected.append(choice)
        validation=IndependentGlobalValidator.validate(container,list(current),list(cargo))
        if not validation.is_valid:
            current=original;selected=[];validation=IndependentGlobalValidator.validate(container,list(original),list(cargo));status="ROLLED_BACK"
        else:status="SUCCESS"
        return ThreeDLayerRecompositionResult(status,tuple(current),tuple(candidates),tuple(selected),{
            "regions_considered":len(ranked),"candidates_generated":len(candidates),"regions_rebuilt":len(selected),
            "columns_exchanged":sum(c.exchanged_columns for c in selected),"placements_moved":sum(c.moved_placements for c in selected),
            "raggedness_reduction_m":round(sum(c.raggedness_before_m-c.raggedness_after_m for c in selected),6),
            "incomplete_columns_reduced":sum(c.incomplete_columns_before-c.incomplete_columns_after for c in selected)},validation)
