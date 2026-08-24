from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from .DoorSealOptimizer import DoorSealOptimizer
from .LayerAnalyzer import LayerAnalyzer
from .LayerCompletionEngine import LayerCompletionEngine
from .WallBridgeEngine import WallBridgeEngine
from .types import LayerOptimizationResult


class LayerOptimizationEngine:
    def __init__(self):
        self.analyzer = LayerAnalyzer()
        self.completion = LayerCompletionEngine()
        self.bridges = WallBridgeEngine()
        self.door_seal = DoorSealOptimizer()

    def optimize(self, container, cargo, existing, optimized_walls, wall_optimization, door_wall,
                 intelligence_adapter=None, intelligence=None):
        existing = tuple(existing)
        fingerprint = tuple((p.placement_id, p.aabb(), p.orientation.name) for p in existing)
        before = self.analyzer.analyze(container, existing)
        added, decisions = self.completion.complete(
            container, cargo, existing, optimized_walls, intelligence_adapter, intelligence
        )
        bridge_candidates = self.bridges.generate(
            optimized_walls, cargo, intelligence_adapter, intelligence
        )
        after = self.analyzer.analyze(container, existing + added)
        validation = IndependentGlobalValidator.validate(container, list(existing + added), list(cargo))
        preserved = fingerprint == tuple((p.placement_id, p.aabb(), p.orientation.name) for p in existing)
        seal = self.door_seal.analyze(container, door_wall, wall_optimization)
        occupancy_before = sum(layer.occupancy for layer in before) / max(len(before), 1)
        occupancy_after = sum(layer.occupancy for layer in after) / max(len(after), 1)
        void_before = sum(layer.void_volume for layer in before)
        void_after = sum(layer.void_volume for layer in after)
        status = "SUCCESS" if validation.is_valid and preserved and seal["status"] == "READY" else "FAILED"
        return LayerOptimizationResult(
            status, before, after, added, decisions, bridge_candidates, seal,
            round(occupancy_before, 6), round(occupancy_after, 6),
            round(void_before, 6), round(void_after, 6), preserved, validation,
        )
