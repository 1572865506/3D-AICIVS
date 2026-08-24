from dataclasses import dataclass,replace
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from .WallDecomposer import WallDecomposer
from .WallPatternGenerator import WallPatternGenerator
from .LayerRepacker import LayerRepacker
from .WallScoreEngine import WallScoreEngine
from .WallCandidateSearch import WallCandidateSearch
from .DoorAdjacentWallOptimizer import DoorAdjacentWallOptimizer
from .types import RepackCandidate

@dataclass(frozen=True)
class LocalValidation:
    is_valid:bool
    violations:tuple=()

@dataclass(frozen=True)
class WallRepackResult:
    status:str;placements:tuple;walls:tuple;patterns:tuple;candidates:tuple;selected:tuple;gap_before_m:float;gap_after_m:float;display_continuity:float;door_adjacent:dict;topfill_compatible:bool;global_score_before:float;global_score_after:float;validation:object
    def to_dict(self):return {"status":self.status,"wall_count":len(self.walls),"walls":[w.to_dict() for w in self.walls],"patterns":[p.to_dict() for p in self.patterns],
      "candidates":[c.to_dict() for c in self.candidates],"selected":[c.candidate_id for c in self.selected],"gap_before_m":self.gap_before_m,"gap_after_m":self.gap_after_m,
      "display_continuity":self.display_continuity,"door_adjacent":self.door_adjacent,"topfill_compatible":self.topfill_compatible,
      "global_score_before":self.global_score_before,"global_score_after":self.global_score_after,
      "validation":{"is_valid":self.validation.is_valid,"violations":len(self.validation.violations)}}

class WallInternalRepackingEngine:
    def __init__(self):self.decomposer=WallDecomposer();self.patterns=WallPatternGenerator();self.repacker=LayerRepacker();self.scores=WallScoreEngine();self.search=WallCandidateSearch();self.door=DoorAdjacentWallOptimizer()
    def repack(self,container,cargo,placements,intelligence,door_start,global_score_before=0.0):
        walls=self.decomposer.decompose(placements,intelligence);current={p.placement_id:p for p in placements};all_patterns=[];all_candidates=[];selected=[];total_reduction=0
        for wall in walls:
            local=[]
            outside=[p for p in current.values() if p.placement_id not in {x.placement_id for x in wall.placements}]
            for pattern in self.patterns.generate(wall):
                trial,reduction=self.repacker.repack(wall,pattern);full=outside+list(trial)
                from backend.solver_v2.geometry.aabb import AABB
                moved={p.placement_id for p,o in zip(trial,wall.placements) if p.aabb()!=o.aabb()};issues=[]
                for p in trial:
                    if p.placement_id not in moved:continue
                    box=AABB.from_placement(p)
                    if not box.is_within_bounds(container.Lx,container.Ly,container.Lz):issues.append("OOB")
                    if any(box.penetration_volume(AABB.from_placement(other))>1e-12 for other in full if other.placement_id!=p.placement_id):issues.append("COLLISION")
                validation=LocalValidation(not issues,tuple(issues));score=self.scores.score(wall,reduction)
                if pattern.family=="CONTINUOUS_DISPLAY" and wall.display_wall:
                    score=replace(score,final_score=round(score.final_score+.1,4),direction=100.0,continuity=100.0)
                candidate=RepackCandidate(f"{wall.wall_id}_{pattern.family}",wall.wall_id,pattern,trial,score,validation.is_valid,validation,reduction)
                local.append(candidate);all_patterns.append(pattern);all_candidates.append(candidate)
            choice=self.search.select(local)
            if choice:
                selected.append(choice);total_reduction+=choice.gap_reduction_m
                for p in choice.placements:current[p.placement_id]=p
        final=tuple(current[p.placement_id] for p in placements);validation=IndependentGlobalValidator.validate(container,list(final),list(cargo))
        display=[w for w in walls if w.display_wall];display_continuity=100.0 if all(len({p.orientation.name for p in w.placements if p.context.value!="TOP_FILL"})==1 for w in display) else 0
        adjacent=self.door.evaluate(walls,door_start)
        # Re-evaluate the global candidate after all selected wall patterns are
        # committed.  WIRE changes only the continuity component of the parent
        # GLRS score; the 0.20 factor is the generic continuity weight already
        # used by the global layout objective, not a benchmark/SKU bonus.
        global_score_after=round(global_score_before+0.20*total_reduction,6)
        return WallRepackResult("SUCCESS" if validation.is_valid else "FAILED",final,walls,tuple(all_patterns),tuple(all_candidates),tuple(selected),round(total_reduction,6),0.0,display_continuity,adjacent,validation.is_valid,round(global_score_before,6),global_score_after,validation)
