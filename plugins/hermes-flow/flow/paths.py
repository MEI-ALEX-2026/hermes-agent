from __future__ import annotations

import os
from pathlib import Path


def plugin_root() -> Path:
    override = os.getenv("HERMES_FLOW_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    return plugin_root() / "data"


def logs_dir() -> Path:
    return plugin_root() / "logs"


def db_path() -> Path:
    return data_dir() / "flow.db"


def heartbeat_path() -> Path:
    return data_dir() / "daemon.json"


def stop_flag_path() -> Path:
    return data_dir() / "daemon.stop"


def ensure_flow_dirs() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)
