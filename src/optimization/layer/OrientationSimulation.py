from .types import OrientationCandidate


class OrientationSimulation:
    """Pure, non-mutating scoring of a legal orientation in a local void."""

    @staticmethod
    def orientation_label(orientation):
        if orientation.is_flat:
            return "FLAT_HORIZONTAL"
        if orientation.is_side:
            return "SIDE"
        return "VERTICAL"

    def simulate(self, sku, orientation, space, support_ratio=1.0, stability_margin=1.0,normalized_dimension=None):
        fits = (
            orientation.dx <= space.dx + 1e-9
            and orientation.dy <= space.dy + 1e-9
            and orientation.dz <= space.dz + 1e-9
        )
        footprint = orientation.dx * orientation.dy
        available_footprint = max(space.dx * space.dy, 1e-12)
        completion = min(1.0, footprint / available_footprint)
        height_fit = min(1.0, orientation.dz / max(space.dz, 1e-12))
        volume_gain = orientation.volume if fits else 0.0
        support = min(1.0, max(0.0, support_ratio))
        stability = min(1.0, max(0.0, stability_margin))
        risk = 1.0 - min(support, stability)
        score = 100.0 * (
            0.30 * completion + 0.25 * height_fit + 0.25 * support + 0.20 * stability
        ) - 100.0 * risk
        if not fits:
            score = -1e9
        return OrientationCandidate(
            sku.sku_id, orientation, self.orientation_label(orientation), round(score, 6),
            round(volume_gain, 6), round(completion, 6), round(support, 6),
            round(stability, 6), round(risk, 6),
            "IMPROVE_LAYER_COMPLETION" if fits else "GEOMETRY_DOES_NOT_FIT",
        )
