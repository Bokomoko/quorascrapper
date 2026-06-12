"""Centralized configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import dotenv_values, load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    dotenv_values = None  # type: ignore
    pass


def load_project_env() -> None:
    """Load env from global config, then project files in cwd (project wins)."""
    if dotenv_values is None:
        return
    from pathlib import Path

    from quorascrapper.ops.config_cmd import config_paths

    def merge_file(path: Path, *, override: bool) -> None:
        if not path.is_file():
            return
        for key, value in dotenv_values(path).items():
            if value is None:
                continue
            if override or key not in os.environ:
                os.environ[key] = value

    for path in config_paths():
        merge_file(path, override=False)

    for name in (".env", ".env.container", ".env.scraper"):
        merge_file(Path(name), override=True)

_PLACEHOLDER_MARKERS = ("username:password", "your-connection", "secure_password")


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Settings:
    kafka_bootstrap: str = field(
        default_factory=lambda: os.environ.get("KAFKA_BOOTSTRAP", "")
    )
    kafka_topic: str = field(
        default_factory=lambda: os.environ.get("KAFKA_TOPIC", "quora-answers")
    )
    kafka_group_id: str = field(
        default_factory=lambda: os.environ.get("KAFKA_GROUP_ID", "quora-consumer-group")
    )
    kafka_healthcheck_topic: str = field(
        default_factory=lambda: os.environ.get("KAFKA_HEALTHCHECK_TOPIC", "healthcheck")
    )
    kafka_healthcheck_enabled: bool = field(
        default_factory=lambda: _truthy(os.environ.get("KAFKA_HEALTHCHECK"), True)
    )

    mongodb_uri: str = field(default_factory=lambda: os.environ.get("MONGODB_URI", ""))
    mongodb_database: str = field(
        default_factory=lambda: os.environ.get("MONGODB_DATABASE", "quora_data")
    )
    mongodb_collection: str = field(
        default_factory=lambda: os.environ.get("MONGODB_COLLECTION", "answers")
    )

    profile_url: str = field(default_factory=lambda: os.environ.get("PROFILE_URL", ""))
    max_results: int = field(
        default_factory=lambda: int(os.environ.get("MAX_RESULTS", "16000"))
    )
    scroll_pause: float = field(
        default_factory=lambda: float(os.environ.get("SCROLL_PAUSE", "1.5"))
    )
    chrome_binary: str = field(
        default_factory=lambda: os.environ.get("CHROME_BINARY", "")
    )
    sender: str = field(default_factory=lambda: os.environ.get("SENDER", "stdout"))
    dry_run: bool = field(
        default_factory=lambda: _truthy(os.environ.get("DRY_RUN"), False)
    )
    debug_selectors: bool = field(
        default_factory=lambda: _truthy(os.environ.get("DEBUG_SELECTORS"), False)
    )
    use_firefox: bool = field(
        default_factory=lambda: _truthy(os.environ.get("USE_FIREFOX"), False)
    )

    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))

    @classmethod
    def from_env(cls) -> Settings:
        return cls()

    def validate_subscriber(self) -> list[str]:
        errors: list[str] = []
        if not self.kafka_bootstrap:
            errors.append("KAFKA_BOOTSTRAP is required")
        if not self.mongodb_uri:
            errors.append("MONGODB_URI is required")
        elif any(m in self.mongodb_uri for m in _PLACEHOLDER_MARKERS):
            errors.append("MONGODB_URI appears to be a placeholder")
        return errors

    def validate_scraper(self) -> list[str]:
        errors: list[str] = []
        if self.sender == "kafka" and not self.kafka_bootstrap:
            errors.append("KAFKA_BOOTSTRAP is required when SENDER=kafka")
        return errors
