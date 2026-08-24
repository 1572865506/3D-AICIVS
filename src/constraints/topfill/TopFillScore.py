class TopFillScore:
    def calculate(self,volume_gain,height_usage,support,weight_safety,orientation_fit,risk):
        score=.25*volume_gain+.20*height_usage+.25*support+.15*weight_safety+.15*orientation_fit-risk
        return round(max(0,min(100,score)),4)
