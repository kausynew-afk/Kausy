"""Data models shared across all agent modules."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class JobListing:
    title: str
    company: str
    location: str
    description: str
    url: str
    platform: str
    salary: Optional[str] = None
    posted_date: Optional[str] = None
    job_type: Optional[str] = None
    experience_level: Optional[str] = None
    job_code: Optional[str] = None

    @property
    def uid(self) -> str:
        raw = f"{self.platform}|{self.company}|{self.title}|{self.url}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @property
    def dedup_keys(self) -> dict[str, str]:
        """Multiple keys used for duplicate detection."""
        return {
            "uid": self.uid,
            "company_title": f"{self._normalize(self.company)}|{self._normalize(self.title)}",
            "job_code": self._normalize(self.job_code or ""),
        }

    @property
    def safe_company(self) -> str:
        return re.sub(r"[^a-zA-Z0-9]", "", self.company)

    @property
    def safe_title(self) -> str:
        return re.sub(r"[^a-zA-Z0-9]", "", self.title)

    @property
    def resume_filename(self) -> str:
        """JobCode_CompanyName_Designation_Date.pdf"""
        code = self.job_code or "NA"
        code_clean = re.sub(r"[^a-zA-Z0-9_-]", "", code)
        date_str = datetime.now().strftime("%Y-%m-%d")
        return f"{code_clean}_{self.safe_company}_{self.safe_title}_{date_str}.pdf"

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())


@dataclass
class ATSResult:
    overall_score: float
    technical_matches: list[str] = field(default_factory=list)
    technical_missing: list[str] = field(default_factory=list)
    soft_skill_matches: list[str] = field(default_factory=list)
    soft_skill_missing: list[str] = field(default_factory=list)
    cert_matches: list[str] = field(default_factory=list)
    cert_missing: list[str] = field(default_factory=list)
    title_match_score: float = 0.0
    experience_match_score: float = 0.0
    iteration: int = 1


@dataclass
class ApplicationRecord:
    job: JobListing
    ats_score: float
    resume_path: str
    resume_filename: str = ""
    applied_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "logged"  # logged | applied | skipped | error
    notes: str = ""
