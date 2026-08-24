from dataclasses import dataclass

@dataclass(frozen=True)
class RecompositionCandidate:
    candidate_id:str;strategy:str;placements:tuple;blueprints:tuple;score:object;validation:object;changed_count:int;wall_changes:int;orientation_changes:int;swaps:tuple
    @property
    def valid(self): return self.validation.is_valid
    def to_dict(self): return {"candidate_id":self.candidate_id,"strategy":self.strategy,"placement_count":len(self.placements),"changed_count":self.changed_count,
        "changed_ratio":round(self.changed_count/max(len(self.placements),1),6),"wall_changes":self.wall_changes,"orientation_changes":self.orientation_changes,
        "score":self.score.to_dict(),"valid":self.valid,"violations":len(self.validation.violations),"blueprints":[x.to_dict() for x in self.blueprints]}
