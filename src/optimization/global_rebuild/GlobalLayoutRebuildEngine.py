from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from dataclasses import replace
from .CargoSequencePlanner import CargoSequencePlanner
from .GlobalPlacementSearch import GlobalPlacementSearch
from .LayoutCandidateGenerator import LayoutCandidateGenerator
from .LayoutComparator import LayoutComparator
from .LayoutScoreEngine import LayoutScoreEngine
from .WallReconstructionEngine import WallReconstructionEngine
from .types import LayoutCandidate,RebuildResult
from src.cargo.dimension_normalization import DimensionNormalizer


class GlobalLayoutRebuildEngine:
    def __init__(self):
        self.generator=LayoutCandidateGenerator();self.walls=WallReconstructionEngine();self.sequence=CargoSequencePlanner()
        self.scoring=LayoutScoreEngine();self.search=GlobalPlacementSearch();self.comparator=LayoutComparator()
        self.dimension_normalizer=DimensionNormalizer();self.last_normalized_dimensions={}
    def rebuild(self,container,cargo,placements,intelligence,direction_plan,door_coverage,mode="REBUILD"):
        candidates=[];self.last_normalized_dimensions={sku.sku_id:self.dimension_normalizer.normalize_sku(sku) for sku in cargo}
        cargo_sequence=self.sequence.plan(cargo,intelligence)
        for strategy in self.generator.generate():
            wall_plan,placement_plan=self.walls.reconstruct(tuple(placements),strategy,intelligence)
            placement_plan=replace(placement_plan,sequence=cargo_sequence)
            validation=IndependentGlobalValidator.validate(container,list(placement_plan.placements),list(cargo))
            score=self.scoring.score(container,placement_plan.placements,cargo,direction_plan,wall_plan,door_coverage)
            advantages=("better_display_wall","higher_layer_balance") if strategy.family=="LAYER_BALANCED" else (strategy.family.lower(),)
            rejected=() if validation.is_valid else tuple(validation.rejection_reasons)
            candidates.append(LayoutCandidate(strategy.strategy_id,strategy,wall_plan,placement_plan,score,validation.is_valid,validation,advantages,rejected))
        incumbent=candidates[0];best=self.search.select(candidates)
        if not best:return RebuildResult("FAILED",mode,incumbent,tuple(candidates),incumbent,{},"NO_COMPLETE_LEGAL_REBUILD")
        comparison=self.comparator.compare(incumbent,best)
        return RebuildResult("SUCCESS",mode,incumbent,tuple(candidates),best,comparison,"BEST_COMPLETE_LEGAL_GLOBAL_SCORE")
