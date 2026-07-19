"""Pydantic contracts for every agent's JSON output. The deterministic
pipeline consumes these — validation failures are re-prompted, so nothing
malformed flows downstream."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

SEGMENT_ROLES = ("hook", "build", "peak", "resolve", "outro")
MOODS = ("gritty", "dark", "epic", "calm")


class Concept(BaseModel):
    working_title: str
    theme: str
    angle: str
    source_type: str
    pd_source: str | None = None
    hook: str
    emotional_arc: list[str] = Field(default_factory=list)
    target_minutes: float = 7
    visual_world: str = ""
    rationale: str = ""

    @field_validator("source_type")
    @classmethod
    def _source(cls, v: str) -> str:
        if v not in ("original", "public_domain"):
            raise ValueError("source_type must be 'original' or 'public_domain'")
        return v


class ConceptOutput(BaseModel):
    concept: Concept


class Segment(BaseModel):
    id: str
    text: str
    role: str = "build"
    energy: int = 3
    visual_theme: str = ""
    pd_verbatim: bool = False
    pause_after_ms: int = 500

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in SEGMENT_ROLES:
            raise ValueError(f"role must be one of {SEGMENT_ROLES}")
        return v

    @field_validator("energy")
    @classmethod
    def _energy(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("energy must be 1-5")
        return v


class ShortsCandidate(BaseModel):
    segment_ids: list[str]
    hook_line: str = ""
    why: str = ""


class Script(BaseModel):
    title_working: str
    estimated_minutes: float
    segments: list[Segment]
    pd_attribution: str | None = None
    shorts_candidates: list[ShortsCandidate] = Field(default_factory=list)

    @field_validator("segments")
    @classmethod
    def _nonempty(cls, v: list[Segment]) -> list[Segment]:
        if not v:
            raise ValueError("script must have at least one segment")
        ids = [s.id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("segment ids must be unique")
        return v


class ScriptOutput(BaseModel):
    script: Script


class Shot(BaseModel):
    query: str
    provider: str = ""
    clip_id: str = ""
    fallback_queries: list[str] = Field(default_factory=list)
    target_seconds: float = 4.0


class SegmentShots(BaseModel):
    segment_id: str
    shots: list[Shot]
    mood: str = "gritty"

    @field_validator("mood")
    @classmethod
    def _mood(cls, v: str) -> str:
        return v if v in MOODS else "gritty"

    @field_validator("shots")
    @classmethod
    def _has_shots(cls, v: list[Shot]) -> list[Shot]:
        if not v:
            raise ValueError("each segment needs at least one shot")
        return v


class ShotPlanOutput(BaseModel):
    shot_plan: list[SegmentShots]
    reuse_notes: str = ""


class LongFormMetadata(BaseModel):
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    category_id: str = "22"
    thumbnail_text: str = ""

    @field_validator("title")
    @classmethod
    def _title_len(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError("YouTube titles are capped at 100 characters")
        return v

    @field_validator("tags")
    @classmethod
    def _tags_len(cls, v: list[str]) -> list[str]:
        while sum(len(t) + 1 for t in v) > 480:
            v = v[:-1]
        return v


class ShortMetadata(BaseModel):
    for_segments: list[str]
    title: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def _title_len(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError("YouTube titles are capped at 100 characters")
        return v


class MetadataOutput(BaseModel):
    long_form: LongFormMetadata
    shorts: list[ShortMetadata] = Field(default_factory=list)
