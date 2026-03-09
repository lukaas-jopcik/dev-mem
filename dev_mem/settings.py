"""
settings.py — Config loader with defaults for dev-mem.

Settings are stored at ~/.dev-mem/settings.json and fall back to
built-in defaults for any missing keys.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Canonical paths
# ---------------------------------------------------------------------------

DATA_DIR: Path = Path.home() / ".dev-mem"
DB_PATH: Path = DATA_DIR / "mem.db"
SETTINGS_PATH: Path = DATA_DIR / "settings.json"

# ---------------------------------------------------------------------------
# Default schema
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "timezone": "auto",
    "session_timeout_minutes": 30,
    "context_max_tokens": 4000,
    "web_port": 8888,
    "daily_summary_hour": 20,
    "prompt_min_score_alert": 40,
    "ignore_commands": [
        "ls", "cd", "pwd", "clear", "history",
        "exit", "ll", "la", "cat", "echo",
    ],
    "ignore_paths": [
        ".git", "node_modules", "__pycache__", ".env",
        ".DS_Store", "*.pyc", "dist", "build",
    ],
    "projects": [],
    "error_alert_threshold": 3,
    "retention_days": {
        "commands": 90,
        "file_events": 60,
        "claude_sessions": 90,
    },
    # Memory / observations subsystem
    "observations_enabled": True,
    "observations_min_output_chars": 100,
    "observations_obs_tools": ["Read", "Write", "Edit", "Bash", "MultiEdit"],
    "context_inject_max_observations": 10,
    "context_inject_max_chars": 8000,
    "session_summary_enabled": True,
    "mcp_server_db_path": None,
}


# ---------------------------------------------------------------------------
# Settings class
# ---------------------------------------------------------------------------

class Settings:
    """
    Persistent key-value settings backed by a JSON file.

    Falls back to DEFAULTS for any key not present in the file.
    """

    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self._path = path
        self._data: dict[str, Any] = {}
        self.load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """
        Load settings from disk.

        Creates the data directory and an empty settings file if they
        do not exist yet. Missing keys are silently filled from DEFAULTS.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)

        if self._path.exists():
            try:
                with self._path.open("r", encoding="utf-8") as fh:
                    on_disk: dict[str, Any] = json.load(fh)
            except (json.JSONDecodeError, OSError):
                on_disk = {}
        else:
            on_disk = {}

        # Deep-merge: top-level keys; nested dicts use defaults as base
        merged: dict[str, Any] = {}
        for key, default_value in DEFAULTS.items():
            disk_value = on_disk.get(key)
            if disk_value is None:
                if isinstance(default_value, dict):
                    merged[key] = dict(default_value)
                elif isinstance(default_value, list):
                    merged[key] = list(default_value)
                else:
                    merged[key] = default_value
            elif isinstance(default_value, dict) and isinstance(disk_value, dict):
                # Merge nested dict (e.g. retention_days) — disk wins per-key
                base = dict(default_value)
                base.update(disk_value)
                merged[key] = base
            else:
                merged[key] = disk_value

        # Preserve any extra user-defined keys not present in DEFAULTS
        for key, value in on_disk.items():
            if key not in merged:
                merged[key] = value

        self._data = merged

    def save(self) -> None:
        """Persist current in-memory settings to disk as formatted JSON."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Return the value for *key*.

        Resolution order: loaded settings -> DEFAULTS -> *default*.
        """
        if key in self._data:
            return self._data[key]
        return DEFAULTS.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        Update *key* in memory.

        Call :meth:`save` afterwards to persist the change to disk.
        """
        self._data[key] = value

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def data_dir(self) -> Path:
        """Resolved path to the data directory (~/.dev-mem/)."""
        return DATA_DIR

    @property
    def db_path(self) -> Path:
        """Resolved path to the SQLite database file."""
        return DB_PATH

    @property
    def active_project(self) -> str | None:
        return self._data.get("active_project")

    @property
    def projects(self) -> list:
        return self._data.get("projects", [])

    @property
    def context_dir(self) -> Path:
        return DATA_DIR / "context"

    @property
    def daily_dir(self) -> Path:
        return DATA_DIR / "daily"

    @property
    def archive_after_days(self) -> int:
        return int(self._data.get("archive_after_days", 90))

    def set_active_project(self, name: str) -> None:
        self._data["active_project"] = name
        self.save()

    def add_project(self, path: str, name: str | None = None, color: str = "#6366f1") -> dict:
        projects = self._data.get("projects", [])
        proj_name = name or Path(path).name
        entry = {"name": proj_name, "path": str(Path(path).expanduser()), "color": color}
        projects.append(entry)
        self._data["projects"] = projects
        self.save()
        return entry

    def as_dict(self) -> dict[str, Any]:
        """Return a shallow copy of the merged settings dict."""
        return dict(self._data)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Settings(path={self._path}, keys={list(self._data)})"
