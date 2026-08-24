class WallCandidateSearch:
    def __init__(self,beam_width=5,max_wall_candidates=20):self.beam_width=beam_width;self.max_wall_candidates=max_wall_candidates
    def select(self,candidates):
        legal=[c for c in candidates if c.valid];legal.sort(key=lambda c:(-c.score.final_score,c.candidate_id));return legal[0] if legal else None
