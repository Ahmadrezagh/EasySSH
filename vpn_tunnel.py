"""System-wide VPN routing over SSH using sshuttle (no system SOCKS proxy)."""

from __future__ import annotations

import atexit
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from elevation import elevation_hint, run_elevated_command, run_elevated_script
from platform_util import find_elevated_python, is_linux, is_macos, is_windows, runtime_dir
from tunnel import TunnelConfig


def _sshuttle_package_dir() -> Path:
    spec = importlib.util.find_spec("sshuttle")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("sshuttle is not installed. Run: pip install sshuttle")
    return Path(next(iter(spec.submodule_search_locations)))


def _stage_sshuttle_runtime(runtime_path: Path) -> tuple[Path, str]:
    """Copy sshuttle into a temp dir so elevated processes can import it."""
    package_dir = _sshuttle_package_dir()
    site_packages = runtime_path / "site-packages"
    target = site_packages / "sshuttle"

    if site_packages.exists():
        shutil.rmtree(site_packages)
    site_packages.mkdir(parents=True, exist_ok=True)
    shutil.copytree(package_dir, target)

    python_bin = find_elevated_python()
    return site_packages, python_bin


def _windows_vpn_extra_available() -> bool:
    try:
        import pydivert  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class VPNPaths:
    askpass: Path
    launcher: Path
    pidfile: Path
    runtime_dir: Path


class SSHuttleTunnel:
    """Route all system traffic through SSH using sshuttle."""

    def __init__(
        self,
        on_status: Optional[Callable[[str], None]] = None,
        on_lost: Optional[Callable[[], None]] = None,
    ) -> None:
        self._paths: Optional[VPNPaths] = None
        self._watch_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._on_status = on_status
        self._on_lost = on_lost
        atexit.register(self.disconnect)

    @property
    def is_connected(self) -> bool:
        return self._is_running()

    @staticmethod
    def is_available() -> bool:
        try:
            _sshuttle_package_dir()
        except RuntimeError:
            return False
        if is_windows() and not _windows_vpn_extra_available():
            return False
        return True

    @staticmethod
    def availability_error() -> str:
        try:
            _sshuttle_package_dir()
        except RuntimeError:
            return "VPN mode needs sshuttle.\n\nRun: pip install sshuttle"
        if is_windows() and not _windows_vpn_extra_available():
            return (
                "VPN mode on Windows also needs pydivert.\n\n"
                "Run: pip install pydivert\n\n"
                "Or use SOCKS only mode and configure apps manually."
            )
        return "VPN mode is not available on this system."

    def _emit(self, message: str) -> None:
        if self._on_status:
            self._on_status(message)

    def connect(self, config: TunnelConfig) -> None:
        if not self.is_available():
            raise RuntimeError(self.availability_error())
        if self.is_connected:
            raise RuntimeError("VPN is already connected")

        self.disconnect()
        self._stop_event.clear()

        temp_dir = Path(os.environ.get("TEMP" if is_windows() else "TMPDIR", "/tmp"))
        if not temp_dir.exists():
            temp_dir = Path("/tmp") if not is_windows() else Path(os.environ.get("TEMP", "."))

        paths = VPNPaths(
            askpass=temp_dir / "ssh_proxy_askpass.sh",
            launcher=temp_dir / ("ssh_proxy_launch.bat" if is_windows() else "ssh_proxy_launch.sh"),
            pidfile=temp_dir / "ssh_proxy_sshuttle.pid",
            runtime_dir=runtime_dir(),
        )
        self._paths = paths

        site_packages, python_bin = _stage_sshuttle_runtime(paths.runtime_dir)

        if is_windows():
            paths.askpass = paths.askpass.with_suffix(".bat")
            escaped_password = config.password.replace("%", "%%").replace('"', '""')
            paths.askpass.write_text(
                f"@echo off\r\n"
                f'echo {escaped_password}\r\n',
                encoding="utf-8",
            )
        else:
            paths.askpass.write_text(
                "#!/bin/sh\n"
                f"printf '%s' {shlex.quote(config.password)}\n",
                encoding="utf-8",
            )
            paths.askpass.chmod(0o700)

        if paths.pidfile.exists():
            paths.pidfile.unlink()

        ssh_cmd = (
            f"ssh -4 -o StrictHostKeyChecking=accept-new -o BatchMode=no "
            f"-o ServerAliveInterval=15 -o ServerAliveCountMax=6 "
            f"-p {config.port}"
        )
        remote = f"{config.username}@{config.host}:{config.port}"

        sshuttle_args = " ".join(
            [
                "-D",
                f"--pidfile={shlex.quote(str(paths.pidfile))}",
                "--dns",
                f"-r {shlex.quote(remote)}",
                shlex.quote("0.0.0.0/0"),
                f"-e {shlex.quote(ssh_cmd)}",
            ]
        )

        if is_windows():
            launcher = "\r\n".join(
                [
                    "@echo off",
                    f"set SSH_ASKPASS={paths.askpass}",
                    "set SSH_ASKPASS_REQUIRE=force",
                    f"set PYTHONPATH={site_packages}",
                    (
                        f'"{python_bin}" -m sshuttle -D '
                        f"--pidfile={paths.pidfile} "
                        "--dns "
                        f"-r {remote} "
                        "0.0.0.0/0 "
                        f'-e "{ssh_cmd}"'
                    ),
                ]
            )
        else:
            display = os.environ.get("DISPLAY", ":0")
            launcher = "\n".join(
                [
                    "#!/bin/bash",
                    "set -e",
                    f"export SSH_ASKPASS={shlex.quote(str(paths.askpass))}",
                    "export SSH_ASKPASS_REQUIRE=force",
                    f"export DISPLAY={shlex.quote(display)}",
                    f"export PYTHONPATH={shlex.quote(str(site_packages))}",
                    f"exec {shlex.quote(python_bin)} -m sshuttle {sshuttle_args}",
                ]
            )

        paths.launcher.write_text(launcher, encoding="utf-8")
        if not is_windows():
            paths.launcher.chmod(0o700)

        self._emit(f"Requesting admin access to route system traffic... {elevation_hint()}")
        result = run_elevated_script(paths.launcher)
        if result.returncode != 0:
            self._cleanup_files()
            detail = (result.stderr or result.stdout or "").strip()
            if "canceled" in detail.lower() or "cancelled" in detail.lower():
                raise RuntimeError("Admin permission was canceled")
            if is_linux() and "password" in detail.lower():
                raise RuntimeError(
                    "Could not obtain root access. Install pkexec (polkit) or configure sudo."
                )
            raise RuntimeError(detail or "Failed to start VPN routing")

        deadline = time.time() + 25
        while time.time() < deadline:
            if self._is_running():
                break
            time.sleep(0.5)
        else:
            self.disconnect()
            raise RuntimeError("VPN did not start. Check SSH host, user, and password.")

        self._watch_thread = threading.Thread(target=self._watch, daemon=True)
        self._watch_thread.start()
        self._emit("VPN active · all system traffic routed through SSH")

    def disconnect(self) -> None:
        self._stop_event.set()
        paths = self._paths
        self._paths = None

        if paths and paths.pidfile.exists():
            pid = paths.pidfile.read_text(encoding="utf-8").strip()
            if pid.isdigit():
                if is_windows():
                    subprocess.run(["taskkill", "/F", "/PID", pid], check=False)
                else:
                    run_elevated_command(
                        f"kill {pid} 2>/dev/null; "
                        "pkill -f sshuttle.*ssh_proxy_sshuttle 2>/dev/null; "
                        "true"
                    )

        self._cleanup_files(paths)
        self._emit("Disconnected")

    def _watch(self) -> None:
        while not self._stop_event.is_set():
            if not self._is_running():
                paths = self._paths
                self._paths = None
                self._cleanup_files(paths)
                if not self._stop_event.is_set() and self._on_lost:
                    self._emit("VPN tunnel closed unexpectedly")
                    self._on_lost()
                return
            time.sleep(2)

    def _is_running(self) -> bool:
        paths = self._paths
        if not paths or not paths.pidfile.exists():
            return False
        pid = paths.pidfile.read_text(encoding="utf-8").strip()
        if not pid.isdigit():
            return False

        if is_windows():
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                check=False,
            )
            return pid in result.stdout

        result = subprocess.run(
            ["ps", "-p", pid],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    def _cleanup_files(self, paths: Optional[VPNPaths] = None) -> None:
        paths = paths or self._paths
        if not paths:
            return
        for path in (paths.askpass, paths.launcher, paths.pidfile):
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
        if paths.runtime_dir.exists():
            try:
                shutil.rmtree(paths.runtime_dir)
            except OSError:
                pass
