"""Configuration loading: config.yaml + .env, rooted at the project directory."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

MODES = ("dry_run", "live")


class StoreConfig(BaseModel):
    shop_domain: str = ""
    api_version: str = "2025-07"


class SupplierConfig(BaseModel):
    name: str = "cj"
    ship_to_country: str = "US"


class PricingConfig(BaseModel):
    markup_multiplier: float = 2.5
    min_margin_usd: float = 3.0


class BusinessConfig(BaseModel):
    niches: list[str] = Field(default_factory=lambda: ["pet accessories"])
    pricing: PricingConfig = Field(default_factory=PricingConfig)
    max_new_products_per_run: int = 5
    min_candidate_pool: int = 3


class AIConfig(BaseModel):
    model: str = "claude-opus-4-8"
    max_tokens: int = 8192
    max_tool_iterations: int = 20


class PathsConfig(BaseModel):
    db_path: str = "shopagent.db"
    output_dir: str = "output"
    inbox_dir: str = "inbox"


class AppConfig(BaseModel):
    mode: str = "dry_run"
    store: StoreConfig = Field(default_factory=StoreConfig)
    supplier: SupplierConfig = Field(default_factory=SupplierConfig)
    business: BusinessConfig = Field(default_factory=BusinessConfig)
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
    def inbox_dir(self) -> Path:
        return self.resolve(self.paths.inbox_dir)

    @property
    def shop_domain(self) -> str:
        return self.store.shop_domain or os.environ.get("SHOPIFY_STORE_DOMAIN", "")

    def shopify_mode(self) -> str:
        """Effective mode for the Shopify integration: 'live' or 'mock'."""
        if self.mode != "live":
            return "mock"
        if self.shop_domain and os.environ.get("SHOPIFY_ACCESS_TOKEN"):
            return "live"
        return "mock"

    def cj_mode(self) -> str:
        """Effective mode for the CJ Dropshipping integration: 'live' or 'mock'."""
        if self.mode != "live":
            return "mock"
        if os.environ.get("CJ_EMAIL") and os.environ.get("CJ_API_KEY"):
            return "live"
        return "mock"


def find_root(start: Path | None = None) -> Path:
    """Locate the shopagent project dir (contains config.yaml).

    Honors SHOPAGENT_HOME, otherwise walks up from the current directory.
    """
    env = os.environ.get("SHOPAGENT_HOME")
    if env:
        return Path(env).resolve()
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "config.yaml").exists() and (candidate / "src" / "shopagent").is_dir():
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
    cfg = AppConfig(**data)
    cfg.root = root_path
    return cfg
