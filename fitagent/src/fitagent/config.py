"""Configuration loading: config.yaml + .env, rooted at the project directory."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

MODES = ("dry_run", "live")
TTS_PROVIDERS = ("edge", "elevenlabs", "mock")
PRIVACIES = ("private", "unlisted", "public")


class TTSConfig(BaseModel):
    provider: str = "edge"
    voice: str = "en-US-ChristopherNeural"
    rate: str = "-8%"
    pitch: str = "-4Hz"


class PresetConfig(BaseModel):
    channel_name: str = "The Forge"
    niche: str = "men's fitness & discipline motivation"
    tone: str = "dark, gritty, stoic; earned intensity, no toxic positivity"
    audience: str = "men 18-40 pushing through training and life plateaus"
    original_ratio: float = 0.8
    tts: TTSConfig = Field(default_factory=TTSConfig)
    seo_hints: list[str] = Field(default_factory=lambda: ["gym motivation", "discipline"])


class LongFormConfig(BaseModel):
    min_minutes: float = 5
    max_minutes: float = 10
    width: int = 1920
    height: int = 1080
    fps: int = 30
    crf: int = 20


class ShortsConfig(BaseModel):
    count: int = 3
    max_seconds: float = 58
    width: int = 1080
    height: int = 1920


class VideoConfig(BaseModel):
    long_form: LongFormConfig = Field(default_factory=LongFormConfig)
    shorts: ShortsConfig = Field(default_factory=ShortsConfig)


class AudioConfig(BaseModel):
    voice_lufs: float = -16
    final_lufs: float = -14
    music_volume: float = 0.9
    duck_ratio: float = 8


class PublishingConfig(BaseModel):
    auto_upload: bool = False
    default_privacy: str = "private"
    category_id: str = "22"


class AIConfig(BaseModel):
    model: str = "claude-opus-4-8"
    max_tokens: int = 8192
    max_tool_iterations: int = 24


class PathsConfig(BaseModel):
    db_path: str = "fitagent.db"
    output_dir: str = "output"
    assets_dir: str = "assets"
    youtube_client_secrets: str = "client_secret.json"


class AppConfig(BaseModel):
    mode: str = "dry_run"
    active_preset: str = "forge"
    presets: dict[str, PresetConfig] = Field(default_factory=lambda: {"forge": PresetConfig()})
    video: VideoConfig = Field(default_factory=VideoConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)
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
    def assets_dir(self) -> Path:
        return self.resolve(self.paths.assets_dir)

    @property
    def music_dir(self) -> Path:
        return self.assets_dir / "music"

    @property
    def fonts_dir(self) -> Path:
        return self.assets_dir / "fonts"

    @property
    def public_domain_dir(self) -> Path:
        return self.assets_dir / "public_domain"

    @property
    def cache_dir(self) -> Path:
        return self.output_dir / "cache"

    def preset(self, name: str | None = None) -> PresetConfig:
        key = name or self.active_preset
        if key not in self.presets:
            raise ValueError(f"unknown preset {key!r}; configured: {sorted(self.presets)}")
        return self.presets[key]

    # ---- effective modes ---------------------------------------------------
    # dry_run mocks integrations that would hit external APIs for assets or
    # uploads. TTS is independent of mode: the edge provider is free and the
    # voiceover IS the product, so a dry run still talks. Tests set
    # tts.provider: mock explicitly.

    def stock_mode(self) -> str:
        """'live' or 'mock' for the stock footage APIs."""
        if self.mode != "live":
            return "mock"
        if os.environ.get("PEXELS_API_KEY") or os.environ.get("PIXABAY_API_KEY"):
            return "live"
        return "mock"

    def tts_provider(self, preset: PresetConfig) -> str:
        """Effective TTS provider; elevenlabs falls back to edge without creds."""
        p = preset.tts.provider
        if p not in TTS_PROVIDERS:
            raise ValueError(f"tts.provider must be one of {TTS_PROVIDERS}, got {p!r}")
        if p == "elevenlabs" and not (
            os.environ.get("ELEVENLABS_API_KEY") and os.environ.get("ELEVENLABS_VOICE_ID")
        ):
            return "edge"
        return p

    def youtube_client_secrets(self) -> Path:
        env = os.environ.get("YOUTUBE_CLIENT_SECRETS")
        return self.resolve(env) if env else self.resolve(self.paths.youtube_client_secrets)

    def youtube_token_path(self, preset_name: str | None = None) -> Path:
        name = preset_name or self.active_preset
        return self.resolve(f".youtube_token.{name}.json")

    def youtube_mode(self, preset_name: str | None = None) -> str:
        """'live' or 'mock' for YouTube uploads."""
        if self.mode != "live":
            return "mock"
        if self.youtube_client_secrets().exists() and self.youtube_token_path(preset_name).exists():
            return "live"
        return "mock"


def find_root(start: Path | None = None) -> Path:
    """Locate the fitagent project dir (contains config.yaml).

    Honors FITAGENT_HOME, otherwise walks up from the current directory.
    """
    env = os.environ.get("FITAGENT_HOME")
    if env:
        return Path(env).resolve()
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "config.yaml").exists() and (candidate / "src" / "fitagent").is_dir():
            return candidate
    return cur


def load_config(root: Path | str | None = None) -> AppConfig:
    root_path = find_root() if root is None else Path(root).resolve()
    load_dotenv(root_path / ".env")
    data: dict = {}
    cfg_file = root_path / "config.yaml"
    if cfg_file.exists():
        data = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    if data.get("mode") not in (None, *MODES):
        raise ValueError(f"config.yaml mode must be one of {MODES}, got {data['mode']!r}")
    privacy = (data.get("publishing") or {}).get("default_privacy")
    if privacy not in (None, *PRIVACIES):
        raise ValueError(f"publishing.default_privacy must be one of {PRIVACIES}, got {privacy!r}")
    cfg = AppConfig(**data)
    cfg.root = root_path
    return cfg
