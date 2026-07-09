# EasySSH

A cross-platform GUI app (macOS, Linux, Windows) that routes traffic through SSH — similar to Proxyfire — without breaking the SSH tunnel itself.

## Why not system proxy?

Setting the OS system SOCKS proxy to `127.0.0.1:1080` routes **all** traffic through the local proxy, including the SSH client that creates the tunnel. That causes a loop: SSH tries to connect through itself and fails.

**VPN mode** avoids this by routing at the network level (`sshuttle`) instead of using system SOCKS settings. The SSH connection to your server is excluded automatically.

## Connection modes

| Mode | Whole system | Admin required | Platforms |
|------|--------------|----------------|-----------|
| **VPN** (recommended) | Yes | Yes | macOS, Linux, Windows* |
| **SOCKS only** | No | No | All |
| **System SOCKS** (legacy) | Yes | No | macOS, Linux (GNOME), Windows |

\* Windows VPN mode also requires `pydivert` (`pip install pydivert`).

## Requirements

- Python 3.10+
- OpenSSH client (`ssh` in PATH)
- Python packages: `pexpect`, `sshuttle` (see setup below)

### Platform notes

| Platform | VPN mode | System SOCKS |
|----------|----------|--------------|
| **macOS** | `sshuttle` + `pf` via admin prompt | `networksetup` |
| **Linux** | `sshuttle` + `iptables`/`nft` via `pkexec`/`sudo` | GNOME `gsettings` |
| **Windows** | `sshuttle` + WinDivert via UAC (`pydivert` required) | Registry (Internet Settings) |

## Setup

```bash
cd EasySSH
python3 -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate

pip install -r requirements.txt
```

### Windows VPN (optional)

```bash
pip install pydivert
```

## Run from source

```bash
python main.py
```

## Install from release (recommended)

Download the latest release for your platform from  
**[GitHub Releases](https://github.com/Ahmadrezagh/EasySSH/releases)**.

| Platform | Download | How to run |
|----------|----------|------------|
| **macOS** | `EasySSH-macOS.zip` | Unzip → open `EasySSH.app` |
| **Windows** | `EasySSH-Windows.zip` | Unzip → run `EasySSH/EasySSH.exe` |
| **Linux** | `EasySSH-Linux.tar.gz` | Extract → run `EasySSH/EasySSH` |

> **Note:** OpenSSH (`ssh`) must still be installed on your system. VPN mode may prompt for admin/root access.

### Create a new release (maintainers)

```bash
git tag v1.0.0
git push origin v1.0.0
```

Pushing a `v*` tag triggers [GitHub Actions](.github/workflows/release.yml) to build macOS, Linux, and Windows installers and publish them to GitHub Releases.

## Usage

### VPN mode (recommended)

1. Select **VPN mode (whole system, recommended)**.
2. Enter SSH host, port, username, and password.
3. Click **Connect**.
4. Approve the admin/UAC prompt when your OS asks.
5. Click **Disconnect** when finished.

### SOCKS only

1. Select **SOCKS only (manual per-app setup)**.
2. Enter SSH credentials and local port (default `1080`).
3. Click **Connect**.
4. In each app, set SOCKS5 proxy to `127.0.0.1` and your local port.

### System SOCKS (not recommended)

Uses OS proxy settings. Can still loop SSH through itself on some systems.

- **macOS**: also sets custom DNS and disables IPv6 while connected.
- **Linux**: requires GNOME desktop (`gsettings`).
- **Windows**: sets Internet Settings proxy with bypass list.

## How VPN mode works

1. `sshuttle` is copied to a temp directory so elevated processes can import it (avoids venv permission issues on macOS).
2. A launcher script runs with administrator/root privileges.
3. `sshuttle` redirects traffic through SSH transparently.
4. On disconnect, routing rules are removed and temp files are cleaned up.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **VPN: PermissionError on `.venv`** | Update to latest code — VPN stages `sshuttle` to temp and uses system Python. |
| **VPN: Admin/UAC canceled** | Connect again and approve the prompt. |
| **Linux VPN: sudo/polkit failed** | Install `policykit-1` (`pkexec`) or configure passwordless sudo. |
| **Linux System SOCKS not working** | GNOME only — use VPN mode or SOCKS only on KDE/other desktops. |
| **Windows VPN: pydivert missing** | Run `pip install pydivert` or use SOCKS only mode. |
| **SSH not found (Windows)** | Install [OpenSSH Client](https://docs.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse) and ensure `ssh` is in PATH. |
| **Telegram disconnects (SOCKS)** | Set SOCKS5 manually in Telegram settings. |

## Notes

- SSH details (host, port, username, password, mode) are saved locally after a successful connect and when you close the app.
  - macOS / Linux: `~/.config/easyssh/settings.json`
  - Windows: `%APPDATA%\EasySSH\settings.json`
- The first connection to a new SSH host accepts the host key automatically.
- VPN mode needs admin rights because `sshuttle` modifies system firewall/routing rules.
- SOCKS proxies handle TCP only; UDP-based apps may not work through the tunnel.
- Some apps ignore system proxy settings and need manual SOCKS configuration.
