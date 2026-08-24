class GlobalPlacementSearch:
    def __init__(self,beam_width=10,max_candidates=50):self.beam_width=beam_width;self.max_candidates=max_candidates
    def select(self,candidates):
        legal=[c for c in candidates if c.valid]
        legal.sort(key=lambda c:(-c.score.global_score,c.layout_id))
        return legal[0] if legal else None
