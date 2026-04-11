"""Deduplication guard -- prevents applying to the same job twice."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..models import JobListing

logger = logging.getLogger(__name__)


class DeduplicationGuard:
    """Maintains a JSON ledger of previously-seen job UIDs."""

    def __init__(self, config: dict[str, Any]) -> None:
        db_path = config.get("safety", {}).get(
            "duplicate_check_db", "data/logs/applied_jobs.json"
        )
        self._path = Path(db_path)
        self._seen: set[str] = set()
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._seen = set(data.get("applied_uids", []))
                logger.info("Loaded %d previously-applied UIDs", len(self._seen))
            except (json.JSONDecodeError, KeyError):
                logger.warning("Corrupt dedup DB, starting fresh")
                self._seen = set()

    def is_duplicate(self, job: JobListing) -> bool:
        return job.uid in self._seen

    def mark_applied(self, job: JobListing) -> None:
        self._seen.add(job.uid)
        self._persist()

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"applied_uids": sorted(self._seen)}
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @property
    def total_applied(self) -> int:
        return len(self._seen)
