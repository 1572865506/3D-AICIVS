class WallRebuildAdapter:
    def __init__(self,engine):self.engine=engine
    def rebuild(self,*args,**kwargs):
        result=self.engine.repack(*args,**kwargs)
        if result.status!="SUCCESS":raise ValueError("WALL_INTERNAL_REPACK_FAILED")
        return result
