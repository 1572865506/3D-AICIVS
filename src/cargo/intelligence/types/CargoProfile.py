from dataclasses import dataclass
from typing import Any,Dict,Tuple
from .CargoCategory import CargoCategory
from .CompressionRule import CompressionRule
from .LoadingPolicy import LoadingPolicy
from .OrientationRule import OrientationRule
from .StackRule import StackRule
@dataclass(frozen=True)
class CargoProfile:
    sku:str
    category:CargoCategory
    category_confidence:float
    fragility:str
    orientationPolicy:OrientationRule
    stackPolicy:StackRule
    compressionPolicy:CompressionRule
    loadingPriority:LoadingPolicy
    specialRules:Tuple[str,...]
    source:str
    def to_dict(self)->Dict[str,Any]:return {"sku":self.sku,"category":self.category.value,"category_confidence":self.category_confidence,
        "fragility":self.fragility,"orientationPolicy":self.orientationPolicy.to_dict(),"stackPolicy":self.stackPolicy.to_dict(),
        "compressionPolicy":self.compressionPolicy.to_dict(),"loadingPriority":self.loadingPriority.to_dict(),
        "specialRules":list(self.specialRules),"source":self.source}
