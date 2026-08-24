from src.cargo.dimension_normalization import DimensionNormalizer
class OrientationMutationSearch:
    def __init__(self):self.normalizer=DimensionNormalizer()
    def candidates(self,sku,placement):
        legal=sku.orientation_policy.get_legal_orientations(self.normalizer.normalize_sku(sku).to_box_dim(),placement.context)
        return tuple(legal[:6])
    def choose(self,sku,placement):
        # Preserve the current legal orientation unless a reconstructed slot is
        # explicitly rebuilt for another shape. This prevents unsafe free rotation.
        legal=self.candidates(sku,placement)
        return next((o for o in legal if (o.dx,o.dy,o.dz)==(placement.orientation.dx,placement.orientation.dy,placement.orientation.dz)),placement.orientation)
