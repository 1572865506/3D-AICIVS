class DirectionConstraintAdapter:
    """Projects preferred priorities without mutating CargoSKU or hard-locking the frozen solver."""
    def prepare(self, engine, container, cargo, intelligence):
        plan = engine.plan(container, cargo, intelligence)
        return tuple(cargo), plan
