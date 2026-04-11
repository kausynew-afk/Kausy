"""Applied Jobs Tracker — persistent record of all processed jobs.

Tracks: Job Code, Company, Position, Platform, Action (Applied/Skipped),
Reason, Resume File Name, ATS Score, Date, URL, Skill Gaps.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import ATSResult, JobListing

logger = logging.getLogger(__name__)


class JobTracker:
    """Maintains a master JSON file of all jobs processed across runs."""

    def __init__(self, config: dict[str, Any]) -> None:
        log_dir = Path(config.get("logging", {}).get("log_directory", "data/logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        self._path = log_dir / "tracked_applications.json"
        self._records: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._records = json.loads(self._path.read_text(encoding="utf-8"))
                logger.info("Tracker: loaded %d historical applications", len(self._records))
            except (json.JSONDecodeError, TypeError):
                logger.warning("Tracker: corrupt file, starting fresh")
                self._records = []

    def track(
        self,
        job: JobListing,
        ats: ATSResult,
        status: str,
        resume_path: str = "",
        resume_filename: str = "",
        action: str = "",
        notes: str = "",
    ) -> None:
        entry = {
            "job_code": job.job_code or "NA",
            "company": job.company,
            "position": job.title,
            "platform": job.platform,
            "location": job.location,
            "url": job.url,
            "salary": job.salary or "Not disclosed",
            "ats_score": ats.overall_score,
            "status": status,
            "action": action or ("Applied" if status == "logged" else "Skipped"),
            "reason": notes if status != "logged" else "",
            "applied_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "resume_file": resume_filename,
            "resume_path": resume_path,
            "matched_skills": ats.technical_matches,
            "missing_skills": ats.technical_missing,
            "matched_soft_skills": ats.soft_skill_matches,
            "matched_certs": ats.cert_matches,
            "notes": notes,
        }
        self._records.append(entry)
        self._persist()

        logger.info(
            "Tracked: %s @ %s — %s (ATS %.1f%%) — Resume: %s",
            job.title, job.company, entry["action"],
            ats.overall_score, resume_filename or "N/A",
        )

    def track_skip(self, job: JobListing, reason: str) -> None:
        """Log a skipped job (duplicate / empty JD) without ATS analysis."""
        entry = {
            "job_code": job.job_code or "NA",
            "company": job.company,
            "position": job.title,
            "platform": job.platform,
            "location": job.location,
            "url": job.url,
            "salary": job.salary or "Not disclosed",
            "ats_score": 0,
            "status": "skipped",
            "action": "Skipped",
            "reason": reason,
            "applied_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "resume_file": "",
            "resume_path": "",
            "matched_skills": [],
            "missing_skills": [],
            "matched_soft_skills": [],
            "matched_certs": [],
            "notes": reason,
        }
        self._records.append(entry)
        self._persist()
        logger.info("Tracked SKIP: %s @ %s — %s", job.title, job.company, reason)

    def track_error(self, job: JobListing, error_msg: str) -> None:
        """Log a failed job processing attempt."""
        entry = {
            "job_code": job.job_code or "NA",
            "company": job.company,
            "position": job.title,
            "platform": job.platform,
            "location": job.location,
            "url": job.url,
            "salary": job.salary or "Not disclosed",
            "ats_score": 0,
            "status": "error",
            "action": "Error",
            "reason": error_msg[:200],
            "applied_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "resume_file": "",
            "resume_path": "",
            "matched_skills": [],
            "missing_skills": [],
            "matched_soft_skills": [],
            "matched_certs": [],
            "notes": error_msg[:200],
        }
        self._records.append(entry)
        self._persist()
        logger.info("Tracked ERROR: %s @ %s — %s", job.title, job.company, error_msg[:100])

    def _persist(self) -> None:
        self._path.write_text(
            json.dumps(self._records, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def write_tracker_report(self, output_dir: str = "output") -> Path:
        """Generate a Markdown report of all tracked jobs."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        report_path = out / "applied_jobs_report.md"

        applied = [r for r in self._records if r["action"] == "Applied"]
        skipped = [r for r in self._records if r["action"] == "Skipped"]
        errors = [r for r in self._records if r["action"] == "Error"]

        lines = [
            "# Job Application Tracker Report\n",
            f"**Total jobs processed:** {len(self._records)}  ",
            f"**Applied:** {len(applied)}  ",
            f"**Skipped:** {len(skipped)}  ",
            f"**Errors:** {len(errors)}  ",
            f"**Last updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            "---\n",
        ]

        if applied:
            lines.append("## Applied Jobs\n")
            lines.append("| # | Job Code | Company | Position | Platform | ATS Score | Date | Resume File | URL |")
            lines.append("|---|----------|---------|----------|----------|-----------|------|-------------|-----|")
            for i, r in enumerate(applied, 1):
                lines.append(
                    f"| {i} | {r['job_code']} | {r['company']} | {r['position']} | "
                    f"{r['platform']} | {r['ats_score']:.1f}% | {r['applied_date']} | "
                    f"{r['resume_file']} | [Link]({r['url']}) |"
                )
            lines.append("")

        if skipped:
            lines.append("## Skipped Jobs\n")
            lines.append("| # | Job Code | Company | Position | Platform | ATS Score | Reason |")
            lines.append("|---|----------|---------|----------|----------|-----------|--------|")
            for i, r in enumerate(skipped, 1):
                lines.append(
                    f"| {i} | {r['job_code']} | {r['company']} | {r['position']} | "
                    f"{r['platform']} | {r['ats_score']:.1f}% | {r['reason'][:80]} |"
                )
            lines.append("")

        if errors:
            lines.append("## Errors\n")
            lines.append("| # | Company | Position | Error |")
            lines.append("|---|---------|----------|-------|")
            for i, r in enumerate(errors, 1):
                lines.append(
                    f"| {i} | {r['company']} | {r['position']} | {r['reason'][:80]} |"
                )
            lines.append("")

        lines.append("---\n")
        lines.append("## Skill Gap Analysis\n")

        all_missing: dict[str, int] = {}
        for r in self._records:
            for skill in r.get("missing_skills", []):
                all_missing[skill] = all_missing.get(skill, 0) + 1

        if all_missing:
            sorted_gaps = sorted(all_missing.items(), key=lambda x: x[1], reverse=True)
            lines.append("Most commonly requested skills you're missing:\n")
            lines.append("| Skill | Times Requested |")
            lines.append("|-------|----------------|")
            for skill, count in sorted_gaps[:15]:
                lines.append(f"| {skill} | {count} |")
        else:
            lines.append("No skill gaps detected yet.\n")

        report_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Tracker report written to %s", report_path)
        return report_path

    def get_current_run_records(self, run_start: str) -> list[dict]:
        """Get records from the current run only (for email report)."""
        return [r for r in self._records if r["applied_date"] >= run_start]

    @property
    def total_tracked(self) -> int:
        return len(self._records)

    @property
    def total_logged(self) -> int:
        return sum(1 for r in self._records if r["action"] == "Applied")
