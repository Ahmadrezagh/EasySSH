"""SSH dynamic SOCKS5 tunnel using the system OpenSSH client."""

from __future__ import annotations

import atexit
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, Union

import pexpect

from platform_util import is_port_listening, is_windows, kill_process_on_port, ssh_command_name


@dataclass
class TunnelConfig:
    host: str
    port: int
    username: str
    password: str
    local_port: int = 1080


SpawnType = Union[pexpect.spawn, "pexpect.popen_spawn.PopenSpawn"]


class SSHTunnel:
    """Manage an SSH -D SOCKS5 tunnel."""

    def __init__(
        self,
        on_status: Optional[Callable[[str], None]] = None,
        on_lost: Optional[Callable[[], None]] = None,
    ) -> None:
        self._process: Optional[SpawnType] = None
        self._thread: Optional[threading.Thread] = None
        self._config: Optional[TunnelConfig] = None
        self._on_status = on_status
        self._on_lost = on_lost
        self._stop_event = threading.Event()
        atexit.register(self.disconnect)

    @property
    def is_connected(self) -> bool:
        return self._process is not None and self._process.isalive()

    @property
    def local_port(self) -> Optional[int]:
        return self._config.local_port if self._config else None

    def _emit(self, message: str) -> None:
        if self._on_status:
            self._on_status(message)

    def _spawn_ssh(self, cmd: str) -> SpawnType:
        if is_windows():
            from pexpect import popen_spawn

            return popen_spawn.PopenSpawn(cmd, timeout=30, encoding="utf-8")
        return pexpect.spawn(cmd, timeout=30, encoding="utf-8")

    def connect(self, config: TunnelConfig) -> None:
        if self.is_connected:
            raise RuntimeError("Tunnel is already connected")

        kill_process_on_port(config.local_port)
        time.sleep(0.3)

        self._config = config
        self._stop_event.clear()

        ssh = ssh_command_name()
        cmd = (
            f"{ssh} -N -T -4 -C -D 127.0.0.1:{config.local_port} "
            f"-p {config.port} "
            f"-o StrictHostKeyChecking=accept-new "
            f"-o ServerAliveInterval=15 "
            f"-o ServerAliveCountMax=6 "
            f"-o TCPKeepAlive=yes "
            f"-o Compression=yes "
            f"-o ExitOnForwardFailure=yes "
            f"-o AddressFamily=inet "
            f"-o BatchMode=no "
            f"{config.username}@{config.host}"
        )

        self._emit("Connecting to SSH server...")
        self._process = self._spawn_ssh(cmd)
        self._process.logfile_read = None

        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

        if not self._wait_for_connection(timeout=30):
            output = ""
            if self._process:
                output = (self._process.before or "") + str(self._process.after or "")
            self.disconnect()
            raise RuntimeError(self._format_ssh_error(output) or "Failed to establish SSH tunnel")

        if not self._process.isalive():
            self.disconnect()
            raise RuntimeError("SSH process exited right after connecting")

        self._emit(f"SOCKS5 proxy listening on 127.0.0.1:{config.local_port}")

    def _wait_for_connection(self, timeout: float) -> bool:
        if not self._process or not self._config:
            return False

        deadline = time.time() + timeout

        while time.time() < deadline:
            if not self._process.isalive():
                output = (self._process.before or "") + str(self._process.after or "")
                raise RuntimeError(self._format_ssh_error(output))

            if is_port_listening(self._config.local_port):
                time.sleep(0.5)
                if self._process.isalive() and is_port_listening(self._config.local_port):
                    return True

            try:
                index = self._process.expect(
                    [
                        r"[Pp]assword:",
                        r"Are you sure you want to continue connecting",
                        pexpect.TIMEOUT,
                    ],
                    timeout=1,
                )
            except pexpect.EOF:
                return (
                    self._process.isalive()
                    and is_port_listening(self._config.local_port)
                )

            if index == 0:
                self._process.sendline(self._config.password)
            elif index == 1:
                self._process.sendline("yes")

        return self._process.isalive() and is_port_listening(self._config.local_port)

    def _watch(self) -> None:
        if not self._process:
            return

        try:
            self._process.wait()
        except Exception:
            pass
        finally:
            lost = not self._stop_event.is_set()
            self._process = None
            self._config = None
            if lost:
                self._emit("SSH tunnel closed unexpectedly")
                if self._on_lost:
                    self._on_lost()

    def disconnect(self) -> None:
        self._stop_event.set()
        process = self._process
        local_port = self._config.local_port if self._config else None
        self._process = None
        self._config = None

        if process and process.isalive():
            try:
                if is_windows():
                    process.kill(signal.SIGTERM)
                else:
                    process.send_signal(signal.SIGTERM)
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill(signal.SIGKILL)
                except Exception:
                    pass

        if local_port:
            kill_process_on_port(local_port)
        self._emit("Disconnected")

    @staticmethod
    def _format_ssh_error(output: str) -> str:
        text = (output or "").strip()
        if not text:
            return "SSH connection failed"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in reversed(lines):
            lowered = line.lower()
            if "permission denied" in lowered:
                return "Authentication failed: invalid username or password"
            if "connection refused" in lowered:
                return "Connection refused: check host and port"
            if "address already in use" in lowered:
                return "Local port is already in use. Disconnect and try again."
            if "could not resolve hostname" in lowered:
                return "Could not resolve hostname"
            if "no route to host" in lowered:
                return "No route to host"
            if "not recognized" in lowered and "ssh" in lowered:
                return "OpenSSH client not found. Install OpenSSH and ensure ssh is in PATH."
        return lines[-1]
