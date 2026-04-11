"""Data models shared across all agent modules."""

from __future__ import annotations

import hashlib
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

    @property
    def uid(self) -> str:
        raw = f"{self.platform}|{self.company}|{self.title}|{self.url}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


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
    applied_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "logged"  # logged | applied | skipped | error
    notes: str = ""
