"""Cross-platform helpers."""

from __future__ import annotations

import platform
import shutil
import socket
import sys
import tempfile
from pathlib import Path


def bundle_path(*parts: str) -> Path:
    """Resolve bundled asset paths for dev and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    else:
        base = Path(__file__).resolve().parent
    return base.joinpath(*parts)


def is_macos() -> bool:
    return platform.system() == "Darwin"


def is_linux() -> bool:
    return platform.system() == "Linux"


def is_windows() -> bool:
    return platform.system() == "Windows"


def runtime_dir() -> Path:
    return Path(tempfile.gettempdir()) / "ssh_proxy_runtime"


def platform_label() -> str:
    system = platform.system()
    if system == "Darwin":
        return f"macOS {platform.mac_ver()[0]}"
    if system == "Windows":
        return f"Windows {platform.release()}"
    return f"{system} {platform.release()}"


def is_port_listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def kill_process_on_port(port: int) -> None:
    if is_windows():
        _kill_process_on_port_windows(port)
    elif is_macos():
        _kill_process_on_port_unix(port, use_lsof=True)
    else:
        _kill_process_on_port_unix(port, use_lsof=shutil.which("lsof") is not None)


def _kill_process_on_port_windows(port: int) -> None:
    import subprocess

    result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True,
        text=True,
        check=False,
    )
    suffix = f":{port}"
    for line in result.stdout.splitlines():
        if "LISTENING" not in line or suffix not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        pid = parts[-1]
        if pid.isdigit() and pid != "0":
            subprocess.run(["taskkill", "/F", "/PID", pid], check=False)


def _kill_process_on_port_unix(port: int, use_lsof: bool) -> None:
    import subprocess

    if use_lsof:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True,
            text=True,
            check=False,
        )
        for pid in result.stdout.strip().split():
            if pid.isdigit():
                subprocess.run(["kill", "-9", pid], check=False)
        return

    if shutil.which("fuser"):
        subprocess.run(["fuser", "-k", f"{port}/tcp"], check=False)


def find_elevated_python() -> str:
    """Pick a system Python interpreter for elevated VPN launches."""
    if is_macos():
        candidates = (
            "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
            "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
            "/usr/local/bin/python3",
            "/opt/homebrew/bin/python3",
            "/usr/bin/python3",
        )
    elif is_windows():
        candidates = (
            shutil.which("python") or "",
            shutil.which("python3") or "",
        )
    else:
        candidates = (
            "/usr/bin/python3",
            "/usr/local/bin/python3",
            shutil.which("python3") or "",
        )

    seen: set[str] = set()
    home = str(Path.home())
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        path = Path(candidate)
        if not path.is_file():
            continue
        resolved = str(path.resolve())
        if home in resolved and ".venv" in resolved:
            continue
        return resolved

    raise RuntimeError("No system Python found for VPN mode")


def find_vpn_python() -> str:
    """Python interpreter for the elevated sshuttle launcher."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        if is_macos():
            framework = exe.parent.parent / "Frameworks" / "Python.framework" / "Versions"
            for relative in ("Current/bin/python3", "3.13/bin/python3"):
                candidate = framework / relative
                if candidate.is_file():
                    return str(candidate.resolve())
        elif is_windows():
            internal = exe.parent / "_internal" / "python3.dll"
            if internal.exists():
                return str(exe.resolve())
        else:
            internal_python = exe.parent / "_internal" / "python3"
            if internal_python.is_file():
                return str(internal_python.resolve())

    return find_elevated_python()


def ssh_command_name() -> str:
    if is_windows():
        return "ssh.exe" if shutil.which("ssh.exe") else "ssh"
    return "ssh"
