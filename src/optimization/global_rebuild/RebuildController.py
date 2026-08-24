class RebuildController:
    MODES={"NORMAL","OPTIMIZE","REBUILD"}
    def __init__(self,mode="NORMAL"):
        if mode not in self.MODES:raise ValueError("INVALID_REBUILD_MODE")
        self.mode=mode
    @property
    def enabled(self):return self.mode=="REBUILD"
