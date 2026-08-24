class RecompositionCandidateSearch:
    def __init__(self,beam_width=20,max_candidates=50):self.beam_width=beam_width;self.max_candidates=max_candidates
    def select(self,candidates):
        valid=[c for c in candidates[:self.max_candidates] if c.valid]
        # Score is authoritative; relocation count is a deterministic tie-break
        # that makes a real recomposition win over an equivalent no-op layout.
        return max(valid,key=lambda c:(c.score.global_score,c.changed_count,c.candidate_id),default=None)
