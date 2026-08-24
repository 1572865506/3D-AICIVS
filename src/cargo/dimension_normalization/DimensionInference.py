class DimensionInference:
    def __init__(self,thickness_ratio=.25):self.thickness_ratio=thickness_ratio
    def thickness_axis(self,length,width,height):
        values={"LENGTH":length,"WIDTH":width,"HEIGHT":height};axis,value=min(values.items(),key=lambda item:item[1])
        return axis if value/max(values.values())<self.thickness_ratio else None
