"""Central configuration.

All tunables live here so nothing important is implicit in code (spec sections 16, 60).
Values are overridable via environment variables (prefix ``ARCHON_``) or a ``.env`` file.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RepositoryLimits(BaseSettings):
    """Explicit initial repository limits (spec section 16).

    A ``hard`` breach means *reject*; a ``soft`` breach means *degrade and record a warning*.
    """

    model_config = SettingsConfigDict(env_prefix="ARCHON_LIMIT_")

    max_repo_size_bytes: int = 500 * 1024 * 1024
    max_file_size_bytes: int = 2 * 1024 * 1024
    max_file_count: int = 20_000
    max_git_history_commits: int = 5_000
    max_analysis_duration_seconds: int = 30 * 60
    max_generated_tests: int = 200
    max_patch_candidates: int = 5
    max_sandbox_runtime_seconds: int = 300
    clone_depth: int = 0  # 0 == full history (bounded later by max_git_history_commits)


class SandboxSettings(BaseSettings):
    """Docker sandbox tunables (spec sections 12, 36)."""

    model_config = SettingsConfigDict(env_prefix="ARCHON_SANDBOX_")

    image: str = "archon-sandbox:latest"
    cpu_limit: float = 1.0
    memory_mb: int = 512
    pids_limit: int = 128
    docker_host: str | None = None  # maps to DOCKER_HOST if set; None = default context


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARCHON_",
        env_file=os.environ.get("ARCHON_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Runtime ---
    environment: str = "local"
    log_level: str = "INFO"
    log_json: bool = False

    # --- Database ---
    database_url: str = "sqlite:///./archon.db"

    # --- Filesystem / artifacts (spec section 11) ---
    data_root: Path = Field(default_factory=lambda: Path("./_archon_data").resolve())
    workspace_root: Path | None = None  # defaults to data_root / "workspaces"
    artifact_root: Path | None = None  # defaults to data_root / "artifacts"
    workspace_quota_bytes: int = 5 * 1024 * 1024 * 1024

    # --- Providers ---
    github_api_url: str = "https://api.github.com"
    github_token: str | None = None  # read from env only; never logged, never sent to sandbox
    http_timeout_seconds: float = 20.0
    http_max_retries: int = 3

    # --- Jobs / concurrency (spec section 15) ---
    worker_poll_interval_seconds: float = 1.0
    job_heartbeat_timeout_seconds: int = 120
    max_concurrent_runs: int = 4

    # --- AI (spec sections 13-14, 18) ---
    ai_provider: str = "mock"          # "mock" | "claude" (claude is a stub until wired)
    ai_max_context_chars: int = 12_000
    ai_max_components_per_run: int = 40  # archaeology: top-K by churn * complexity

    limits: RepositoryLimits = Field(default_factory=RepositoryLimits)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)

    @property
    def resolved_workspace_root(self) -> Path:
        return (self.workspace_root or (self.data_root / "workspaces")).resolve()

    @property
    def resolved_artifact_root(self) -> Path:
        return (self.artifact_root or (self.data_root / "artifacts")).resolve()

    def ensure_dirs(self) -> None:
        self.resolved_workspace_root.mkdir(parents=True, exist_ok=True)
        self.resolved_artifact_root.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Test hook - drop the cached Settings so env changes take effect."""
    get_settings.cache_clear()
