class CargoWallScore:
    def calculate(self, continuity, support, height_balance, weight_distribution, void_ratio, risk_penalty=0.0):
        score=(0.35*continuity+0.30*support+0.15*height_balance+0.10*weight_distribution
               +0.10*(100.0*(1.0-void_ratio))-risk_penalty)
        score=max(0.0,min(100.0,score))
        return {"wallScore":round(score,4),"risk":"LOW" if score>=80 else "MEDIUM" if score>=60 else "HIGH"}
