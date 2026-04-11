"""Loads and validates the YAML configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path.resolve()}")

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    _validate(cfg)
    return cfg


def _validate(cfg: dict) -> None:
    required_sections = ["profile", "scraping", "ats", "safety", "logging"]
    for section in required_sections:
        if section not in cfg:
            raise ValueError(f"Missing required config section: '{section}'")

    if not cfg["profile"].get("job_title"):
        raise ValueError("profile.job_title must be set in config.yaml")
    if not cfg["profile"].get("location"):
        raise ValueError("profile.location must be set in config.yaml")
    if cfg["ats"].get("target_score", 0) < 1 or cfg["ats"].get("target_score", 0) > 100:
        raise ValueError("ats.target_score must be between 1 and 100")
