"""ATS scoring engine -- compares a resume against a job description."""

from __future__ import annotations

import logging
from typing import Any

from ..models import ATSResult, JobListing
from .keyword_extractor import KeywordExtractor

logger = logging.getLogger(__name__)


class ATSAnalyzer:
    """Scores a resume against a JD and identifies keyword gaps."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.weights = config.get("ats", {}).get("keyword_weights", {})
        self.extractor = KeywordExtractor()

    def analyse(
        self, resume_text: str, job: JobListing, iteration: int = 1
    ) -> ATSResult:
        jd_kw = self.extractor.extract_all(job.description)
        res_kw = self.extractor.extract_all(resume_text)

        tech_match = jd_kw["technical"] & res_kw["technical"]
        tech_miss = jd_kw["technical"] - res_kw["technical"]
        soft_match = jd_kw["soft_skills"] & res_kw["soft_skills"]
        soft_miss = jd_kw["soft_skills"] - res_kw["soft_skills"]
        cert_match = jd_kw["certifications"] & res_kw["certifications"]
        cert_miss = jd_kw["certifications"] - res_kw["certifications"]

        title_score = self._title_similarity(
            self.extractor._normalise(job.title),
            resume_text.lower(),
        )

        jd_years = self.extractor.extract_years_experience(job.description)
        res_years = self.extractor.extract_years_experience(resume_text)
        exp_score = self._experience_score(jd_years, res_years)

        w = self.weights
        overall = (
            self._ratio(tech_match, jd_kw["technical"]) * w.get("technical_skills", 0.45)
            + self._ratio(soft_match, jd_kw["soft_skills"]) * w.get("soft_skills", 0.15)
            + self._ratio(cert_match, jd_kw["certifications"]) * w.get("certifications", 0.20)
            + title_score * w.get("job_title_match", 0.10)
            + exp_score * w.get("experience_years", 0.10)
        ) * 100

        result = ATSResult(
            overall_score=round(overall, 1),
            technical_matches=sorted(tech_match),
            technical_missing=sorted(tech_miss),
            soft_skill_matches=sorted(soft_match),
            soft_skill_missing=sorted(soft_miss),
            cert_matches=sorted(cert_match),
            cert_missing=sorted(cert_miss),
            title_match_score=round(title_score * 100, 1),
            experience_match_score=round(exp_score * 100, 1),
            iteration=iteration,
        )

        logger.info(
            "ATS iteration %d — score: %.1f%% (tech=%d/%d, soft=%d/%d, cert=%d/%d)",
            iteration,
            result.overall_score,
            len(tech_match), len(jd_kw["technical"]),
            len(soft_match), len(jd_kw["soft_skills"]),
            len(cert_match), len(jd_kw["certifications"]),
        )
        return result

    @staticmethod
    def _ratio(matched: set, total: set) -> float:
        return len(matched) / len(total) if total else 1.0

    @staticmethod
    def _title_similarity(jd_title: str, resume_text: str) -> float:
        words = jd_title.split()
        if not words:
            return 1.0
        hits = sum(1 for w in words if w in resume_text)
        return hits / len(words)

    @staticmethod
    def _experience_score(required: int | None, candidate: int | None) -> float:
        if required is None:
            return 1.0
        if candidate is None:
            return 0.5
        if candidate >= required:
            return 1.0
        return max(0.0, candidate / required)
