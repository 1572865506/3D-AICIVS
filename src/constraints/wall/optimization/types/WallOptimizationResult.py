from dataclasses import dataclass
from typing import Any,Dict,Tuple
from .TransitionWall import TransitionWall
from .WallChain import WallChain
from .WallBalanceReport import WallBalanceReport

@dataclass(frozen=True)
class WallOptimizationResult:
    status:str
    optimized_walls:Tuple[Any,...]
    transition_walls:Tuple[TransitionWall,...]
    expanded_placements:Tuple[Any,...]
    consumed_inventory:Dict[str,int]
    original_wall_end_x:float
    optimized_wall_end_x:float
    coverage_increase_m:float
    chain:WallChain
    balance:WallBalanceReport
    merged_segments:Tuple[Dict[str,Any],...]
    fragmentation_before:int
    fragmentation_after:int
    optimization_score:Dict[str,Any]
    remaining_top_candidates:Tuple[Dict[str,Any],...]
    unused_height_regions:Tuple[Dict[str,Any],...]
    def to_dict(self):return {"status":self.status,"optimized_walls":[w.to_dict() for w in self.optimized_walls],
        "transition_walls":[w.to_dict() for w in self.transition_walls],"expanded_placement_count":len(self.expanded_placements),
        "consumed_inventory":self.consumed_inventory,"original_wall_end_x":self.original_wall_end_x,
        "optimized_wall_end_x":self.optimized_wall_end_x,"coverage_increase_m":self.coverage_increase_m,
        "chain":self.chain.to_dict(),"balance":self.balance.to_dict(),"merged_segments":list(self.merged_segments),
        "fragmentation_before":self.fragmentation_before,"fragmentation_after":self.fragmentation_after,
        "optimization_score":self.optimization_score,"remaining_top_candidates":list(self.remaining_top_candidates),
        "unused_height_regions":list(self.unused_height_regions)}
