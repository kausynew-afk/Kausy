"""Applied Jobs Tracker — persistent record of all processed jobs."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import ATSResult, JobListing

logger = logging.getLogger(__name__)


class JobTracker:
    """Maintains a master JSON file of all jobs processed across runs.

    File: data/logs/tracked_applications.json
    Each entry contains: company, position, platform, location, url,
    ats_score, status, applied_date, resume_path, and skill gaps.
    """

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
        notes: str = "",
    ) -> None:
        """Add a job to the tracker."""
        entry = {
            "company": job.company,
            "position": job.title,
            "platform": job.platform,
            "location": job.location,
            "url": job.url,
            "salary": job.salary or "Not disclosed",
            "ats_score": ats.overall_score,
            "status": status,
            "applied_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
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
            "Tracked: %s @ %s — %s (ATS %.1f%%)",
            job.title, job.company, status, ats.overall_score,
        )

    def _persist(self) -> None:
        self._path.write_text(
            json.dumps(self._records, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def write_tracker_report(self, output_dir: str = "output") -> Path:
        """Generate a human-readable Markdown report of all tracked jobs."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        report_path = out / "applied_jobs_report.md"

        logged = [r for r in self._records if r["status"] == "logged"]
        skipped = [r for r in self._records if r["status"] == "skipped"]

        lines = [
            "# Applied Jobs Tracker\n",
            f"**Total jobs tracked:** {len(self._records)}  ",
            f"**Logged (matched):** {len(logged)}  ",
            f"**Skipped (low score):** {len(skipped)}  ",
            f"**Last updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            "---\n",
        ]

        if logged:
            lines.append("## Matched Jobs (Logged)\n")
            lines.append("| # | Company | Position | Platform | Location | ATS Score | Date | URL |")
            lines.append("|---|---------|----------|----------|----------|-----------|------|-----|")
            for i, r in enumerate(logged, 1):
                url_short = r['url'][:50] + "..." if len(r['url']) > 50 else r['url']
                lines.append(
                    f"| {i} | {r['company']} | {r['position']} | {r['platform']} | "
                    f"{r['location']} | {r['ats_score']:.1f}% | {r['applied_date']} | "
                    f"[Link]({r['url']}) |"
                )
            lines.append("")

        if skipped:
            lines.append("## Skipped Jobs (Low ATS Score)\n")
            lines.append("| # | Company | Position | Platform | ATS Score | Date | Reason |")
            lines.append("|---|---------|----------|----------|-----------|------|--------|")
            for i, r in enumerate(skipped, 1):
                lines.append(
                    f"| {i} | {r['company']} | {r['position']} | {r['platform']} | "
                    f"{r['ats_score']:.1f}% | {r['applied_date']} | {r['notes']} |"
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

    @property
    def total_tracked(self) -> int:
        return len(self._records)

    @property
    def total_logged(self) -> int:
        return sum(1 for r in self._records if r["status"] == "logged")
