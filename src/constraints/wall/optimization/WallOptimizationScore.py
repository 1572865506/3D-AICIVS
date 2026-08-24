class WallOptimizationScore:
    def calculate(self,continuity,coverage,support,balance,chain_strength,void_ratio,fragmentation_ratio):
        score=.22*continuity+.18*coverage+.18*support+.14*balance+.18*chain_strength+.10*(100*(1-void_ratio))-10*fragmentation_ratio
        score=max(0.0,min(100.0,score));return {"score":round(score,4),"grade":"A" if score>=90 else "B" if score>=80 else "C"}
