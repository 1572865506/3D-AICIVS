from .types import DimensionIssue

class DimensionValidator:
    def validate(self,original,normalized,is_display=False):
        first,second,height=original;issues=[]
        if second>first:issues.append(DimensionIssue("AXIS_SWAP_WARNING","WARNING","horizontal width exceeded length; canonical axes were swapped","HORIZONTAL"))
        if is_display:
            if not normalized.height>normalized.width:issues.append(DimensionIssue("DISPLAY_HEIGHT_WIDTH_WARNING","WARNING","display standing height should exceed thickness width","HEIGHT"))
            if normalized.width/normalized.length>=.35:issues.append(DimensionIssue("DISPLAY_THICKNESS_RATIO_WARNING","WARNING","display width is not thin relative to length","WIDTH"))
        if normalized.thicknessAxis:issues.append(DimensionIssue("THICKNESS_AXIS","INFO",f"significantly smaller dimension detected: {normalized.thicknessAxis}",normalized.thicknessAxis))
        return tuple(issues)
