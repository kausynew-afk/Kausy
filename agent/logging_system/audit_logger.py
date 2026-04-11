"""Audit logger -- writes structured logs for human review."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import ATSResult, ApplicationRecord, JobListing
from ..pdf_converter import md_to_pdf

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
        resume_filename = ""
        if self._save_resumes and status != "skipped":
            resume_filename = job.resume_filename
            resume_path = self._save_resume(job, tailored_resume, resume_filename)

        record = ApplicationRecord(
            job=job,
            ats_score=ats.overall_score,
            resume_path=resume_path,
            resume_filename=resume_filename,
            status=status,
            notes=notes,
        )
        self._records.append(record)
        self._append_to_csv(record)
        self._write_json_detail(record, ats)

        logger.info(
            "Logged: %s @ %s — ATS %.1f%% [%s] | Resume: %s",
            job.title, job.company, ats.overall_score, status, resume_filename or "N/A",
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
            "| # | Job Code | Company | Title | Platform | ATS Score | Status | Resume File |",
            "|---|----------|---------|-------|----------|-----------|--------|-------------|",
        ]

        for i, rec in enumerate(self._records, 1):
            code = rec.job.job_code or "NA"
            lines.append(
                f"| {i} | {code} | {rec.job.company} | {rec.job.title} | "
                f"{rec.job.platform} | {rec.ats_score:.1f}% | {rec.status} | "
                f"{rec.resume_filename or 'N/A'} |"
            )

        lines.append("")
        applied = sum(1 for r in self._records if r.status in ("logged", "email_sent"))
        skipped = sum(1 for r in self._records if r.status == "skipped")
        errors = sum(1 for r in self._records if r.status == "error")
        avg_score = (
            sum(r.ats_score for r in self._records) / len(self._records)
            if self._records else 0
        )
        lines.extend([
            f"**Emailed:** {applied}  ",
            f"**Skipped (duplicate/low-score):** {skipped}  ",
            f"**Errors:** {errors}  ",
            f"**Average ATS Score:** {avg_score:.1f}%  ",
        ])

        summary_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Summary written to %s", summary_path)
        return summary_path

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def records(self) -> list[ApplicationRecord]:
        return self._records

    def _save_resume(self, job: JobListing, resume_md: str, filename: str) -> str:
        pdf_path = self._out_dir / filename
        try:
            md_to_pdf(resume_md, pdf_path)
        except Exception as e:
            logger.error("PDF conversion failed for %s: %s — saving as .md fallback", filename, e)
            fallback = pdf_path.with_suffix(".md")
            fallback.write_text(resume_md, encoding="utf-8")
            return str(fallback)
        return str(pdf_path)

    def _append_to_csv(self, record: ApplicationRecord) -> None:
        csv_path = self._log_dir / f"applications_{self._run_id}.csv"
        write_header = not csv_path.exists()

        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow([
                    "timestamp", "job_code", "platform", "company", "title",
                    "location", "ats_score", "status", "action",
                    "url", "resume_file", "notes",
                ])
            writer.writerow([
                record.applied_at,
                record.job.job_code or "NA",
                record.job.platform,
                record.job.company,
                record.job.title,
                record.job.location,
                record.ats_score,
                record.status,
                "Email Sent" if record.status in ("logged", "email_sent") else "Skipped",
                record.job.url,
                record.resume_filename,
                record.notes,
            ])

    def _write_json_detail(self, record: ApplicationRecord, ats: ATSResult) -> None:
        detail = {
            "job": {
                "uid": record.job.uid,
                "job_code": record.job.job_code or "NA",
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
            "action": "Email Sent" if record.status in ("logged", "email_sent") else "Skipped",
            "status": record.status,
            "resume_file": record.resume_filename,
            "resume_path": record.resume_path,
            "applied_at": record.applied_at,
            "notes": record.notes,
        }

        json_path = self._log_dir / f"detail_{record.job.uid}_{self._run_id}.json"
        json_path.write_text(json.dumps(detail, indent=2), encoding="utf-8")
