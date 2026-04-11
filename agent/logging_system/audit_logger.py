"""Audit logger -- writes structured logs for human review."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import ATSResult, ApplicationRecord, JobListing

logger = logging.getLogger(__name__)


class AuditLogger:
    """Persists every job-processing event for human-in-the-loop review."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._log_dir = Path(config.get("logging", {}).get("log_directory", "data/logs"))
        self._out_dir = Path(config.get("logging", {}).get("output_directory", "output"))
        self._save_resumes = config.get("logging", {}).get("save_modified_resumes", True)

        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._out_dir.mkdir(parents=True, exist_ok=True)

        self._run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._records: list[ApplicationRecord] = []

    def log_application(
        self,
        job: JobListing,
        ats: ATSResult,
        tailored_resume: str,
        status: str = "logged",
        notes: str = "",
    ) -> ApplicationRecord:
        resume_path = ""
        if self._save_resumes:
            resume_path = self._save_resume(job, tailored_resume)

        record = ApplicationRecord(
            job=job,
            ats_score=ats.overall_score,
            resume_path=resume_path,
            status=status,
            notes=notes,
        )
        self._records.append(record)
        self._append_to_csv(record)
        self._write_json_detail(record, ats)

        logger.info(
            "Logged: %s @ %s — ATS %.1f%% [%s]",
            job.title, job.company, ats.overall_score, status,
        )
        return record

    def write_summary(self) -> Path:
        """Write a human-readable run summary."""
        summary_path = self._out_dir / f"run_summary_{self._run_id}.md"
        lines = [
            f"# Job Application Agent — Run {self._run_id}\n",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            f"**Total jobs processed:** {len(self._records)}\n",
            "",
            "| # | Company | Title | Platform | ATS Score | Status |",
            "|---|---------|-------|----------|-----------|--------|",
        ]

        for i, rec in enumerate(self._records, 1):
            lines.append(
                f"| {i} | {rec.job.company} | {rec.job.title} | "
                f"{rec.job.platform} | {rec.ats_score:.1f}% | {rec.status} |"
            )

        lines.append("")
        applied = sum(1 for r in self._records if r.status == "logged")
        skipped = sum(1 for r in self._records if r.status == "skipped")
        avg_score = (
            sum(r.ats_score for r in self._records) / len(self._records)
            if self._records else 0
        )
        lines.extend([
            f"**Applied/Logged:** {applied}  ",
            f"**Skipped (duplicate/low-score):** {skipped}  ",
            f"**Average ATS Score:** {avg_score:.1f}%  ",
        ])

        summary_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Summary written to %s", summary_path)
        return summary_path

    def _save_resume(self, job: JobListing, resume_md: str) -> str:
        safe_company = "".join(c if c.isalnum() else "_" for c in job.company)
        safe_title = "".join(c if c.isalnum() else "_" for c in job.title)
        filename = f"resume_{safe_company}_{safe_title}_{self._run_id}.md"
        path = self._out_dir / filename
        path.write_text(resume_md, encoding="utf-8")
        return str(path)

    def _append_to_csv(self, record: ApplicationRecord) -> None:
        csv_path = self._log_dir / f"applications_{self._run_id}.csv"
        write_header = not csv_path.exists()

        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow([
                    "timestamp", "platform", "company", "title",
                    "location", "ats_score", "status", "url", "resume_path",
                ])
            writer.writerow([
                record.applied_at, record.job.platform, record.job.company,
                record.job.title, record.job.location, record.ats_score,
                record.status, record.job.url, record.resume_path,
            ])

    def _write_json_detail(self, record: ApplicationRecord, ats: ATSResult) -> None:
        detail = {
            "job": {
                "uid": record.job.uid,
                "title": record.job.title,
                "company": record.job.company,
                "location": record.job.location,
                "platform": record.job.platform,
                "url": record.job.url,
            },
            "ats": {
                "overall_score": ats.overall_score,
                "iteration": ats.iteration,
                "technical_matches": ats.technical_matches,
                "technical_missing": ats.technical_missing,
                "soft_skill_matches": ats.soft_skill_matches,
                "soft_skill_missing": ats.soft_skill_missing,
                "cert_matches": ats.cert_matches,
                "cert_missing": ats.cert_missing,
            },
            "status": record.status,
            "resume_path": record.resume_path,
            "applied_at": record.applied_at,
        }

        json_path = self._log_dir / f"detail_{record.job.uid}_{self._run_id}.json"
        json_path.write_text(json.dumps(detail, indent=2), encoding="utf-8")
