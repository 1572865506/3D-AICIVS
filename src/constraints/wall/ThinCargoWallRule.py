from src.constraints.door import CargoRiskClassifier


class ThinCargoWallRule:
    """Geometry/policy based thin-cargo rule; SKU ids and product names are irrelevant."""
    def __init__(self, threshold=0.35): self.classifier=CargoRiskClassifier(thin_ratio_threshold=threshold)
    def applies(self, sku, container): return self.classifier.classify(sku,container.Ly,container.Lz).thin
    def validate(self, sku, container, support_result):
        if not self.applies(sku,container): return True, None
        if support_result["isolatedCargo"]: return False,"THIN_CARGO_ISOLATED"
        return True,None
