"""Persist SSH connection details between sessions."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from platform_util import is_windows

VALID_MODES = {"vpn", "socks", "system"}


@dataclass
class AppSettings:
    host: str = ""
    port: str = "22"
    username: str = ""
    password: str = ""
    mode: str = "vpn"
    local_port: str = "1080"
    dns: str = "8.8.8.8"


def config_dir() -> Path:
    if is_windows():
        base = Path(os.environ.get("APPDATA", str(Path.home())))
        return base / "EasySSH"
    return Path.home() / ".config" / "easyssh"


def config_path() -> Path:
    return config_dir() / "settings.json"


def load_settings() -> AppSettings:
    path = config_path()
    if not path.exists():
        return AppSettings()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()

    mode = str(data.get("mode", "vpn"))
    if mode not in VALID_MODES:
        mode = "vpn"

    return AppSettings(
        host=str(data.get("host", "")).strip(),
        port=str(data.get("port", "22")).strip() or "22",
        username=str(data.get("username", "")).strip(),
        password=str(data.get("password", "")),
        mode=mode,
        local_port=str(data.get("local_port", "1080")).strip() or "1080",
        dns=str(data.get("dns", "8.8.8.8")).strip() or "8.8.8.8",
    )


def save_settings(settings: AppSettings) -> None:
    if not settings.host or not settings.username:
        return

    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = config_path()
    path.write_text(
        json.dumps(asdict(settings), indent=2),
        encoding="utf-8",
    )

    if not is_windows():
        try:
            path.chmod(0o600)
        except OSError:
            pass
