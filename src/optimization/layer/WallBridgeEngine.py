from .types import BridgeCandidate


class WallBridgeEngine:
    """Audits bridge opportunities; only fully supported/profile-legal candidates are valid."""

    def evaluate(self, bridge_id, sku_id, left_wall_id, right_wall_id,
                 support_ratio, compression_pass, profile_allowed, discontinuity_reduction=0.0):
        valid = support_ratio >= 0.8 and compression_pass and profile_allowed
        reason = "VALID_BRIDGE" if valid else (
            "INSUFFICIENT_SUPPORT" if support_ratio < 0.8 else
            "COMPRESSION_FAILURE" if not compression_pass else "PROFILE_FORBIDDEN"
        )
        score = 100.0 * (0.65 * min(1.0, support_ratio) + 0.35 * min(1.0, max(0.0, discontinuity_reduction)))
        return BridgeCandidate(bridge_id, sku_id, left_wall_id, right_wall_id,
                               round(support_ratio, 6), compression_pass, profile_allowed,
                               round(score, 4), valid, reason)

    def generate(self, walls, cargo, intelligence_adapter=None, intelligence=None):
        result = []
        ordered = sorted(walls, key=lambda wall: (wall.x_start, wall.id))
        for index, (left, right) in enumerate(zip(ordered, ordered[1:]), 1):
            gap = max(0.0, right.x_start - left.x_end)
            overlap_y = max(0.0, min(max(p.max_y for p in left.placements), max(p.max_y for p in right.placements)) -
                            max(min(p.min_y for p in left.placements), min(p.min_y for p in right.placements)))
            width = max(max(p.max_y for p in left.placements), max(p.max_y for p in right.placements)) - \
                    min(min(p.min_y for p in left.placements), min(p.min_y for p in right.placements))
            support = overlap_y / max(width, 1e-12) if gap <= 1e-6 else 0.0
            sku = min(cargo, key=lambda item: (item.weight_kg, item.sku_id))
            profile_allowed = True
            compression_pass = True
            if intelligence_adapter and intelligence:
                profile_allowed, _ = intelligence_adapter.validate_orientation(intelligence, sku.sku_id, "VERTICAL", "MAIN_BODY")
                compression_pass, _ = intelligence_adapter.validate_compression(intelligence, sku.sku_id, sku.weight_kg)
            reduction = min(1.0, abs(left.height - right.height) / max(left.height, right.height, 1e-12))
            result.append(self.evaluate(f"BRIDGE_{index:03d}", sku.sku_id, left.id, right.id,
                                        support, compression_pass, profile_allowed, reduction))
        return tuple(result)
