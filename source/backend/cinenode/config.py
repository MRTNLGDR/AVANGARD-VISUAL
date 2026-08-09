from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class AppConfig:
    home: Path
    database: Path
    assets_dir: Path
    projects_dir: Path
    outputs_dir: Path
    uploads_dir: Path
    backups_dir: Path
    logs_dir: Path
    models_dir: Path
    engines_dir: Path
    temp_dir: Path
    frontend_dir: Path
    host: str
    port: int
    max_upload_bytes: int
    command_timeout_seconds: int
    local_access_token: str
    allow_shutdown_endpoint: bool
    allow_loopback_proxy: bool = False

    @classmethod
    def from_env(cls) -> "AppConfig":
        package_source = Path(__file__).resolve().parents[2]
        bundled_frontend = Path(__file__).resolve().parent / "frontend"
        source_frontend = package_source / "frontend"
        default_frontend = bundled_frontend if bundled_frontend.is_dir() else source_frontend
        default_home = Path.cwd() / "data"
        home = Path(os.getenv("CINENODE_HOME", str(default_home))).expanduser().resolve()
        frontend_dir = Path(
            os.getenv("CINENODE_FRONTEND_DIR", str(default_frontend))
        ).expanduser().resolve()
        token = os.getenv("CINENODE_LOCAL_TOKEN", "").strip()
        if not token:
            token_file = home / ".local-token"
            if token_file.exists():
                token = token_file.read_text(encoding="utf-8").strip()
            else:
                token = secrets.token_urlsafe(32)
                token_file.parent.mkdir(parents=True, exist_ok=True)
                token_file.write_text(token, encoding="utf-8")
                try:
                    token_file.chmod(0o600)
                except OSError:
                    pass
        return cls(
            home=home,
            database=Path(os.getenv("CINENODE_DB", str(home / "cinenode.sqlite3"))).resolve(),
            assets_dir=home / "assets",
            projects_dir=home / "projects",
            outputs_dir=home / "outputs",
            uploads_dir=home / "uploads",
            backups_dir=home / "backups",
            logs_dir=home / "logs",
            models_dir=Path(os.getenv("CINENODE_MODELS_DIR", str(home / "models"))).resolve(),
            engines_dir=Path(os.getenv("CINENODE_ENGINES_DIR", str(home / "engines"))).resolve(),
            temp_dir=home / "tmp",
            frontend_dir=frontend_dir,
            host=os.getenv("CINENODE_HOST", "127.0.0.1"),
            port=int(os.getenv("CINENODE_PORT", "8787")),
            max_upload_bytes=int(os.getenv("CINENODE_MAX_UPLOAD_BYTES", str(8 * 1024**3))),
            command_timeout_seconds=int(os.getenv("CINENODE_COMMAND_TIMEOUT_SECONDS", "14400")),
            local_access_token=token,
            allow_shutdown_endpoint=_env_bool("CINENODE_ALLOW_SHUTDOWN", True),
            allow_loopback_proxy=_env_bool("CINENODE_ALLOW_LOOPBACK_PROXY", False),
        )

    def ensure_directories(self) -> None:
        for directory in (
            self.home,
            self.assets_dir,
            self.projects_dir,
            self.outputs_dir,
            self.uploads_dir,
            self.backups_dir,
            self.logs_dir,
            self.models_dir,
            self.engines_dir,
            self.temp_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
