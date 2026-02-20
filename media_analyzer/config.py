"""Load, save, and validate configuration from config.yaml."""

import os
import secrets
from pathlib import Path

import yaml

DEFAULT_CONFIG = {
    "scan_dirs": [],
    "server": {
        "host": "0.0.0.0",
        "port": 8080,
    },
    "db_path": "data/media_analyzer.db",
    "secret_token": None,
    "file_extensions": {
        "video": [".mp4", ".mkv", ".avi", ".mov", ".m4v"],
        "audio": [".mp3", ".aac", ".flac", ".wav", ".ogg", ".wma", ".m4a", ".opus"],
    },
    "hashing": {
        "workers": min(4, os.cpu_count() or 1),
        "phash": False,
    },
}


def _find_config_path() -> Path:
    """Find the config.yaml file, checking env var then default locations."""
    if env_path := os.environ.get("MEDIA_ANALYZER_CONFIG"):
        return Path(env_path)
    # Default: config.yaml next to the package's parent directory
    return Path(__file__).resolve().parent.parent / "config.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: Path | None = None) -> dict:
    """Load config from YAML file, merged with defaults."""
    if config_path is None:
        config_path = _find_config_path()

    config = DEFAULT_CONFIG.copy()
    if config_path.exists():
        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(DEFAULT_CONFIG, user_config)

    # Resolve db_path relative to config file location
    db_path = Path(config["db_path"])
    if not db_path.is_absolute():
        db_path = config_path.parent / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    config["db_path"] = str(db_path)

    # Normalize scan_dirs: null, missing, or bare string → list
    scan_dirs = config.get("scan_dirs")
    if not isinstance(scan_dirs, list):
        config["scan_dirs"] = [scan_dirs] if isinstance(scan_dirs, str) else []

    return config


def save_config(config: dict, config_path: Path | None = None) -> None:
    """Save config back to YAML file."""
    if config_path is None:
        config_path = _find_config_path()

    # Make db_path relative to config dir if it's under the same tree
    save_data = config.copy()
    db_path = Path(save_data["db_path"])
    try:
        save_data["db_path"] = str(db_path.relative_to(config_path.parent))
    except ValueError:
        pass  # Keep absolute path

    with open(config_path, "w") as f:
        yaml.dump(save_data, f, default_flow_style=False, sort_keys=False)


def generate_secret_token() -> str:
    """Generate a cryptographically secure token."""
    return secrets.token_urlsafe(32)


def validate_config(config: dict) -> list[str]:
    """Validate configuration, returning a list of warnings."""
    warnings = []
    scan_dirs = config.get("scan_dirs") or []
    if isinstance(scan_dirs, str):
        scan_dirs = [scan_dirs]
    for d in scan_dirs:
        p = Path(d)
        if not p.is_absolute():
            warnings.append(f"Scan directory must be absolute: {d}")
        elif not p.exists():
            warnings.append(f"Scan directory does not exist: {d}")
    if config["server"]["host"] == "0.0.0.0" and not config.get("secret_token"):
        warnings.append(
            "Server bound to 0.0.0.0 without secret_token — anyone on the network can access"
        )
    return warnings
