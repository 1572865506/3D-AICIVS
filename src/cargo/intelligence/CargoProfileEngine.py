import json
from pathlib import Path
from .CargoClassifier import CargoClassifier
from .CompressionPolicyEngine import CompressionPolicyEngine
from .FragilityPolicyEngine import FragilityPolicyEngine
from .LoadingPriorityEngine import LoadingPriorityEngine
from .OrientationPolicyEngine import OrientationPolicyEngine
from .StackPolicyEngine import StackPolicyEngine
from .types import CargoCategory,CargoProfile

class CargoProfileEngine:
    def __init__(self,config_dir=None):
        self.config_dir=Path(config_dir) if config_dir else Path(__file__).resolve().parents[3]/"config"/"cargo_profiles"
        self.classifier=CargoClassifier();self.orientation=OrientationPolicyEngine();self.stack=StackPolicyEngine()
        self.compression=CompressionPolicyEngine();self.fragility=FragilityPolicyEngine();self.priority=LoadingPriorityEngine()
    def _config(self,sku_id):
        path=self.config_dir/f"{sku_id}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    def profile(self,sku):
        config=self._config(sku.sku_id);classification=self.classifier.classify(sku);source=config.get("source","INFERRED")
        if "category" in config:classification=type(classification)(CargoCategory(config["category"]),float(config.get("confidence",1)),("MANUAL_PROFILE",))
        fragility=self.fragility.infer(classification,sku,config)
        return CargoProfile(sku.sku_id,classification.category,classification.confidence,fragility,
            self.orientation.build(classification,config,source),self.stack.build(classification,config,source),
            self.compression.build(classification,fragility,config,source),self.priority.build(classification,config,source),
            tuple(config.get("specialRules",())),source)
    def profile_all(self,cargo):return {sku.sku_id:self.profile(sku) for sku in cargo}
