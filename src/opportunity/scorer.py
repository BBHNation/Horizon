"""Deterministic startup opportunity scoring."""

from __future__ import annotations

from .schemas import OpportunityCandidate, ScoredOpportunity


WEIGHTS = {
    "pain_intensity": 15,
    "user_scale": 10,
    "occurrence_frequency": 10,
    "solution_gap": 10,
    "why_now_strength": 10,
    "ai_cost_leverage": 10,
    "indie_suitability": 15,
    "personal_match": 8,
    "mvp_feasibility": 7,
    "evidence_credibility": 5,
}


class OpportunityScorer:
    """Combines AI dimensions with recurrence evidence into a 0-100 score."""

    @staticmethod
    def base_score(candidate: OpportunityCandidate) -> float:
        dims = candidate.analysis.score_dimensions
        values = {
            "pain_intensity": dims.pain_intensity,
            "user_scale": dims.user_scale,
            "occurrence_frequency": dims.occurrence_frequency,
            "solution_gap": 10 - dims.solution_maturity,
            "why_now_strength": dims.why_now_strength,
            "ai_cost_leverage": dims.ai_cost_leverage,
            "indie_suitability": dims.indie_suitability,
            "personal_match": candidate.analysis.personal_fit,
            "mvp_feasibility": 10 - dims.mvp_difficulty,
            "evidence_credibility": dims.evidence_credibility,
        }
        weighted = sum(values[key] * weight for key, weight in WEIGHTS.items())
        return round(weighted / 10, 1)

    @staticmethod
    def history_boost(occurrence_count: int, source_count: int) -> float:
        recurrence = min(max(occurrence_count - 1, 0) * 1.25, 3.75)
        corroboration = min(max(source_count - 1, 0) * 1.25, 3.75)
        return round(min(recurrence + corroboration, 7.5), 1)

    def score(
        self,
        candidate: OpportunityCandidate,
        *,
        occurrence_count: int,
        source_count: int,
        first_seen,
        last_seen,
        recently_output: bool,
    ) -> ScoredOpportunity:
        base = self.base_score(candidate)
        boost = self.history_boost(occurrence_count, source_count)
        return ScoredOpportunity(
            candidate=candidate,
            base_score=base,
            history_boost=boost,
            total_score=min(100.0, round(base + boost, 1)),
            occurrence_count=occurrence_count,
            source_count=source_count,
            first_seen=first_seen,
            last_seen=last_seen,
            recently_output=recently_output,
        )
