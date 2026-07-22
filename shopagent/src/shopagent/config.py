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


class AmazonConfig(BaseModel):
    marketplace_id: str = "ATVPDKIKX0DER"  # amazon.com (US)
    endpoint: str = "https://sellingpartnerapi-na.amazon.com"
    carrier_default: str = "Other"
    carrier_name_default: str = "CJPacket"
    lead_time_days: int = 5
    default_quantity: int = 20  # FBM stock buffer shown to Amazon


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
    amazon: AmazonConfig = Field(default_factory=AmazonConfig)
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
        raw = self.store.shop_domain or os.environ.get("SHOPIFY_STORE_DOMAIN", "")
        return normalize_shop_domain(raw)

    def shopify_auth_method(self) -> str:
        """'token' (legacy shpat_), 'client_credentials' (Dev Dashboard apps,
        the only kind creatable since Jan 2026), or 'none'."""
        if os.environ.get("SHOPIFY_ACCESS_TOKEN"):
            return "token"
        if os.environ.get("SHOPIFY_CLIENT_ID") and os.environ.get("SHOPIFY_CLIENT_SECRET"):
            return "client_credentials"
        return "none"

    def shopify_mode(self) -> str:
        """Effective mode for the Shopify integration: 'live' or 'mock'."""
        if self.mode != "live":
            return "mock"
        if self.shop_domain and self.shopify_auth_method() != "none":
            return "live"
        return "mock"

    def cj_mode(self) -> str:
        """Effective mode for the CJ Dropshipping integration: 'live' or 'mock'."""
        if self.mode != "live":
            return "mock"
        if os.environ.get("CJ_EMAIL") and os.environ.get("CJ_API_KEY"):
            return "live"
        return "mock"

    def amazon_mode(self) -> str:
        """Effective mode for the Amazon SP-API integration: 'live' or 'mock'."""
        if self.mode != "live":
            return "mock"
        required = ("AMZ_CLIENT_ID", "AMZ_CLIENT_SECRET", "AMZ_REFRESH_TOKEN",
                    "AMZ_SELLER_ID")
        if all(os.environ.get(v) for v in required):
            return "live"
        return "mock"


def normalize_shop_domain(raw: str) -> str:
    """Clean common paste mistakes: scheme, path, trailing slash, whitespace.
    'https://x.myshopify.com/admin' -> 'x.myshopify.com'."""
    domain = raw.strip().removeprefix("https://").removeprefix("http://")
    return domain.split("/", 1)[0]


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
