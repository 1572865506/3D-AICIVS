from .types import AxisDefinition

class AxisMapper:
    """Maps product L/W/H semantics onto canonical container X/Y/Z axes."""
    def map(self,length,width,height):
        return (max(float(length),float(width)),min(float(length),float(width)),float(height),AxisDefinition("X","Y","Z"))
