"""Run commands with administrator / root privileges."""

from __future__ import annotations

import subprocess
from pathlib import Path

from platform_util import is_linux, is_macos, is_windows


def _applescript_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def run_elevated_script(script_path: Path) -> subprocess.CompletedProcess[str]:
    if is_macos():
        return _run_macos(script_path)
    if is_linux():
        return _run_linux(script_path)
    if is_windows():
        return _run_windows(script_path)
    raise RuntimeError("Elevated execution is not supported on this platform")


def run_elevated_command(command: str) -> subprocess.CompletedProcess[str]:
    if is_macos():
        escaped = _applescript_string(command)
        return subprocess.run(
            [
                "osascript",
                "-e",
                f'do shell script "{escaped}" with administrator privileges',
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    if is_linux():
        if _has_command("pkexec"):
            return subprocess.run(
                ["pkexec", "bash", "-lc", command],
                capture_output=True,
                text=True,
                check=False,
            )
        return subprocess.run(
            ["sudo", "-n", "bash", "-lc", command],
            capture_output=True,
            text=True,
            check=False,
        )
    if is_windows():
        return _run_windows_bat(command)
    raise RuntimeError("Elevated execution is not supported on this platform")


def elevation_hint() -> str:
    if is_macos():
        return "macOS will ask for your admin password."
    if is_linux():
        return "Linux will ask for your administrator password (polkit/sudo)."
    if is_windows():
        return "Windows will ask for UAC approval."
    return "Administrator privileges are required."


def _run_macos(script_path: Path) -> subprocess.CompletedProcess[str]:
    escaped = _applescript_string(str(script_path))
    return subprocess.run(
        [
            "osascript",
            "-e",
            f'do shell script "{escaped}" with administrator privileges',
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _run_linux(script_path: Path) -> subprocess.CompletedProcess[str]:
    if _has_command("pkexec"):
        return subprocess.run(
            ["pkexec", "bash", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )

    # passwordless sudo or terminal prompt
    result = subprocess.run(
        ["sudo", "-n", "bash", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return result

    return subprocess.run(
        ["sudo", "bash", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )


def _run_windows(script_path: Path) -> subprocess.CompletedProcess[str]:
    import ctypes

    if script_path.suffix.lower() != ".bat":
        bat_path = script_path.with_suffix(".bat")
        bat_path.write_text(f'@"{script_path}" %*\r\n', encoding="utf-8")
        script_path = bat_path

    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        "cmd.exe",
        f'/c "{script_path}"',
        None,
        0,
    )
    if result <= 32:
        detail = {
            0: "System out of memory or resources",
            2: "File not found",
            5: "Access denied (UAC canceled)",
        }.get(result, f"ShellExecute failed ({result})")
        return subprocess.CompletedProcess(
            args=["cmd.exe", "/c", str(script_path)],
            returncode=1,
            stdout="",
            stderr=detail,
        )
    return subprocess.CompletedProcess(
        args=["cmd.exe", "/c", str(script_path)],
        returncode=0,
        stdout="",
        stderr="",
    )


def _run_windows_bat(command: str) -> subprocess.CompletedProcess[str]:
    import ctypes

    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        "cmd.exe",
        f'/c {command}',
        None,
        0,
    )
    if result <= 32:
        return subprocess.CompletedProcess(
            args=["cmd.exe", "/c", command],
            returncode=1,
            stdout="",
            stderr="Access denied (UAC canceled)",
        )
    return subprocess.CompletedProcess(
        args=["cmd.exe", "/c", command],
        returncode=0,
        stdout="",
        stderr="",
    )


def _has_command(name: str) -> bool:
    from shutil import which

    return which(name) is not None
