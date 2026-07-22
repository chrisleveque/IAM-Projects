"""Configuration loading: config.yaml + .env, rooted at the project directory."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class SearchSpec(BaseModel):
    source: str  # "linkedin" | "indeed"
    query: str
    location: str = ""
    easy_apply_only: bool = True
    max_results: int = 25


class Limits(BaseModel):
    max_applications_per_day: int = 10
    min_action_delay_seconds: float = 2.0
    max_action_delay_seconds: float = 6.0
    min_job_delay_seconds: float = 20.0
    max_job_delay_seconds: float = 60.0


class ScoringConfig(BaseModel):
    min_score_to_tailor: int = 60


class AIConfig(BaseModel):
    model: str = "claude-sonnet-5"
    max_tokens: int = 8192


class PathsConfig(BaseModel):
    output_dir: str = "output"
    db_path: str = "jobagent.db"
    browser_profile: str = "browser_profile"
    master_resume: str = "profile/master_resume.md"
    answers: str = "profile/answers.yaml"


class AppConfig(BaseModel):
    searches: list[SearchSpec] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    root: Path = Path(".")

    def resolve(self, rel: str) -> Path:
        return (self.root / rel).resolve()

    @property
    def db_path(self) -> Path:
        return self.resolve(self.paths.db_path)

    @property
    def output_dir(self) -> Path:
        return self.resolve(self.paths.output_dir)

    @property
    def master_resume_path(self) -> Path:
        return self.resolve(self.paths.master_resume)

    @property
    def answers_path(self) -> Path:
        return self.resolve(self.paths.answers)


def find_root(start: Path | None = None) -> Path:
    """Locate the jobagent project dir (contains config.yaml + profile/).

    Honors JOBAGENT_HOME, otherwise walks up from the current directory.
    """
    env = os.environ.get("JOBAGENT_HOME")
    if env:
        return Path(env).resolve()
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "config.yaml").exists() and (candidate / "profile").is_dir():
            return candidate
    return cur


def load_config(root: Path | str | None = None) -> AppConfig:
    root_path = find_root() if root is None else Path(root).resolve()
    load_dotenv(root_path / ".env")
    data: dict = {}
    cfg_file = root_path / "config.yaml"
    if cfg_file.exists():
        data = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    cfg = AppConfig(**data)
    cfg.root = root_path
    return cfg
