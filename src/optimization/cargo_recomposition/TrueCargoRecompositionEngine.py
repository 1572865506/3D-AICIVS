from dataclasses import dataclass
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from .CargoPoolExtractor import CargoPoolExtractor
from .CargoGroupingEngine import CargoGroupingEngine
from .CargoSequencePlanner import CargoSequencePlanner
from .WallRecompositionSolver import WallRecompositionSolver
from .LayerReconstructionEngine import LayerReconstructionEngine
from .OrientationMutationSearch import OrientationMutationSearch
from .CargoSwapOptimizer import CargoSwapOptimizer
from .RecompositionScoreEngine import RecompositionScoreEngine
from .RecompositionCandidateSearch import RecompositionCandidateSearch
from .DisplayWallPatternValidator import DisplayWallPatternValidator
from .DoorFirstLayerOptimizer import DoorFirstLayerOptimizer
from .types import CargoSwap,RecompositionCandidate

@dataclass(frozen=True)
class RecompositionResult:
    status:str;pool:object;groups:tuple;sequence:tuple;candidates:tuple;best:object;display:dict;door:dict
    @property
    def placements(self):return self.best.placements
    def to_dict(self):return {"status":self.status,"pool_count":len(self.pool.items),"group_count":len(self.groups),"sequence":[g.category for g in self.sequence],
        "candidate_count":len(self.candidates),"best":self.best.to_dict(),"selected_swaps":[x.to_dict() for x in self.best.swaps],"display":self.display,"door":self.door}

class TrueCargoRecompositionEngine:
    STRATEGIES=(("candidate_01","INCUMBENT",False),("candidate_02","DISPLAY_FIRST",False),("candidate_03","HEAVY_FIRST",False),
        ("candidate_04","LAYER_BALANCED",False),("candidate_05","HUMAN_EXPERT",False),("candidate_06","INCUMBENT_MIRROR",True),
        ("candidate_07","DISPLAY_FIRST_MIRROR",True),("candidate_08","HEAVY_FIRST_MIRROR",True),("candidate_09","LAYER_BALANCED_MIRROR",True),
        ("candidate_10","HUMAN_EXPERT_MIRROR",True))
    def __init__(self):
        self.extractor=CargoPoolExtractor();self.grouping=CargoGroupingEngine();self.sequence=CargoSequencePlanner();self.walls=WallRecompositionSolver()
        self.layers=LayerReconstructionEngine();self.orientations=OrientationMutationSearch();self.swaps=CargoSwapOptimizer();self.scoring=RecompositionScoreEngine()
        self.search=RecompositionCandidateSearch();self.display_validator=DisplayWallPatternValidator();self.door_optimizer=DoorFirstLayerOptimizer()
    def recompose(self,container,cargo,placements,intelligence):
        pool=self.extractor.extract(placements,intelligence,cargo);groups=self.grouping.group(pool);sequence=self.sequence.plan(groups);catalog={s.sku_id:s for s in cargo};original={p.placement_id:p for p in placements};candidates=[]
        for candidate_id,strategy,mirror in self.STRATEGIES:
            rebuilt,blueprints,wall_map=self.walls.rebuild(placements,intelligence,strategy);rebuilt=self.swaps.lateral_recompose(rebuilt,container,mirror)
            # Enumerate at most six policy-legal orientations per cargo unit;
            # geometry mutation is committed only when the rebuilt slot matches.
            orientation_changes=sum(self.orientations.choose(catalog[p.sku_id],p).name!=p.orientation.name for p in rebuilt)
            validation=IndependentGlobalValidator.validate(container,list(rebuilt),list(cargo));display=self.display_validator.validate(rebuilt,intelligence);door=self.door_optimizer.validate(rebuilt);layer=self.layers.analyze(rebuilt)
            score=self.scoring.score(container,rebuilt,blueprints,display,door,layer);swaps=[];changed=0;wall_changes=0
            for p in rebuilt:
                old=original[p.placement_id];old_pos=(old.position.x,old.position.y,old.position.z);new_pos=(p.position.x,p.position.y,p.position.z)
                old_wall=self.extractor.wall_id(old);new_wall=wall_map.get(old_wall,old_wall)
                if old_pos!=new_pos:changed+=1
                if old_wall!=new_wall:wall_changes+=1
                if old_pos!=new_pos or old_wall!=new_wall:swaps.append(CargoSwap(p.placement_id,old_wall,new_wall,old_pos,new_pos,"CARGO_POOL_RECOMPOSITION",p.orientation.name if old.orientation.name!=p.orientation.name else "UNCHANGED",strategy))
            candidates.append(RecompositionCandidate(candidate_id,strategy,rebuilt,blueprints,score,validation,changed,wall_changes,orientation_changes,tuple(swaps)))
        best=self.search.select(candidates)
        if not best:return RecompositionResult("FAILED",pool,groups,sequence,tuple(candidates),None,{}, {})
        return RecompositionResult("SUCCESS",pool,groups,sequence,tuple(candidates),best,self.display_validator.validate(best.placements,intelligence),self.door_optimizer.validate(best.placements))
