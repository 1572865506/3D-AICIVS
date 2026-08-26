from collections import Counter
from dataclasses import replace

from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from backend.solver_v2.domain.models import PlacementContext
from src.optimization.residual_filling import ResidualSpaceFillingEngine
from .JointWallScoreEngine import JointWallScoreEngine
from .MixedSkuWallBlueprintGenerator import MixedSkuWallBlueprintGenerator
from .WallProblemDetector import WallProblemDetector
from .types import JointWallCandidate,JointWallResult,MixedWallBlueprint,WallCargoPool


class MultiSkuWallRecompositionEngine:
    """Conservative multi-wall structural recomposition with atomic rollback."""
    def __init__(self,max_regions=32):
        self.max_regions=int(max_regions);self.detector=WallProblemDetector()
        self.generator=MixedSkuWallBlueprintGenerator();self.scoring=JointWallScoreEngine()
        self.layer_composer=ResidualSpaceFillingEngine(max_added=160,max_waves=6,min_row_coverage=.85,min_row_items=2,
            supported_row_context=PlacementContext.MAIN_WALL)

    def recompose(self,container,cargo,placements,intelligence=None):
        cargo=tuple(cargo);catalog={s.sku_id:s for s in cargo};current=tuple(placements)
        original=current;detected=self.detector.detect(container,current)
        if len(detected)>self.max_regions:
            # Preserve deterministic full-container coverage. A simple prefix
            # budget silently ignored the inner/doorward half of the box.
            indices=sorted({round(i*(len(detected)-1)/(self.max_regions-1)) for i in range(self.max_regions)})
            regions=tuple(detected[index] for index in indices)
        else:regions=detected
        pools=[];blueprints=[];candidates=[];selected=[]
        baseline_validation=IndependentGlobalValidator.validate(container,list(current),list(cargo))
        used=Counter(p.sku_id for p in current)
        remaining={s.sku_id:max(0,s.quantity.required-used[s.sku_id]) for s in cargo}
        for region in regions:
            local=tuple(p for p in current if self.detector.wall_id(p) in region.wall_ids and p.context.value!="TOP_FILL")
            pools.append(WallCargoPool(tuple(p.placement_id for p in local),dict(Counter(p.sku_id for p in local)),remaining))
            before=self.scoring.metrics(container,current,region.wall_ids,self.detector);region_candidates=[]
            for blueprint,trial in self.generator.generate(container,current,region,self.detector,cargo,remaining):
                blueprints.append(blueprint)
                after=self.scoring.metrics(container,trial,region.wall_ids,self.detector);score=self.scoring.score(before,after)
                improved=(after["gap"]<before["gap"]-1e-6 or after["side_gap"]<before["side_gap"]-1e-6 or
                          after["centered_gap"]<before["centered_gap"]-1e-6 or
                          after["incomplete"]<before["incomplete"] or after["isolated"]<before["isolated"])
                # Do not spend a complete O(n²) global validation on a geometry
                # that has already proved it changes none of the target metrics.
                validation=(IndependentGlobalValidator.validate(container,list(trial),list(cargo))
                            if improved else baseline_validation)
                reason="" if validation.is_valid and improved else "NO_STRUCTURAL_IMPROVEMENT" if validation.is_valid else \
                    (validation.rejection_reasons[0] if validation.rejection_reasons else "HARD_VALIDATION_FAILED")
                candidate=JointWallCandidate(blueprint.blueprint_id,blueprint,tuple(trial),score,validation.is_valid and improved,reason,validation)
                candidates.append(candidate);region_candidates.append(candidate)
            valid=[c for c in region_candidates if c.valid]
            if valid:
                choice=max(valid,key=lambda c:(c.score.final_score,c.candidate_id));current=choice.placements;selected.append(choice)
                used=Counter(p.sku_id for p in current)
                remaining={s.sku_id:max(0,s.quantity.required-used[s.sku_id]) for s in cargo}
        # Complete supported rows inside detected problem windows. This stage
        # reuses the existing physical support/compression/global-validation
        # path and only relaxes the structural row threshold from four cartons
        # to two; no orientation or hard-constraint rights are added.
        layer_result=self.layer_composer.fill(container,cargo,current,intelligence,
            allowed_x_ranges=tuple(region.x_range for region in regions)) if regions else None
        above_admitted=0;above_rejected=0
        if layer_result and layer_result.status=="SUCCESS" and layer_result.placements:
            wall_extents={wid:(min(p.min_x for p in current if self.detector.wall_id(p)==wid),
                               max(p.max_x for p in current if self.detector.wall_id(p)==wid))
                          for wid in {self.detector.wall_id(p) for p in current if self.detector.wall_id(p)}}
            layer_added=[]
            for index,placement in enumerate(layer_result.placements,1):
                wall_id=max(wall_extents,key=lambda wid:max(0.0,min(placement.max_x,wall_extents[wid][1])-max(placement.min_x,wall_extents[wid][0])))
                layer_added.append(replace(placement,placement_id=f"{wall_id.lower()}_jointlayer_{index:04d}"))
            trial=tuple(current)+tuple(layer_added)
            layer_validation=IndependentGlobalValidator.validate(container,list(trial),list(cargo))
            if layer_validation.is_valid:
                before=self.scoring.metrics(container,current,tuple({wid for r in regions for wid in r.wall_ids}),self.detector)
                after=self.scoring.metrics(container,trial,tuple({wid for r in regions for wid in r.wall_ids}),self.detector)
                blueprint=MixedWallBlueprint("SUPPORTED_MIXED_LAYER_COMPLETION","MULTI_REGION","MIXED_SUPPORTED_LAYER","STRUCTURAL_TOP",
                    tuple({wid for r in regions for wid in r.wall_ids}),dict(Counter(p.sku_id for p in layer_added)),
                    len({round(p.min_z,6) for p in layer_added}),len(layer_result.plans),container.Ly,0.0)
                candidate=JointWallCandidate(blueprint.blueprint_id,blueprint,trial,self.scoring.score(before,after),True,"",layer_validation)
                blueprints.append(blueprint);candidates.append(candidate);selected.append(candidate);current=trial
                above_admitted=sum(item.source=="STRUCTURED_TOP_ROW" for item in layer_result.accepted)
        if layer_result:
            above_rejected=sum(count for reason,count in layer_result.rejected.items() if "TOP" in reason or "SUPPORT" in reason or "VALIDATION" in reason)
        validation=IndependentGlobalValidator.validate(container,list(current),list(cargo))
        if not validation.is_valid:
            current=original;selected=[];validation=IndependentGlobalValidator.validate(container,list(original),list(cargo));status="ROLLED_BACK"
        else:status="SUCCESS"
        before_all=self.scoring.metrics(container,original,tuple({self.detector.wall_id(p) for p in original if self.detector.wall_id(p)}),self.detector)
        after_all=self.scoring.metrics(container,current,tuple({self.detector.wall_id(p) for p in current if self.detector.wall_id(p)}),self.detector)
        def mixed_wall_count(layout):
            groups={}
            for placement in layout:
                wall_id=self.detector.wall_id(placement)
                if wall_id and placement.context.value!="TOP_FILL":groups.setdefault(wall_id,set()).add(placement.sku_id)
            return sum(len(skus)>1 for skus in groups.values())
        metrics={"problem_regions_detected":len(detected),"problem_regions_budgeted":len(regions),"joint_regions_rebuilt":len(selected),
                 "walls_involved":sum(len(x.wall_ids) for x in regions),
                 "multi_sku_walls_before":mixed_wall_count(original),
                 "multi_sku_walls_after":mixed_wall_count(current),
                 "inter_wall_gap_m_before":round(before_all["gap"],6),"inter_wall_gap_m_after":round(after_all["gap"],6),
                 "side_gap_m_before":round(before_all["side_gap"],6),"side_gap_m_after":round(after_all["side_gap"],6),
                 "isolated_columns_before":before_all["isolated"],"isolated_columns_after":after_all["isolated"],
                 "incomplete_layers_before":before_all["incomplete"],"incomplete_layers_after":after_all["incomplete"],
                 "false_stack_ceiling_count":0,"above_cargo_admitted_count":above_admitted,"above_cargo_rejected_count":above_rejected,
                 "mixed_layer_rows_committed":len(layer_result.plans) if layer_result and layer_result.placements else 0,
                 "mixed_layer_placements_committed":len(layer_result.placements) if layer_result else 0}
        return JointWallResult(status,tuple(current),tuple(regions),tuple(pools),tuple(blueprints),tuple(candidates),tuple(selected),metrics,validation)
