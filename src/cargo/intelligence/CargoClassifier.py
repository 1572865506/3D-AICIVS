from dataclasses import dataclass
from .types import CargoCategory
from src.cargo.dimension_normalization import DimensionNormalizer
@dataclass(frozen=True)
class ClassificationResult:
    category:CargoCategory
    confidence:float
    evidence:tuple
    def to_dict(self):return {"category":self.category.value,"confidence":self.confidence,"evidence":list(self.evidence)}
class CargoClassifier:
    DISPLAY_TOKENS=("显示器","液晶","屏","monitor","display","玻璃")
    ELECTRONIC_TOKENS=("电源","电脑","主机","electronic","computer")
    def __init__(self,thin_threshold=.35,heavy_threshold_kg=20):self.thin_threshold=thin_threshold;self.heavy_threshold_kg=heavy_threshold_kg;self.dimensions=DimensionNormalizer()
    def classify(self,sku):
        name=sku.name.lower();dimension=self.dimensions.normalize_sku(sku);ratio=dimension.width/max(dimension.height,1e-9);evidence=[]
        display=any(t in name for t in self.DISPLAY_TOKENS)
        if display:evidence.append("DISPLAY_NAME_RULE")
        if ratio<self.thin_threshold:evidence.append("THIN_GEOMETRY")
        if display and ratio<.65:return ClassificationResult(CargoCategory.DISPLAY,.96,tuple(evidence))
        if sku.weight_kg>self.heavy_threshold_kg:return ClassificationResult(CargoCategory.HEAVY,.90,("WEIGHT_THRESHOLD",))
        if any(t in name for t in self.ELECTRONIC_TOKENS):return ClassificationResult(CargoCategory.ELECTRONIC,.82,("ELECTRONIC_NAME_RULE",))
        if display:return ClassificationResult(CargoCategory.FRAGILE,.78,tuple(evidence))
        return ClassificationResult(CargoCategory.NORMAL_BOX,.65,("CONSERVATIVE_DEFAULT",))
