"""EasySSH — GUI application for SOCKS5 / VPN over SSH."""

from __future__ import annotations

import queue
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from elevation import elevation_hint
from platform_util import is_macos, platform_label
from settings import AppSettings, load_settings, save_settings
from system_proxy import SystemProxy
from tunnel import SSHTunnel, TunnelConfig
from vpn_tunnel import SSHuttleTunnel

LOGO_PATH = Path(__file__).resolve().parent / "img" / "logo.png"


class EasySSHApp:
    BG = "#1e1e2e"
    FG = "#cdd6f4"
    ACCENT = "#89b4fa"
    SUCCESS = "#a6e3a1"
    ERROR = "#f38ba8"
    INPUT_BG = "#313244"
    MUTED = "#a6adc8"

    MODE_VPN = "vpn"
    MODE_SOCKS = "socks"
    MODE_SYSTEM = "system"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("EasySSH")
        self.root.geometry("500x820")
        self.root.minsize(500, 820)
        self.root.resizable(True, True)
        self.root.configure(bg=self.BG)
        self._icon_photo: tk.PhotoImage | None = None
        self._header_photo: tk.PhotoImage | None = None
        self._icon_photo, self._header_photo = self._load_logo_images()
        if self._icon_photo is not None:
            self.root.iconphoto(True, self._icon_photo)

        self.socks_tunnel = SSHTunnel(
            on_status=self._queue_status,
            on_lost=lambda: self.root.after(0, self._on_tunnel_lost),
        )
        self.vpn_tunnel = SSHuttleTunnel(
            on_status=self._queue_status,
            on_lost=lambda: self.root.after(0, self._on_tunnel_lost),
        )
        self.system_proxy = SystemProxy()
        self.status_queue: queue.Queue[str] = queue.Queue()
        self.connected = False
        self.active_mode: str | None = None
        self._settings = load_settings()

        self._build_ui()
        self._poll_status()
        self._on_mode_change()

    def _load_logo_images(self) -> tuple[tk.PhotoImage | None, tk.PhotoImage | None]:
        if not LOGO_PATH.exists():
            return None, None
        try:
            full = tk.PhotoImage(file=str(LOGO_PATH))
        except tk.TclError:
            return None, None

        width, height = full.width(), full.height()
        icon_factor = max(1, max(width, height) // 48)
        header_factor = max(1, max(width, height) // 72)
        icon = full.subsample(icon_factor, icon_factor) if icon_factor > 1 else full
        header = (
            full.subsample(header_factor, header_factor)
            if header_factor > 1
            else full
        )
        return icon, header

    def _build_ui(self) -> None:
        button_row = tk.Frame(self.root, bg=self.BG, padx=28)
        button_row.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 24))

        self.connect_btn = tk.Button(
            button_row,
            text="Connect",
            command=self._on_connect,
            bg=self.ACCENT,
            fg="#11111b",
            activebackground="#74a8f7",
            activeforeground="#11111b",
            font=("Helvetica", 13, "bold"),
            relief=tk.FLAT,
            padx=20,
            pady=12,
            cursor="hand2",
        )
        self.connect_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 8))

        self.disconnect_btn = tk.Button(
            button_row,
            text="Disconnect",
            command=self._on_disconnect,
            bg=self.INPUT_BG,
            fg=self.FG,
            activebackground="#45475a",
            activeforeground=self.FG,
            font=("Helvetica", 13, "bold"),
            relief=tk.FLAT,
            padx=20,
            pady=12,
            state=tk.DISABLED,
            cursor="hand2",
        )
        self.disconnect_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(8, 0))

        container = tk.Frame(self.root, bg=self.BG, padx=28, pady=24)
        container.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(container, bg=self.BG)
        header.pack(anchor=tk.W, pady=(0, 4))

        if self._header_photo is not None:
            tk.Label(header, image=self._header_photo, bg=self.BG).pack(
                side=tk.LEFT, padx=(0, 12)
            )

        title_block = tk.Frame(header, bg=self.BG)
        title_block.pack(side=tk.LEFT, fill=tk.X, expand=True)

        title = tk.Label(
            title_block,
            text="EasySSH",
            font=("Helvetica", 20, "bold"),
            bg=self.BG,
            fg=self.FG,
        )
        title.pack(anchor=tk.W)

        subtitle = tk.Label(
            title_block,
            text="Route system traffic through SSH without breaking the tunnel",
            font=("Helvetica", 11),
            bg=self.BG,
            fg=self.MUTED,
            wraplength=340,
            justify=tk.LEFT,
        )
        subtitle.pack(anchor=tk.W, pady=(4, 0))

        mode_row = tk.LabelFrame(
            container,
            text=" Connection mode ",
            bg=self.BG,
            fg=self.MUTED,
            font=("Helvetica", 10),
            padx=12,
            pady=10,
        )
        mode_row.pack(fill=tk.X, pady=(12, 12))

        self.mode_var = tk.StringVar(value=self._settings.mode or self.MODE_VPN)

        for value, label in (
            (self.MODE_VPN, "VPN mode (whole system, recommended)"),
            (self.MODE_SOCKS, "SOCKS only (manual per-app setup)"),
            (self.MODE_SYSTEM, "System SOCKS (legacy, can break SSH)"),
        ):
            tk.Radiobutton(
                mode_row,
                text=label,
                variable=self.mode_var,
                value=value,
                command=self._on_mode_change,
                bg=self.BG,
                fg=self.FG,
                activebackground=self.BG,
                activeforeground=self.FG,
                selectcolor=self.INPUT_BG,
                font=("Helvetica", 11),
                anchor=tk.W,
                justify=tk.LEFT,
            ).pack(anchor=tk.W, pady=2)

        self.mode_hint = tk.Label(
            mode_row,
            text="",
            font=("Helvetica", 10),
            bg=self.BG,
            fg=self.MUTED,
            wraplength=410,
            justify=tk.LEFT,
        )
        self.mode_hint.pack(anchor=tk.W, pady=(8, 0))

        self.host_var = tk.StringVar(value=self._settings.host)
        self.port_var = tk.StringVar(value=self._settings.port or "22")
        self.username_var = tk.StringVar(value=self._settings.username)
        self.password_var = tk.StringVar(value=self._settings.password)
        self.local_port_var = tk.StringVar(value=self._settings.local_port or "1080")
        self.dns_var = tk.StringVar(value=self._settings.dns or "8.8.8.8")

        self._add_field(container, "SSH Host", self.host_var, "example.com")
        self._add_field(container, "SSH Port", self.port_var, "22")
        self._add_field(container, "Username", self.username_var, "user")
        self._add_field(container, "Password", self.password_var, "", show="•")

        self.local_port_row = tk.Frame(container, bg=self.BG)
        self.local_port_row.pack(fill=tk.X)
        self._add_field(self.local_port_row, "Local SOCKS Port", self.local_port_var, "1080")

        self.dns_row = tk.Frame(container, bg=self.BG)
        self.dns_row.pack(fill=tk.X)
        self._add_field(self.dns_row, "DNS Server", self.dns_var, "8.8.8.8")

        self.status_label = tk.Label(
            container,
            text="● Disconnected",
            font=("Helvetica", 12, "bold"),
            bg=self.BG,
            fg=self.ERROR,
        )
        self.status_label.pack(anchor=tk.W, pady=(16, 4))

        self.log_label = tk.Label(
            container,
            text="Ready",
            font=("Helvetica", 10),
            bg=self.BG,
            fg=self.MUTED,
            wraplength=430,
            justify=tk.LEFT,
        )
        self.log_label.pack(anchor=tk.W, pady=(0, 8))

        footer = tk.Label(
            container,
            text=f"{platform_label()} · VPN uses sshuttle (no system SOCKS)",
            font=("Helvetica", 9),
            bg=self.BG,
            fg="#585b70",
        )
        footer.pack(anchor=tk.W, pady=(18, 0))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_mode_change(self) -> None:
        mode = self.mode_var.get()
        if mode == self.MODE_VPN:
            self.mode_hint.configure(
                text=(
                    "Like Proxyfire: routes traffic at the network level. "
                    "Does not use system SOCKS proxy, so SSH keeps working. "
                    + elevation_hint()
                )
            )
            self.dns_row.pack_forget()
            self.local_port_row.pack_forget()
        elif mode == self.MODE_SOCKS:
            self.mode_hint.configure(
                text="Creates SOCKS5 on localhost only. Configure each app manually."
            )
            self.local_port_row.pack(fill=tk.X)
            self.dns_row.pack_forget()
        else:
            platform_name = "macOS" if is_macos() else "the system"
            self.mode_hint.configure(
                text=(
                    f"Uses {platform_name} SOCKS proxy settings. "
                    "Can loop SSH through itself and fail."
                )
            )
            self.local_port_row.pack(fill=tk.X)
            if is_macos():
                self.dns_row.pack(fill=tk.X)
            else:
                self.dns_row.pack_forget()

    def _add_field(
        self,
        parent: tk.Frame,
        label: str,
        variable: tk.StringVar,
        placeholder: str,
        show: str | None = None,
    ) -> None:
        row = tk.Frame(parent, bg=self.BG)
        row.pack(fill=tk.X, pady=5)

        tk.Label(
            row,
            text=label,
            font=("Helvetica", 11),
            bg=self.BG,
            fg=self.MUTED,
        ).pack(anchor=tk.W)

        entry = tk.Entry(
            row,
            textvariable=variable,
            font=("Helvetica", 12),
            bg=self.INPUT_BG,
            fg=self.FG,
            insertbackground=self.FG,
            relief=tk.FLAT,
            show=show,
        )
        entry.pack(fill=tk.X, ipady=8, pady=(4, 0))

        if placeholder and not variable.get():
            entry.insert(0, placeholder)
            entry.configure(fg="#6c7086")

            def on_focus_in(event: tk.Event, e: tk.Entry = entry, p: str = placeholder) -> None:
                if e.get() == p:
                    e.delete(0, tk.END)
                    e.configure(fg=self.FG)

            def on_focus_out(
                event: tk.Event,
                e: tk.Entry = entry,
                p: str = placeholder,
                v: tk.StringVar = variable,
            ) -> None:
                if not v.get().strip():
                    e.insert(0, p)
                    e.configure(fg="#6c7086")

            entry.bind("<FocusIn>", on_focus_in)
            entry.bind("<FocusOut>", on_focus_out)

    def _queue_status(self, message: str) -> None:
        self.status_queue.put(message)

    def _poll_status(self) -> None:
        while True:
            try:
                message = self.status_queue.get_nowait()
            except queue.Empty:
                break
            self.log_label.configure(text=message)

        self.root.after(200, self._poll_status)

    def _collect_settings(self) -> AppSettings:
        return AppSettings(
            host=self._get_field_value(self.host_var, "example.com"),
            port=self._get_port_value(self.port_var, "22"),
            username=self._get_field_value(self.username_var, "user"),
            password=self.password_var.get().strip(),
            mode=self.mode_var.get(),
            local_port=self._get_port_value(self.local_port_var, "1080"),
            dns=self._get_dns_value(self.dns_var, "8.8.8.8"),
        )

    def _save_settings(self) -> None:
        save_settings(self._collect_settings())

    def _on_tunnel_lost(self) -> None:
        if not self.connected:
            return
        self._cleanup_connection()
        self._set_disconnected_ui()
        messagebox.showwarning("Connection Lost", "SSH tunnel closed unexpectedly")

    def _get_field_value(self, variable: tk.StringVar, placeholder: str = "") -> str:
        value = variable.get().strip()
        if placeholder and value == placeholder:
            return ""
        return value

    def _get_port_value(self, variable: tk.StringVar, default: str) -> str:
        value = variable.get().strip()
        return value or default

    def _get_dns_value(self, variable: tk.StringVar, default: str) -> str:
        value = variable.get().strip()
        return value or default

    def _is_valid_ip(self, value: str) -> bool:
        if not re.match(r"^(\d{1,3}\.){3}\d{1,3}$", value):
            return False
        return all(0 <= int(part) <= 255 for part in value.split("."))

    def _validate(self) -> tuple[TunnelConfig, str, str] | None:
        mode = self.mode_var.get()
        host = self._get_field_value(self.host_var, "example.com")
        port_text = self._get_port_value(self.port_var, "22")
        username = self._get_field_value(self.username_var, "user")
        password = self.password_var.get().strip()
        local_port_text = self._get_port_value(self.local_port_var, "1080")
        dns = self._get_dns_value(self.dns_var, "8.8.8.8")

        if not host:
            messagebox.showerror("Validation", "SSH host is required")
            return None
        if not username:
            messagebox.showerror("Validation", "Username is required")
            return None
        if not password:
            messagebox.showerror("Validation", "Password is required")
            return None
        if mode == self.MODE_SYSTEM and is_macos() and not self._is_valid_ip(dns):
            messagebox.showerror("Validation", "DNS must be a valid IP address (e.g. 8.8.8.8)")
            return None
        if mode == self.MODE_SYSTEM and not SystemProxy.is_supported():
            messagebox.showerror("Validation", "System SOCKS is not supported on this platform")
            return None
        if mode == self.MODE_VPN and not SSHuttleTunnel.is_available():
            messagebox.showerror("Missing dependency", SSHuttleTunnel.availability_error())
            return None

        try:
            port = int(port_text)
            local_port = int(local_port_text)
        except ValueError:
            messagebox.showerror("Validation", "Ports must be valid numbers")
            return None

        if not (1 <= port <= 65535):
            messagebox.showerror("Validation", "SSH port must be between 1 and 65535")
            return None
        if mode != self.MODE_VPN and not (1 <= local_port <= 65535):
            messagebox.showerror("Validation", "Local SOCKS port must be between 1 and 65535")
            return None

        return (
            TunnelConfig(
                host=host,
                port=port,
                username=username,
                password=password,
                local_port=local_port,
            ),
            dns,
            mode,
        )

    def _on_connect(self) -> None:
        validated = self._validate()
        if not validated:
            return
        config, dns, mode = validated

        self.connect_btn.configure(state=tk.DISABLED)
        self.log_label.configure(text="Connecting...")

        def worker() -> None:
            prepared = False
            try:
                if mode == self.MODE_VPN:
                    self.vpn_tunnel.connect(config)
                    self.active_mode = self.MODE_VPN
                    self._queue_status("Connected · VPN routing all system traffic")
                else:
                    if mode == self.MODE_SYSTEM and SystemProxy.is_supported():
                        if is_macos():
                            dns_servers = [dns, SystemProxy.secondary_dns(dns)]
                            self.system_proxy.prepare(
                                dns_servers=dns_servers,
                                bypass_hosts=[config.host],
                                disable_ipv6=True,
                            )
                        else:
                            self.system_proxy.prepare(bypass_hosts=[config.host])
                        prepared = True

                    self.socks_tunnel.connect(config)
                    self.active_mode = mode

                    if mode == self.MODE_SYSTEM and SystemProxy.is_supported():
                        self.system_proxy.enable_socks(
                            "127.0.0.1",
                            config.local_port,
                            bypass_hosts=[config.host],
                        )
                        self._queue_status(
                            f"Connected · System SOCKS on 127.0.0.1:{config.local_port}"
                        )
                    else:
                        self._queue_status(
                            f"Connected · SOCKS5 on 127.0.0.1:{config.local_port}"
                        )

                self.root.after(0, self._set_connected_ui)
            except Exception as exc:
                if prepared or self.system_proxy.is_active:
                    try:
                        self.system_proxy.disable()
                    except Exception:
                        pass
                self.vpn_tunnel.disconnect()
                self.socks_tunnel.disconnect()
                self.active_mode = None
                error_message = str(exc)
                self.root.after(
                    0,
                    lambda msg=error_message: self._handle_connect_error(msg),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _handle_connect_error(self, message: str) -> None:
        self._set_disconnected_ui()
        messagebox.showerror("Connection Failed", message)

    def _cleanup_connection(self) -> None:
        try:
            self.system_proxy.disable()
        except Exception:
            pass
        self.vpn_tunnel.disconnect()
        self.socks_tunnel.disconnect()
        self.active_mode = None

    def _on_disconnect(self) -> None:
        self.disconnect_btn.configure(state=tk.DISABLED)
        self._cleanup_connection()
        self._set_disconnected_ui()

    def _set_connected_ui(self) -> None:
        self.connected = True
        self._save_settings()
        self.status_label.configure(text="● Connected", fg=self.SUCCESS)
        self.connect_btn.configure(state=tk.DISABLED)
        self.disconnect_btn.configure(state=tk.NORMAL)
        self._set_inputs_state(tk.DISABLED)

    def _set_disconnected_ui(self) -> None:
        self.connected = False
        self.status_label.configure(text="● Disconnected", fg=self.ERROR)
        self.connect_btn.configure(state=tk.NORMAL)
        self.disconnect_btn.configure(state=tk.DISABLED)
        self._set_inputs_state(tk.NORMAL)

    def _set_inputs_state(self, state: str) -> None:
        for child in self.root.winfo_children():
            self._set_widget_state(child, state)

    def _set_widget_state(self, widget: tk.Widget, state: str) -> None:
        if isinstance(widget, (tk.Entry, tk.Radiobutton)):
            widget.configure(state=state)
        for child in widget.winfo_children():
            self._set_widget_state(child, state)

    def _on_close(self) -> None:
        if self.connected:
            self._cleanup_connection()
        self._save_settings()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        style = ttk.Style()
        style.theme_use("clam")
    except Exception:
        pass
    EasySSHApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
