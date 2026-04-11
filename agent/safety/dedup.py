"""Deduplication guard -- prevents applying to the same job twice.

A job is duplicate if ANY of these match a previous record:
  1. Company Name + Job Title (normalized)
  2. Job Code / Job ID (if present)
  3. SHA-256 UID (platform|company|title|url)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..models import JobListing

logger = logging.getLogger(__name__)


class DeduplicationGuard:
    """Maintains a JSON ledger of previously-seen jobs with multi-key matching."""

    def __init__(self, config: dict[str, Any]) -> None:
        db_path = config.get("safety", {}).get(
            "duplicate_check_db", "data/logs/applied_jobs.json"
        )
        self._path = Path(db_path)
        self._uids: set[str] = set()
        self._company_titles: set[str] = set()
        self._job_codes: set[str] = set()
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._uids = set(data.get("applied_uids", []))
                self._company_titles = set(data.get("company_titles", []))
                self._job_codes = set(data.get("job_codes", []))
                logger.info(
                    "Loaded dedup DB: %d UIDs, %d company+title combos, %d job codes",
                    len(self._uids), len(self._company_titles), len(self._job_codes),
                )
            except (json.JSONDecodeError, KeyError):
                logger.warning("Corrupt dedup DB, starting fresh")

    def is_duplicate(self, job: JobListing) -> str:
        """Return the reason string if duplicate, empty string if new."""
        keys = job.dedup_keys

        if keys["uid"] in self._uids:
            return "Duplicate UID (same platform+company+title+url)"

        if keys["company_title"] and keys["company_title"] in self._company_titles:
            return "Duplicate Company+Title match"

        if keys["job_code"] and keys["job_code"] in self._job_codes:
            return f"Duplicate Job Code: {job.job_code}"

        return ""

    def mark_applied(self, job: JobListing) -> None:
        keys = job.dedup_keys
        self._uids.add(keys["uid"])
        if keys["company_title"]:
            self._company_titles.add(keys["company_title"])
        if keys["job_code"]:
            self._job_codes.add(keys["job_code"])
        self._persist()

    def clear(self) -> None:
        """Reset the dedup database."""
        self._uids.clear()
        self._company_titles.clear()
        self._job_codes.clear()
        self._persist()
        logger.info("Dedup database cleared")

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "applied_uids": sorted(self._uids),
            "company_titles": sorted(self._company_titles),
            "job_codes": sorted(self._job_codes),
        }
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @property
    def total_applied(self) -> int:
        return len(self._uids)
