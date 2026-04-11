"""Dynamically tailors the master resume to a specific JD without hallucinating."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ..models import ATSResult, JobListing

logger = logging.getLogger(__name__)


class ResumeModifier:
    """
    Generates a tailored Markdown resume by:
      1. Re-ordering existing bullet points by JD relevance.
      2. Surfacing keywords the candidate already possesses but that are buried.
      3. Injecting missing keywords ONLY into existing experience descriptions
         where the candidate actually used that skill.
      4. Never fabricating roles, projects, certifications, or metrics.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._master_text: str | None = None
        self._master_sections: dict[str, str] = {}

    def load_master(self, path: str | None = None) -> str:
        resume_path = path or self.config["profile"]["master_resume_path"]
        p = Path(resume_path)
        if not p.exists():
            raise FileNotFoundError(f"Master resume not found: {p.resolve()}")
        self._master_text = p.read_text(encoding="utf-8")
        self._master_sections = self._parse_sections(self._master_text)
        return self._master_text

    def tailor(self, job: JobListing, ats_result: ATSResult) -> str:
        """Return a new Markdown resume tailored for the given job."""
        if not self._master_text:
            raise RuntimeError("Call load_master() first")

        sections = dict(self._master_sections)

        sections = self._tailor_summary(sections, job, ats_result)
        sections = self._reorder_experience(sections, job)
        sections = self._enrich_skills(sections, ats_result)
        sections = self._highlight_certifications(sections, ats_result)

        return self._assemble(sections)

    @staticmethod
    def _parse_sections(md: str) -> dict[str, str]:
        """Split a Markdown resume into {heading: content} pairs."""
        parts: dict[str, str] = {}
        current_heading = "_preamble"
        buffer: list[str] = []

        for line in md.splitlines():
            if re.match(r"^#{1,3}\s+", line):
                parts[current_heading] = "\n".join(buffer)
                current_heading = line.strip()
                buffer = []
            else:
                buffer.append(line)

        parts[current_heading] = "\n".join(buffer)
        return parts

    def _tailor_summary(
        self, sections: dict[str, str], job: JobListing, ats: ATSResult
    ) -> dict[str, str]:
        """Inject high-value JD keywords into the professional summary
        only if the keyword already exists somewhere in the master resume."""
        summary_key = self._find_section(sections, ["summary", "objective", "profile"])
        if not summary_key:
            return sections

        master_lower = self._master_text.lower() if self._master_text else ""
        valuable_additions: list[str] = []

        for kw in ats.technical_missing[:5]:
            if kw.lower() in master_lower:
                valuable_additions.append(kw)

        if valuable_additions:
            addition = ", ".join(valuable_additions)
            sections[summary_key] = (
                sections[summary_key].rstrip()
                + f"\n\nKey competencies aligned with this role: {addition}."
            )

        return sections

    def _reorder_experience(
        self, sections: dict[str, str], job: JobListing
    ) -> dict[str, str]:
        """Move bullet points containing JD keywords toward the top of each role."""
        exp_key = self._find_section(sections, ["experience", "work history", "employment"])
        if not exp_key:
            return sections

        jd_lower = job.description.lower()
        lines = sections[exp_key].splitlines()
        bullets: list[tuple[str, int]] = []
        non_bullets: list[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("- ", "* ", "• ")):
                relevance = sum(1 for word in jd_lower.split() if word in stripped.lower())
                bullets.append((line, relevance))
            else:
                if bullets:
                    bullets.sort(key=lambda x: x[1], reverse=True)
                    non_bullets.extend(b[0] for b in bullets)
                    bullets = []
                non_bullets.append(line)

        if bullets:
            bullets.sort(key=lambda x: x[1], reverse=True)
            non_bullets.extend(b[0] for b in bullets)

        sections[exp_key] = "\n".join(non_bullets)
        return sections

    def _enrich_skills(
        self, sections: dict[str, str], ats: ATSResult
    ) -> dict[str, str]:
        """Add missing technical skills to the Skills section ONLY if they
        appear somewhere in the master resume (preventing hallucination)."""
        skills_key = self._find_section(sections, ["skills", "technical skills", "core competencies"])
        if not skills_key:
            return sections

        master_lower = self._master_text.lower() if self._master_text else ""
        existing_section_lower = sections[skills_key].lower()

        safe_adds: list[str] = []
        for kw in ats.technical_missing:
            if kw.lower() in master_lower and kw.lower() not in existing_section_lower:
                safe_adds.append(kw.title())

        for kw in ats.soft_skill_missing:
            if kw.lower() in master_lower and kw.lower() not in existing_section_lower:
                safe_adds.append(kw.title())

        if safe_adds:
            sections[skills_key] = (
                sections[skills_key].rstrip() + "\n- " + "\n- ".join(safe_adds)
            )

        return sections

    def _highlight_certifications(
        self, sections: dict[str, str], ats: ATSResult
    ) -> dict[str, str]:
        """Surface certifications from the master that the JD wants."""
        cert_key = self._find_section(
            sections, ["certifications", "certificates", "credentials", "licenses"]
        )
        if not cert_key:
            return sections

        master_lower = self._master_text.lower() if self._master_text else ""
        for cert in ats.cert_missing:
            if cert.lower() in master_lower and cert.lower() not in sections[cert_key].lower():
                sections[cert_key] = sections[cert_key].rstrip() + f"\n- {cert.title()}"

        return sections

    @staticmethod
    def _find_section(sections: dict[str, str], candidates: list[str]) -> str | None:
        for key in sections:
            heading_lower = key.lower()
            for candidate in candidates:
                if candidate in heading_lower:
                    return key
        return None

    @staticmethod
    def _assemble(sections: dict[str, str]) -> str:
        parts: list[str] = []
        for heading, content in sections.items():
            if heading == "_preamble":
                parts.append(content)
            else:
                parts.append(f"\n{heading}\n{content}")
        return "\n".join(parts).strip() + "\n"
