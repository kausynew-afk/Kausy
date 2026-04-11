"""Main orchestrator -- wires scraping, analysis, tailoring, email, and logging.

Strict rules enforced:
  1. No duplicate jobs (company+title, job code, UID triple-check)
  2. Resume customized for every job before proceeding
  3. Resume saved as PDF with standardized naming
  4. Email the user per job -- agent does NOT auto-apply
  5. Validate everything before sending email
  6. Fail-safe: errors on one job never crash the whole run
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Any

from .analysis import ATSAnalyzer
from .email_report import EmailReporter
from .logging_system import AuditLogger
from .models import JobListing
from .resume import ResumeModifier
from .safety import DeduplicationGuard, RateLimiter
from .scrapers import IndeedScraper, LinkedInScraper, NaukriScraper
from .tracker import JobTracker

logger = logging.getLogger(__name__)

PLATFORM_MAP = {
    "linkedin": LinkedInScraper,
    "indeed": IndeedScraper,
    "naukri": NaukriScraper,
}


class Orchestrator:
    """Runs the full pipeline: scrape -> analyse -> tailor -> validate -> email."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.analyzer = ATSAnalyzer(config)
        self.modifier = ResumeModifier(config)
        self.dedup = DeduplicationGuard(config)
        self.limiter = RateLimiter(config)
        self.audit = AuditLogger(config)
        self.tracker = JobTracker(config)
        self.emailer = EmailReporter(config)

        self._target_score = config.get("ats", {}).get("target_score", 80)
        self._max_iterations = config.get("ats", {}).get("max_iterations", 3)

    async def run(self) -> dict[str, Any]:
        logger.info("=" * 60)
        logger.info("Job Application Agent — starting run")
        logger.info("=" * 60)

        master_text = self.modifier.load_master()
        logger.info("Master resume loaded (%d chars)", len(master_text))

        listings = await self._scrape_all()
        logger.info("Total listings scraped: %d", len(listings))

        processed = 0
        email_sent_count = 0
        skipped_count = 0
        error_count = 0

        for job in listings:
            if not self.limiter.can_proceed():
                logger.info("Rate limit reached, stopping")
                break

            try:
                result = self._process_single_job(master_text, job)
                processed += 1
                if result == "email_sent":
                    email_sent_count += 1
                elif result == "skipped":
                    skipped_count += 1
                elif result == "error":
                    error_count += 1
            except Exception:
                error_count += 1
                processed += 1
                logger.error(
                    "FAIL-SAFE: Unhandled error processing %s @ %s:\n%s",
                    job.title, job.company, traceback.format_exc(),
                )
                self.tracker.track_error(job, traceback.format_exc())

        summary_path = self.audit.write_summary()
        tracker_path = self.tracker.write_tracker_report()

        logger.info("=" * 60)
        logger.info("RUN COMPLETE")
        logger.info("  Summary report : %s", summary_path)
        logger.info("  Tracker report : %s", tracker_path)
        logger.info("  Total processed: %d", processed)
        logger.info("  Emails sent    : %d", email_sent_count)
        logger.info("  Skipped        : %d", skipped_count)
        logger.info("  Errors         : %d", error_count)
        logger.info("  Rate remaining : %d", self.limiter.remaining)
        logger.info("=" * 60)

        return {
            "processed": processed,
            "email_sent_count": email_sent_count,
            "skipped": skipped_count,
            "errors": error_count,
            "summary_path": str(summary_path),
            "tracker_path": str(tracker_path),
            "records": self.audit.records,
            "run_id": self.audit.run_id,
        }

    def _process_single_job(self, master_text: str, job: JobListing) -> str:
        """Process one job through the full pipeline. Returns status string."""

        # --- RULE 1: Duplicate check (company+title, job_code, UID) ---
        dup_reason = self.dedup.is_duplicate(job)
        if dup_reason:
            logger.info(
                "SKIPPED (duplicate): %s @ %s — %s",
                job.title, job.company, dup_reason,
            )
            self.tracker.track_skip(
                job, reason=f"Skipped - Already Processed ({dup_reason})"
            )
            return "skipped"

        # --- Check for empty JD ---
        if not job.description.strip():
            logger.warning(
                "SKIPPED (empty JD): %s @ %s", job.title, job.company,
            )
            self.tracker.track_skip(job, reason="Skipped - Empty Job Description")
            return "skipped"

        logger.info(
            "Processing: %s @ %s [%s] (code: %s)",
            job.title, job.company, job.platform, job.job_code or "NA",
        )

        # --- RULE 2: Resume must be customized ---
        tailored_resume, final_ats = self._tailor_with_iteration(master_text, job)

        if final_ats.overall_score < self._target_score:
            notes = (
                f"ATS score {final_ats.overall_score:.1f}% below "
                f"target {self._target_score}% after {final_ats.iteration} iterations"
            )
            logger.info(
                "LOW ATS: %s @ %s — %s (still emailing with resume)",
                job.title, job.company, notes,
            )

            record = self.audit.log_application(
                job=job, ats=final_ats,
                tailored_resume=tailored_resume,
                status="skipped", notes=notes,
            )

            email_ok = self.emailer.send_job_email(
                job=job, ats=final_ats,
                resume_path=record.resume_path,
                resume_filename=record.resume_filename,
                skip_reason=notes,
            )

            self.tracker.track(
                job=job, ats=final_ats, status="skipped",
                resume_path=record.resume_path,
                resume_filename=record.resume_filename,
                action="Skipped (Emailed)" if email_ok else "Skipped",
                notes=notes,
            )
            self.dedup.mark_applied(job)
            self.limiter.record()
            return "skipped"

        # --- RULE 3: Save resume as PDF with standard naming ---
        record = self.audit.log_application(
            job=job, ats=final_ats,
            tailored_resume=tailored_resume,
            status="email_sent", notes="",
        )

        # --- RULE 5: Validate before sending email ---
        if not record.resume_path:
            logger.error(
                "VALIDATION FAILED: resume not saved for %s @ %s, aborting",
                job.title, job.company,
            )
            self.tracker.track_error(
                job, "Resume PDF was not generated - email not sent"
            )
            return "error"

        if not job.url or not job.url.startswith("http"):
            logger.warning(
                "VALIDATION: invalid job URL for %s @ %s — sending email anyway",
                job.title, job.company,
            )

        # --- RULE 4: Email the user instead of applying ---
        email_ok = self.emailer.send_job_email(
            job=job,
            ats=final_ats,
            resume_path=record.resume_path,
            resume_filename=record.resume_filename,
        )

        action = "Email Sent" if email_ok else "Email Failed (PDF Saved)"

        self.tracker.track(
            job=job, ats=final_ats, status="email_sent",
            resume_path=record.resume_path,
            resume_filename=record.resume_filename,
            action=action, notes="",
        )
        self.dedup.mark_applied(job)
        self.limiter.record()

        logger.info(
            "%s: %s @ %s — ATS %.1f%% — Resume: %s",
            action.upper(), job.title, job.company,
            final_ats.overall_score, record.resume_filename,
        )
        return "email_sent"

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
