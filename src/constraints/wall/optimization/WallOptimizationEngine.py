from .WallBalanceAnalyzer import WallBalanceAnalyzer
from .WallChainGraph import WallChainGraph
from .WallContinuityOptimizer import WallContinuityOptimizer
from .WallExpansionEngine import WallExpansionEngine
from .WallMergeOptimizer import WallMergeOptimizer
from .WallOptimizationScore import WallOptimizationScore
from .TransitionWallBuilder import TransitionWallBuilder
from .types import WallOptimizationResult

class WallOptimizationEngine:
    def __init__(self):
        self.expansion=WallExpansionEngine();self.transition=TransitionWallBuilder();self.continuity=WallContinuityOptimizer()
        self.merge=WallMergeOptimizer();self.balance=WallBalanceAnalyzer();self.chain=WallChainGraph();self.score=WallOptimizationScore()
    def optimize(self,wall_plan,remaining_cargo,container,door_wall,reserved_inventory=None):
        optimized=self.continuity.optimize(wall_plan.build.walls,container)
        door_x_bound = min((p.x for p in door_wall.placements), default=container.Lx) if door_wall and getattr(door_wall, 'placements', None) else container.Lx
        expansion=self.expansion.expand(optimized,remaining_cargo,container,door_x_bound,reserved_inventory)
        transitions=self.transition.build(expansion);all_placements=tuple(p for w in optimized for p in w.placements)+expansion.placements
        chain=self.chain.build(optimized,transitions,door_wall,container);balance=self.balance.analyze(all_placements+tuple(self._door_placements(door_wall)),container)
        merged=self.merge.merge(optimized,transitions);continuity=sum(w.continuity["continuityScore"] for w in optimized)/max(len(optimized),1)
        coverage=sum(w.continuity["coverage"] for w in optimized)/max(len(optimized),1)
        tcontinuity=sum(w.continuity_score for w in transitions)/max(len(transitions),1)
        chain_strength=sum(e.strength for e in chain.connections)/max(len(chain.connections),1) if chain.connections else 100.0
        score=self.score.calculate((continuity+tcontinuity)/2,100*(coverage+sum(w.coverage for w in transitions)/max(len(transitions),1))/2,100,balance.balanceScore,chain_strength,0,len(merged)/max(len(optimized)+len(transitions),1))
        tops=tuple({"region_id":f"OPT_TOP_{w.id}","wall_id":w.id,"x_range":[w.x_start,w.x_end],"base_z":w.height,"available_height":round(container.Lz-w.height,6)} for w in optimized if w.height<container.Lz)
        unused=tuple({"region_id":f"TRANSITION_TOP_{w.id}","x_range":list(w.x_range),"base_z":max(p.max_z for p in w.placements),"available_height":round(container.Lz-max(p.max_z for p in w.placements),6)} for w in transitions)
        status="READY" if transitions and chain.valid and expansion.residual_gap_m<=.03 else "FAILED"
        return WallOptimizationResult(status,optimized,transitions,all_placements,expansion.consumed_inventory,expansion.original_end_x,expansion.expanded_end_x,round(expansion.coverage_increase,6),chain,balance,merged,len(optimized)+len(transitions),len(merged),score,tops,unused)
    @staticmethod
    def _door_placements(door_wall):
        if not door_wall or not getattr(door_wall, 'placements', None): return []
        from backend.solver_v2.domain.models import Orientation3D,Placement,PlacementContext,Point3D
        return [Placement(p.placement_id,p.placement_id,p.sku_id,Point3D(p.x,p.y,p.z),Orientation3D(p.dx,p.dy,p.dz,p.orientation),p.weight_kg,PlacementContext.DOOR_SEAL) for p in door_wall.placements]
