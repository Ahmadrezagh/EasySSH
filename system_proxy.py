"""System-wide SOCKS proxy configuration for macOS, Linux, and Windows."""

from __future__ import annotations

import re
import socket
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from platform_util import is_linux, is_macos, is_windows


@dataclass
class ProxyState:
    enabled: bool
    host: str
    port: str


@dataclass
class ServiceState:
    proxy: ProxyState
    dns_servers: List[str] = field(default_factory=list)
    bypass_domains: List[str] = field(default_factory=list)
    ipv6_mode: str = "automatic"


DEFAULT_BYPASS = [
    "localhost",
    "127.0.0.1",
    "*.local",
    "169.254/16",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
]


def secondary_dns(primary: str) -> str:
    pairs = {
        "8.8.8.8": "8.8.4.4",
        "1.1.1.1": "1.0.0.1",
        "9.9.9.9": "149.112.112.112",
    }
    return pairs.get(primary, primary)


def _resolve_host(host: str) -> List[str]:
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
        return [host]
    try:
        results = socket.getaddrinfo(host, None, socket.AF_INET)
        return list({item[4][0] for item in results})
    except socket.gaierror:
        return []


def _build_bypass_list(extra_hosts: List[str]) -> List[str]:
    bypass = list(DEFAULT_BYPASS)
    for host in extra_hosts:
        host = host.strip()
        if not host:
            continue
        if host not in bypass:
            bypass.append(host)
        for ip in _resolve_host(host):
            if ip not in bypass:
                bypass.append(ip)
    return bypass


def _format_gsettings_array(items: List[str]) -> str:
    return "[" + ", ".join(f"'{item}'" for item in items) + "]"


class SystemProxyBackend(ABC):
    @property
    @abstractmethod
    def is_active(self) -> bool: ...

    @abstractmethod
    def prepare(
        self,
        dns_servers: Optional[List[str]] = None,
        bypass_hosts: Optional[List[str]] = None,
        disable_ipv6: bool = True,
    ) -> None: ...

    @abstractmethod
    def enable_socks(
        self,
        host: str = "127.0.0.1",
        port: int = 1080,
        bypass_hosts: Optional[List[str]] = None,
    ) -> None: ...

    @abstractmethod
    def disable(self) -> None: ...


class MacSystemProxy(SystemProxyBackend):
    def __init__(self) -> None:
        self._saved: dict[str, ServiceState] = {}

    @property
    def is_active(self) -> bool:
        return bool(self._saved)

    def prepare(
        self,
        dns_servers: Optional[List[str]] = None,
        bypass_hosts: Optional[List[str]] = None,
        disable_ipv6: bool = True,
    ) -> None:
        services = self._get_network_services()
        if not services:
            raise RuntimeError("No network services found")

        dns = dns_servers or ["8.8.8.8", "8.8.4.4"]
        bypass = _build_bypass_list(bypass_hosts or [])

        for service in services:
            self._remember_service(service)
            subprocess.run(
                ["networksetup", "-setproxybypassdomains", service, *bypass],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["networksetup", "-setdnsservers", service, *dns],
                check=True,
                capture_output=True,
                text=True,
            )
            if disable_ipv6:
                subprocess.run(
                    ["networksetup", "-setv6off", service],
                    check=False,
                    capture_output=True,
                    text=True,
                )

        self._flush_dns_cache()
        time.sleep(0.5)

    def enable_socks(
        self,
        host: str = "127.0.0.1",
        port: int = 1080,
        bypass_hosts: Optional[List[str]] = None,
    ) -> None:
        services = self._get_network_services()
        if not services:
            raise RuntimeError("No network services found")

        bypass = _build_bypass_list(bypass_hosts or [])
        for service in services:
            self._remember_service(service)
            subprocess.run(
                ["networksetup", "-setproxybypassdomains", service, *bypass],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["networksetup", "-setsocksfirewallproxy", service, host, str(port)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["networksetup", "-setsocksfirewallproxystate", service, "on"],
                check=True,
                capture_output=True,
                text=True,
            )

    def disable(self) -> None:
        for service, state in self._saved.items():
            proxy = state.proxy
            if proxy.enabled and proxy.host and proxy.port:
                subprocess.run(
                    [
                        "networksetup",
                        "-setsocksfirewallproxy",
                        service,
                        proxy.host,
                        proxy.port,
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    ["networksetup", "-setsocksfirewallproxystate", service, "on"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            else:
                subprocess.run(
                    ["networksetup", "-setsocksfirewallproxystate", service, "off"],
                    check=False,
                    capture_output=True,
                    text=True,
                )

            if state.bypass_domains:
                subprocess.run(
                    ["networksetup", "-setproxybypassdomains", service, *state.bypass_domains],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            else:
                subprocess.run(
                    ["networksetup", "-setproxybypassdomains", service, "Empty"],
                    check=False,
                    capture_output=True,
                    text=True,
                )

            if state.dns_servers:
                subprocess.run(
                    ["networksetup", "-setdnsservers", service, *state.dns_servers],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            else:
                subprocess.run(
                    ["networksetup", "-setdnsservers", service, "Empty"],
                    check=False,
                    capture_output=True,
                    text=True,
                )

            if state.ipv6_mode == "off":
                subprocess.run(
                    ["networksetup", "-setv6off", service],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            else:
                subprocess.run(
                    ["networksetup", "-setv6automatic", service],
                    check=False,
                    capture_output=True,
                    text=True,
                )

        self._saved.clear()
        self._flush_dns_cache()

    def _remember_service(self, service: str) -> None:
        if service not in self._saved:
            self._saved[service] = ServiceState(
                proxy=self._get_proxy_state(service),
                dns_servers=self._get_dns_servers(service),
                bypass_domains=self._get_bypass_domains(service),
                ipv6_mode=self._get_ipv6_mode(service),
            )

    def _get_proxy_state(self, service: str) -> ProxyState:
        result = subprocess.run(
            ["networksetup", "-getsocksfirewallproxy", service],
            check=True,
            capture_output=True,
            text=True,
        )
        enabled = False
        host = ""
        port = ""
        for line in result.stdout.splitlines():
            if line.startswith("Enabled:"):
                enabled = line.split(":", 1)[1].strip().lower() == "yes"
            elif line.startswith("Server:"):
                host = line.split(":", 1)[1].strip()
            elif line.startswith("Port:"):
                port = line.split(":", 1)[1].strip()
        return ProxyState(enabled=enabled, host=host, port=port)

    def _get_dns_servers(self, service: str) -> List[str]:
        result = subprocess.run(
            ["networksetup", "-getdnsservers", service],
            check=True,
            capture_output=True,
            text=True,
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lines or lines[0].lower().startswith("there aren't any"):
            return []
        return lines

    def _get_bypass_domains(self, service: str) -> List[str]:
        result = subprocess.run(
            ["networksetup", "-getproxybypassdomains", service],
            check=True,
            capture_output=True,
            text=True,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def _get_ipv6_mode(self, service: str) -> str:
        result = subprocess.run(
            ["networksetup", "-getinfo", service],
            check=True,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("IPv6:"):
                value = line.split(":", 1)[1].strip().lower()
                if value == "off":
                    return "off"
        return "automatic"

    def _get_network_services(self) -> List[str]:
        result = subprocess.run(
            ["networksetup", "-listallnetworkservices"],
            check=True,
            capture_output=True,
            text=True,
        )
        services = []
        for line in result.stdout.splitlines()[1:]:
            line = line.strip()
            if line and not line.startswith("*"):
                services.append(line)
        return services

    @staticmethod
    def _flush_dns_cache() -> None:
        subprocess.run(["dscacheutil", "-flushcache"], check=False)
        subprocess.run(["killall", "-HUP", "mDNSResponder"], check=False)


class LinuxSystemProxy(SystemProxyBackend):
    """GNOME gsettings-based system proxy (other desktops may need manual setup)."""

    def __init__(self) -> None:
        self._saved: dict[str, str] = {}
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    def _gsettings(self, *args: str) -> str:
        result = subprocess.run(
            ["gsettings", *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def _require_gsettings(self) -> None:
        try:
            self._gsettings("get", "org.gnome.system.proxy", "mode")
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise RuntimeError(
                "System SOCKS on Linux needs GNOME gsettings. "
                "Use VPN mode or SOCKS only mode on this desktop."
            ) from exc

    def prepare(
        self,
        dns_servers: Optional[List[str]] = None,
        bypass_hosts: Optional[List[str]] = None,
        disable_ipv6: bool = True,
    ) -> None:
        self._require_gsettings()
        bypass = _build_bypass_list(bypass_hosts or [])
        if "mode" not in self._saved:
            self._saved["mode"] = self._gsettings("get", "org.gnome.system.proxy", "mode")
            self._saved["ignore-hosts"] = self._gsettings(
                "get", "org.gnome.system.proxy", "ignore-hosts"
            )
        self._gsettings(
            "set",
            "org.gnome.system.proxy",
            "ignore-hosts",
            _format_gsettings_array(bypass),
        )

    def enable_socks(
        self,
        host: str = "127.0.0.1",
        port: int = 1080,
        bypass_hosts: Optional[List[str]] = None,
    ) -> None:
        self._require_gsettings()
        bypass = _build_bypass_list(bypass_hosts or [])
        if "mode" not in self._saved:
            self._saved["mode"] = self._gsettings("get", "org.gnome.system.proxy", "mode")
            self._saved["ignore-hosts"] = self._gsettings(
                "get", "org.gnome.system.proxy", "ignore-hosts"
            )
            self._saved["socks-host"] = self._gsettings(
                "get", "org.gnome.system.proxy.socks", "host"
            )
            self._saved["socks-port"] = self._gsettings(
                "get", "org.gnome.system.proxy.socks", "port"
            )

        self._gsettings(
            "set",
            "org.gnome.system.proxy",
            "ignore-hosts",
            _format_gsettings_array(bypass),
        )
        self._gsettings("set", "org.gnome.system.proxy.socks", "host", host)
        self._gsettings("set", "org.gnome.system.proxy.socks", "port", str(port))
        self._gsettings("set", "org.gnome.system.proxy", "mode", "manual")
        self._active = True

    def disable(self) -> None:
        if not self._saved:
            self._active = False
            return
        try:
            if "mode" in self._saved:
                self._gsettings("set", "org.gnome.system.proxy", "mode", self._saved["mode"])
            if "ignore-hosts" in self._saved:
                self._gsettings(
                    "set",
                    "org.gnome.system.proxy",
                    "ignore-hosts",
                    self._saved["ignore-hosts"],
                )
            if "socks-host" in self._saved:
                self._gsettings(
                    "set",
                    "org.gnome.system.proxy.socks",
                    "host",
                    self._saved["socks-host"],
                )
            if "socks-port" in self._saved:
                self._gsettings(
                    "set",
                    "org.gnome.system.proxy.socks",
                    "port",
                    self._saved["socks-port"],
                )
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
        self._saved.clear()
        self._active = False


class WindowsSystemProxy(SystemProxyBackend):
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

    def __init__(self) -> None:
        self._saved: dict[str, object] = {}
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    def _read_values(self) -> dict[str, object]:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH) as key:
            values: dict[str, object] = {}
            for name in ("ProxyEnable", "ProxyServer", "ProxyOverride"):
                try:
                    values[name] = winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    pass
            return values

    def _write_values(self, values: dict[str, object]) -> None:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            self.REG_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            for name, value in values.items():
                if isinstance(value, int):
                    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
                else:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))

        try:
            import ctypes

            internet_set_option = ctypes.windll.wininet.InternetSetOptionW
            internet_set_option(0, 39, 0, 0)
            internet_set_option(0, 37, 0, 0)
        except Exception:
            pass

    def prepare(
        self,
        dns_servers: Optional[List[str]] = None,
        bypass_hosts: Optional[List[str]] = None,
        disable_ipv6: bool = True,
    ) -> None:
        if not self._saved:
            self._saved = self._read_values()
        bypass = _build_bypass_list(bypass_hosts or [])
        override = ";".join(item.replace("*.local", "<local>") for item in bypass)
        self._write_values({"ProxyOverride": override})

    def enable_socks(
        self,
        host: str = "127.0.0.1",
        port: int = 1080,
        bypass_hosts: Optional[List[str]] = None,
    ) -> None:
        if not self._saved:
            self._saved = self._read_values()
        bypass = _build_bypass_list(bypass_hosts or [])
        override = ";".join(item.replace("*.local", "<local>") for item in bypass)
        self._write_values(
            {
                "ProxyEnable": 1,
                "ProxyServer": f"socks={host}:{port}",
                "ProxyOverride": override,
            }
        )
        self._active = True

    def disable(self) -> None:
        if not self._saved:
            self._active = False
            return
        restore: dict[str, object] = {
            "ProxyEnable": int(self._saved.get("ProxyEnable", 0)),
        }
        if "ProxyServer" in self._saved:
            restore["ProxyServer"] = self._saved["ProxyServer"]
        if "ProxyOverride" in self._saved:
            restore["ProxyOverride"] = self._saved["ProxyOverride"]
        try:
            self._write_values(restore)
        except Exception:
            pass
        self._saved.clear()
        self._active = False


class UnsupportedSystemProxy(SystemProxyBackend):
    @property
    def is_active(self) -> bool:
        return False

    def prepare(
        self,
        dns_servers: Optional[List[str]] = None,
        bypass_hosts: Optional[List[str]] = None,
        disable_ipv6: bool = True,
    ) -> None:
        raise RuntimeError("System SOCKS is not supported on this platform")

    def enable_socks(
        self,
        host: str = "127.0.0.1",
        port: int = 1080,
        bypass_hosts: Optional[List[str]] = None,
    ) -> None:
        raise RuntimeError("System SOCKS is not supported on this platform")

    def disable(self) -> None:
        pass


def create_system_proxy() -> SystemProxyBackend:
    if is_macos():
        return MacSystemProxy()
    if is_linux():
        return LinuxSystemProxy()
    if is_windows():
        return WindowsSystemProxy()
    return UnsupportedSystemProxy()


class SystemProxy:
    """Facade for platform-specific system proxy configuration."""

    def __init__(self) -> None:
        self._backend = create_system_proxy()

    @property
    def is_active(self) -> bool:
        return self._backend.is_active

    def prepare(
        self,
        dns_servers: Optional[List[str]] = None,
        bypass_hosts: Optional[List[str]] = None,
        disable_ipv6: bool = True,
    ) -> None:
        self._backend.prepare(
            dns_servers=dns_servers,
            bypass_hosts=bypass_hosts,
            disable_ipv6=disable_ipv6,
        )

    def enable_socks(
        self,
        host: str = "127.0.0.1",
        port: int = 1080,
        bypass_hosts: Optional[List[str]] = None,
    ) -> None:
        self._backend.enable_socks(host=host, port=port, bypass_hosts=bypass_hosts)

    def disable(self) -> None:
        self._backend.disable()

    @staticmethod
    def is_supported() -> bool:
        return is_macos() or is_linux() or is_windows()

    @staticmethod
    def is_macos() -> bool:
        return is_macos()

    @staticmethod
    def secondary_dns(primary: str) -> str:
        return secondary_dns(primary)
