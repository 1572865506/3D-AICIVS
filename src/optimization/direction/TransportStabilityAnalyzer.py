from .types import TransportRisk
from src.cargo.dimension_normalization import DimensionNormalizer


class TransportStabilityAnalyzer:
    def __init__(self):self.dimension_normalizer=DimensionNormalizer()
    def analyze(self, sku, facing, dimension=None):
        dimension=dimension or self.dimension_normalizer.normalize_sku(sku)
        short = dimension.width
        long = dimension.length
        slenderness = dimension.height / max(long, 1e-12)
        forward_ratio = (short if facing == "SHORT_EDGE_FORWARD" else long) / max(long, 1e-12)
        braking = min(1.0, 0.45 * forward_ratio + 0.20 * slenderness)
        turning = min(1.0, 0.15 * (1.0 - forward_ratio) + 0.10 * slenderness)
        forward = braking
        side = turning
        total = min(1.0, 0.6 * braking + 0.4 * turning)
        return TransportRisk(round(forward, 6), round(side, 6), round(braking, 6),
                             round(turning, 6), "SHORT_EDGE_FORWARD", round(100 * (1 - total), 4))
