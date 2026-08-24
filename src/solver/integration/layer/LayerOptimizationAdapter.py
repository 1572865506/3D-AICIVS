from dataclasses import dataclass

from src.optimization.layer import LayerOptimizationEngine


@dataclass(frozen=True)
class PreparedLayerOptimization:
    result: object


class LayerOptimizationAdapter:
    """Outer constraint/optimization adapter; the frozen solver remains untouched."""

    def __init__(self, engine=None):
        self.engine = engine or LayerOptimizationEngine()

    def optimize(self, container, cargo, existing, optimization_result, door_wall,
                 intelligence_adapter=None, intelligence=None):
        result = self.engine.optimize(
            container, cargo, existing, optimization_result.optimized_walls,
            optimization_result, door_wall, intelligence_adapter, intelligence,
        )
        if result.status != "SUCCESS":
            raise ValueError("LAYER_OPTIMIZATION_FAILED")
        return PreparedLayerOptimization(result)
