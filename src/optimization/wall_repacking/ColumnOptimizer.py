class ColumnOptimizer:
    def score(self,wall):
        heights=[c.height for c in wall.columns]
        if not heights:return 0.0
        return round(100*(1-(max(heights)-min(heights))/max(max(heights),1e-9)),4)
