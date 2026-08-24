class CargoSequenceOptimizer:
    def order(self,wall,intelligence):
        return tuple(sorted(wall.sku_mix,key=lambda s:(intelligence.profiles[s].fragility=="HIGH",-intelligence.profiles[s].compressionPolicy.max_load_kg,s)))
