from dataclasses import dataclass
@dataclass(frozen=True)
class RepackCandidate:
    candidate_id:str;wall_id:str;pattern:object;placements:tuple;score:object;valid:bool;validation:object;gap_reduction_m:float
    def to_dict(self):return {"candidate_id":self.candidate_id,"wall_id":self.wall_id,"pattern":self.pattern.to_dict(),
        "placement_count":len(self.placements),"score":self.score.to_dict(),"valid":self.valid,"gap_reduction_m":self.gap_reduction_m,
        "validation":{"is_valid":self.validation.is_valid,"violations":len(self.validation.violations)}}
