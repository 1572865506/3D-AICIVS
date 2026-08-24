from backend.solver_v2.geometry.aabb import AABB
from backend.solver_v2.orientation.manager import OrientationEngine
from .OrientationSimulation import OrientationSimulation
from src.cargo.dimension_normalization import DimensionNormalizer


class OrientationOptimizer:
    """Selects among orientations already legal in both solver and Cargo Intelligence policy."""

    def __init__(self):
        self.engine = OrientationEngine()
        self.simulation = OrientationSimulation()
        self.dimension_normalizer=DimensionNormalizer();self.last_normalized_dimension=None

    def optimize(self, sku, context, space, intelligence_adapter=None, intelligence=None,
                 support_ratio=1.0, stability_margin=1.0):
        candidates = [];self.last_normalized_dimension=self.dimension_normalizer.normalize_sku(sku)
        for raw in self.engine.get_candidate_orientations(
            sku, context, target_space=space, min_support_ratio=support_ratio,
            base_height=space.min_z,
        ):
            label = self.simulation.orientation_label(raw.orientation)
            if intelligence_adapter and intelligence:
                policy_context = "TOP_FILL" if context.value == "TOP_FILL" else "DOOR_ZONE" if context.value == "DOOR_SEAL" else "MAIN_BODY"
                allowed, _ = intelligence_adapter.validate_orientation(
                    intelligence, sku.sku_id, raw.orientation.name, policy_context
                )
                if not allowed:
                    continue
                profile=intelligence.profiles[sku.sku_id]
                if policy_context=="MAIN_BODY" and profile.category.value=="DISPLAY" and raw.orientation.dx>raw.orientation.dy+1e-9:
                    continue
            candidates.append(self.simulation.simulate(
                sku, raw.orientation, space, support_ratio, stability_margin,self.last_normalized_dimension
            ))
        candidates.sort(key=lambda item: (-item.score, item.orientation.name))
        return candidates[0] if candidates else None

    @staticmethod
    def space(x, y, z, dx, dy, dz):
        return AABB(x, y, z, x + dx, y + dy, z + dz)
