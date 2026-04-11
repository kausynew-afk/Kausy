"""Main orchestrator -- wires scraping, analysis, tailoring, and logging."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .analysis import ATSAnalyzer
from .logging_system import AuditLogger
from .models import JobListing
from .resume import ResumeModifier
from .safety import DeduplicationGuard, RateLimiter
from .scrapers import IndeedScraper, LinkedInScraper, NaukriScraper

logger = logging.getLogger(__name__)

PLATFORM_MAP = {
    "linkedin": LinkedInScraper,
    "indeed": IndeedScraper,
    "naukri": NaukriScraper,
}


class Orchestrator:
    """Runs the full pipeline: scrape -> analyse -> tailor -> score -> log."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.analyzer = ATSAnalyzer(config)
        self.modifier = ResumeModifier(config)
        self.dedup = DeduplicationGuard(config)
        self.limiter = RateLimiter(config)
        self.audit = AuditLogger(config)

        self._target_score = config.get("ats", {}).get("target_score", 80)
        self._max_iterations = config.get("ats", {}).get("max_iterations", 3)

    async def run(self) -> None:
        logger.info("=" * 60)
        logger.info("Job Application Agent — starting run")
        logger.info("=" * 60)

        master_text = self.modifier.load_master()
        logger.info("Master resume loaded (%d chars)", len(master_text))

        listings = await self._scrape_all()
        logger.info("Total listings scraped: %d", len(listings))

        processed = 0
        for job in listings:
            if not self.limiter.can_proceed():
                logger.info("Rate limit reached, stopping")
                break

            if self.dedup.is_duplicate(job):
                logger.info("Skipping duplicate: %s @ %s", job.title, job.company)
                continue

            if not job.description.strip():
                logger.warning("Empty JD for %s @ %s, skipping", job.title, job.company)
                continue

            logger.info(
                "Processing [%d]: %s @ %s (%s)",
                processed + 1, job.title, job.company, job.platform,
            )

            tailored_resume, final_ats = self._tailor_with_iteration(master_text, job)

            status = "logged"
            notes = ""
            if final_ats.overall_score < self._target_score:
                status = "skipped"
                notes = (
                    f"ATS score {final_ats.overall_score:.1f}% below "
                    f"target {self._target_score}% after {final_ats.iteration} iterations"
                )

            self.audit.log_application(
                job=job,
                ats=final_ats,
                tailored_resume=tailored_resume,
                status=status,
                notes=notes,
            )

            self.dedup.mark_applied(job)
            self.limiter.record()
            processed += 1

        summary_path = self.audit.write_summary()
        logger.info("Run complete. Summary: %s", summary_path)
        logger.info("Processed %d jobs, %d remaining in rate limit", processed, self.limiter.remaining)

    def _tailor_with_iteration(
        self, master_text: str, job: JobListing
    ) -> tuple[str, Any]:
        """Tailor the resume and re-iterate if ATS score is below target."""
        current_resume = master_text

        for iteration in range(1, self._max_iterations + 1):
            ats_result = self.analyzer.analyse(current_resume, job, iteration)

            if ats_result.overall_score >= self._target_score:
                logger.info(
                    "ATS score %.1f%% >= target %d%% at iteration %d",
                    ats_result.overall_score, self._target_score, iteration,
                )
                tailored = self.modifier.tailor(job, ats_result)
                return tailored, ats_result

            logger.info(
                "ATS score %.1f%% < target %d%%, re-iterating (attempt %d/%d)",
                ats_result.overall_score, self._target_score,
                iteration, self._max_iterations,
            )
            tailored = self.modifier.tailor(job, ats_result)
            current_resume = tailored

        final_ats = self.analyzer.analyse(current_resume, job, self._max_iterations)
        return current_resume, final_ats

    async def _scrape_all(self) -> list[JobListing]:
        platforms = self.config.get("scraping", {}).get("platforms", [])
        tasks = []

        for platform in platforms:
            scraper_cls = PLATFORM_MAP.get(platform)
            if scraper_cls:
                scraper = scraper_cls(self.config)
                tasks.append(scraper.scrape())
            else:
                logger.warning("Unknown platform: %s", platform)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_listings: list[JobListing] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Scraper failed: %s", result)
            else:
                all_listings.extend(result)

        return all_listings
