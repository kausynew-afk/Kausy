"""Extracts and categorises keywords from job descriptions and resumes."""

from __future__ import annotations

import re

TECHNICAL_KEYWORDS = {
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "rust",
    "ruby", "php", "swift", "kotlin", "scala", "r", "matlab", "sql", "nosql",
    "react", "angular", "vue", "node.js", "express", "django", "flask",
    "spring", "spring boot", ".net", "rails", "fastapi", "next.js",
    "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "ansible",
    "jenkins", "github actions", "ci/cd", "devops", "linux", "unix",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "kafka",
    "rabbitmq", "graphql", "rest", "grpc", "microservices", "serverless",
    "machine learning", "deep learning", "nlp", "computer vision",
    "tensorflow", "pytorch", "scikit-learn", "pandas", "numpy",
    "data engineering", "etl", "spark", "hadoop", "airflow", "dbt",
    "git", "jira", "confluence", "agile", "scrum", "kanban",
    "html", "css", "sass", "tailwind", "bootstrap", "figma",
    "api", "oauth", "jwt", "sso", "saml", "security", "encryption",
    "system design", "distributed systems", "caching", "load balancing",
    "data structures", "algorithms", "oop", "design patterns",
    "playwright", "selenium", "cypress", "jest", "pytest", "unittest",
    "tableau", "power bi", "looker", "excel", "sap", "salesforce",
    "testng", "rest assured", "postman", "soap", "soap ui",
    "hp alm", "octane", "svn", "page object model", "pom",
    "data-driven", "bdd", "tdd", "cucumber",
    "mainframe", "jcl", "cics",
}

SOFT_SKILLS = {
    "communication", "leadership", "teamwork", "collaboration",
    "problem solving", "problem-solving", "critical thinking",
    "time management", "adaptability", "creativity", "innovation",
    "attention to detail", "analytical", "interpersonal",
    "presentation", "mentoring", "coaching", "negotiation",
    "conflict resolution", "decision making", "decision-making",
    "strategic thinking", "stakeholder management",
    "cross-functional", "self-motivated", "proactive",
    "fast-paced", "deadline-driven", "multitasking",
    "root cause analysis", "defect triage",
}

CERTIFICATIONS = {
    "aws certified", "aws solutions architect", "aws developer",
    "azure certified", "az-900", "az-104", "az-204", "az-400",
    "gcp certified", "google cloud certified",
    "kubernetes certified", "cka", "ckad", "ckss",
    "pmp", "scrum master", "csm", "psm", "safe",
    "cissp", "cism", "ceh", "comptia security+", "comptia a+",
    "itil", "togaf", "six sigma",
    "terraform certified", "hashicorp certified",
    "oracle certified", "cisco certified", "ccna", "ccnp",
    "data engineer", "data scientist", "machine learning engineer",
    "istqb", "istqb certified", "ctfl", "cste",
}


class KeywordExtractor:
    """Extracts categorized keywords from text using pattern matching."""

    def __init__(self) -> None:
        self._tech = TECHNICAL_KEYWORDS
        self._soft = SOFT_SKILLS
        self._certs = CERTIFICATIONS

    @staticmethod
    def _normalise(text: str) -> str:
        return re.sub(r"\s+", " ", text.lower().strip())

    def extract_technical(self, text: str) -> set[str]:
        norm = self._normalise(text)
        return {kw for kw in self._tech if kw in norm}

    def extract_soft_skills(self, text: str) -> set[str]:
        norm = self._normalise(text)
        return {kw for kw in self._soft if kw in norm}

    def extract_certifications(self, text: str) -> set[str]:
        norm = self._normalise(text)
        return {kw for kw in self._certs if kw in norm}

    def extract_all(self, text: str) -> dict[str, set[str]]:
        return {
            "technical": self.extract_technical(text),
            "soft_skills": self.extract_soft_skills(text),
            "certifications": self.extract_certifications(text),
        }

    @staticmethod
    def extract_years_experience(text: str) -> int | None:
        """Pull the maximum 'X+ years' number from text."""
        matches = re.findall(r"(\d+)\+?\s*(?:years?|yrs?)", text, re.IGNORECASE)
        return max(int(m) for m in matches) if matches else None
