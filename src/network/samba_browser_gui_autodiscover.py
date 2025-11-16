#!/opt/homebrew/bin/python3
"""
Samba share browser with Tkinter GUI and LAN auto-discovery.

Features:
  - Auto-discover SMB servers on local /24 LAN (simple port 445 scan)
  - Connect to SMB/CIFS (Samba) server
  - List available shares
  - Browse folders within a share
  - Prompt for username/password/domain
  - Download files to a local folder

Requirements:
    pip install pysmb

Tested with Python 3.11+.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import threading
import tkinter as tk
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox
import tkinter.ttk as ttk
from dataclasses import dataclass
from typing import List, Optional

# Default domain for SMB connections
DEFAULT_DOMAIN = "WORKGROUP"

try:
    from smb.SMBConnection import SMBConnection
    from nmb.NetBIOS import NetBIOS
except Exception as exc:  # pragma: no cover
    SMBConnection = None  # type: ignore[assignment]
    NetBIOS = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


@dataclass
class SMBState:
    connection: Optional[SMBConnection] = None
    server: str = ""
    port: int = 445
    share: str = ""
    path_parts: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.path_parts is None:
            self.path_parts = []


def _guess_lan_prefix() -> Optional[str]:
    """Best-effort guess of local /24 prefix, e.g. '192.168.1'.

    This tries several strategies to find a non-loopback, private IPv4
    address, which tends to be more reliable on macOS and laptops with
    multiple interfaces.
    """

    def _valid_ipv4(ip: str) -> bool:
        try:
            ip_obj = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if ip_obj.is_loopback:
            return False
        if not ip_obj.is_private:
            return False
        return True

    candidates: list[str] = []

    # 1) Basic hostname lookup (may return 127.0.0.1 on some systems)
    try:
        hostname = socket.gethostname()
        _, _, addrs = socket.gethostbyname_ex(hostname)
        for ip in addrs:
            if ip not in candidates:
                candidates.append(ip)
    except Exception:
        pass

    # 2) getaddrinfo-based discovery
    try:
        info_list = socket.getaddrinfo(None, 0, socket.AF_INET, socket.SOCK_STREAM)
        for info in info_list:
            ip = info[4][0]
            if ip not in candidates:
                candidates.append(ip)
    except Exception:
        pass

    # 3) Fallback: single gethostbyname
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip not in candidates:
            candidates.append(ip)
    except Exception:
        pass

    for ip in candidates:
        if not _valid_ipv4(ip):
            continue
        parts = ip.split(".")
        if len(parts) != 4:
            continue
        return ".".join(parts[:3])

    return None


class SambaBrowserApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Samba Share Browser")
        self.geometry("900x520")
        self.state = SMBState()
        self.discovered_servers: List[str] = []
        self.server_display_map: dict[str, str] = {}
        self.server_credentials: dict[str, tuple[str, str, str]] = {}
        self.servers_with_hostname: int = 0
        self.servers_ip_only: int = 0
        self.hostname_resolution_detail: dict[str, str] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Server:").grid(row=0, column=0, sticky="w")
        self.server_entry = ttk.Combobox(top, width=24)
        self.server_entry.grid(row=0, column=1, sticky="we", padx=4)

        ttk.Label(top, text="Port:").grid(row=0, column=2, sticky="w")
        self.port_entry = ttk.Entry(top, width=6)
        self.port_entry.insert(0, "445")
        self.port_entry.grid(row=0, column=3, sticky="w", padx=4)

        self.discover_button = ttk.Button(
            top,
            text="Discover LAN servers",
            command=self.on_discover_clicked,
        )
        self.discover_button.grid(row=0, column=4, sticky="w", padx=4)

        self.connect_button = ttk.Button(
            top,
            text="Connect...",
            command=self.on_connect_clicked,
        )
        self.connect_button.grid(row=1, column=4, sticky="e", padx=4, pady=(4, 0))

        top.columnconfigure(1, weight=1)

        middle = ttk.Frame(self, padding=(8, 0))
        middle.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(middle, text="Shares:").pack(side=tk.LEFT)
        self.share_combo = ttk.Combobox(middle, state="readonly", width=40)
        self.share_combo.pack(side=tk.LEFT, padx=4)
        self.share_combo.bind("<<ComboboxSelected>>", self.on_share_selected)

        self.path_label = ttk.Label(middle, text="/", anchor="w")
        self.path_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        self.up_button = ttk.Button(
            middle,
            text="Up",
            command=self.on_up_clicked,
        )
        self.up_button.pack(side=tk.RIGHT, padx=4)

        main = ttk.Frame(self, padding=8)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(
            main,
            columns=("name", "type", "size"),
            show="headings",
        )
        self.tree.heading("name", text="Name")
        self.tree.heading("type", text="Type")
        self.tree.heading("size", text="Size (bytes)")
        self.tree.column("name", width=320, anchor="w")
        self.tree.column("type", width=80, anchor="w")
        self.tree.column("size", width=120, anchor="e")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        scroll = ttk.Scrollbar(
            main,
            orient="vertical",
            command=self.tree.yview,
        )
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scroll.set)

        bottom = ttk.Frame(self, padding=8)
        bottom.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_var = tk.StringVar(value="Disconnected.")
        status_label = ttk.Label(
            bottom,
            textvariable=self.status_var,
            anchor="w",
        )
        status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        download_btn = ttk.Button(
            bottom,
            text="Download selected file...",
            command=self.on_download_clicked,
        )
        download_btn.pack(side=tk.RIGHT)

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    # -------- LAN discovery --------

    def on_discover_clicked(self) -> None:
        prefix = _guess_lan_prefix()
        if not prefix:
            messagebox.showerror(
                "Discovery error",
                "Could not determine local LAN prefix automatically.",
            )
            return

        self.discover_button.config(state=tk.DISABLED)
        self.discovered_servers.clear()
        self.server_display_map.clear()
        self.servers_with_hostname = 0
        self.servers_ip_only = 0
        self.hostname_resolution_detail.clear()
        self.server_entry["values"] = ()
        self.set_status(f"Scanning {prefix}.0/24 for SMB servers (port 445)...")

        thread = threading.Thread(
            target=self._discover_worker,
            args=(prefix,),
            daemon=True,
        )
        thread.start()

    def _discover_worker(self, prefix: str) -> None:
        for host in range(1, 255):
            ip = f"{prefix}.{host}"
            try:
                sock = socket.create_connection((ip, 445), timeout=0.2)
                sock.close()
            except OSError:
                continue
            self.after(0, lambda ip=ip: self._add_discovered_server(ip))

        self.after(0, self._on_discover_finished)

    def _add_discovered_server(self, ip: str) -> None:
        """Add a discovered SMB server using a friendly display name if possible.

        We try reverse DNS, FQDN, and NetBIOS; if those fail or just echo the IP, we
        fall back to the raw IP string. The dropdown is kept sorted with named hosts
        first, then IP-only entries.
        """

        display: str
        host: str | None = None
        resolution_method: str = ""
        reasons: list[str] = []

        # Try reverse DNS first
        try:
            host, _, _ = socket.gethostbyaddr(ip)
            if host == ip:
                host = None
                reasons.append("reverse DNS returned IP only")
            else:
                resolution_method = "DNS"
        except Exception:
            host = None
            reasons.append("reverse DNS failed")

        # If reverse DNS did not produce something useful, try FQDN
        if not host or host == ip:
            try:
                fqdn = socket.getfqdn(ip)
            except Exception:
                fqdn = ""
                reasons.append("FQDN lookup failed")
            else:
                if fqdn and fqdn != ip:
                    host = fqdn
                    resolution_method = "FQDN"
                elif fqdn == ip:
                    reasons.append("FQDN returned IP only")

        # If we still do not have a useful hostname, try NetBIOS via pysmb's
        # nmb helper. This is often what SMB browsers use on local networks.
        if not host or host == ip:
            if NetBIOS is not None:
                try:
                    with NetBIOS() as nb:
                        names = nb.queryIPForName(ip, timeout=0.3)
                    if names:
                        host = names[0]
                        resolution_method = "NetBIOS"
                    else:
                        reasons.append("NetBIOS returned no names")
                except Exception as e:
                    reasons.append(f"NetBIOS lookup error: {type(e).__name__}")
            else:
                reasons.append("NetBIOS not available")

        if host and host != ip:
            display = f"{host} ({ip})"
            self.servers_with_hostname += 1
            detail = f"Resolved via {resolution_method}"
            self.hostname_resolution_detail[ip] = detail
        else:
            display = f"[IP-only] {ip}"
            self.servers_ip_only += 1
            detail = "; ".join(reasons) if reasons else "No hostname via DNS/NetBIOS"
            self.hostname_resolution_detail[ip] = detail

        if display in self.discovered_servers:
            return

        self.server_display_map[display] = ip
        self.discovered_servers.append(display)
        
        # Sort: named hosts first (those without [IP-only] prefix), then IP-only entries
        sorted_servers = sorted(
            self.discovered_servers,
            key=lambda s: (s.startswith("[IP-only]"), s.lower())
        )
        self.discovered_servers = sorted_servers
        self.server_entry["values"] = tuple(self.discovered_servers)
        
        if not self.server_entry.get():
            self.server_entry.set(display)
        
        # Update status with live count
        total = len(self.discovered_servers)
        self.set_status(
            f"Scanning... Found {total} server(s) "
            f"({self.servers_with_hostname} named, {self.servers_ip_only} IP-only)"
        )

    def _ensure_manual_server_in_list(self, text: str, resolved: str) -> None:
        """Ensure a manually typed server name appears in the dropdown.

        This makes hostnames entered by the user reusable, even if
        auto-discovery only found IPs.
        """
        text = text.strip()
        if not text:
            return
        if text not in self.discovered_servers:
            self.discovered_servers.append(text)
            if resolved:
                self.server_display_map.setdefault(text, resolved)
            self.server_entry["values"] = tuple(self.discovered_servers)
    def _resolve_server_host(self, text: str) -> str:
        """Map a combobox display string back to an IP/hostname.
        
        Handles both '[IP-only] x.x.x.x' and 'hostname (x.x.x.x)' formats.
        """
        mapped = self.server_display_map.get(text)
        if mapped:
            return mapped
        
        # Handle '[IP-only] x.x.x.x' format
        if text.startswith("[IP-only]"):
            ip = text.replace("[IP-only]", "").strip()
            if ip:
                return ip
        
        # Handle 'hostname (x.x.x.x)' format
        if "(" in text and ")" in text:
            try:
                inner = text.split("(", 1)[1].split(")", 1)[0].strip()
                if inner:
                    return inner
            except Exception:
                pass
        
        return text

    def _prompt_credentials(self, server: str) -> Optional[tuple[str, str, str]]:
        """Prompt for domain/username/password.

        Defaults to anonymous (blank username/password) and DEFAULT_DOMAIN.
        Returns (domain, username, password) or None if cancelled.
        """

        dialog = tk.Toplevel(self)
        dialog.title(f"Credentials for {server}")
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(dialog, text=f"Server: {server}").grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            padx=8,
            pady=(8, 4),
        )

        ttk.Label(dialog, text="Domain:").grid(
            row=1,
            column=0,
            sticky="w",
            padx=8,
            pady=2,
        )
        domain_var = tk.StringVar(value=DEFAULT_DOMAIN)
        domain_entry = ttk.Entry(dialog, textvariable=domain_var, width=24)
        domain_entry.grid(row=1, column=1, sticky="we", padx=8, pady=2)

        ttk.Label(dialog, text="Username (blank = anonymous):").grid(
            row=2,
            column=0,
            sticky="w",
            padx=8,
            pady=2,
        )
        user_var = tk.StringVar(value="")
        user_entry = ttk.Entry(dialog, textvariable=user_var, width=24)
        user_entry.grid(row=2, column=1, sticky="we", padx=8, pady=2)

        ttk.Label(dialog, text="Password:").grid(
            row=3,
            column=0,
            sticky="w",
            padx=8,
            pady=2,
        )
        password_var = tk.StringVar(value="")
        password_entry = ttk.Entry(dialog, textvariable=password_var, width=24, show="*")
        password_entry.grid(row=3, column=1, sticky="we", padx=8, pady=2)

        result: dict[str, Optional[tuple[str, str, str]]] = {"value": None}

        def on_ok() -> None:
            dom = domain_var.get().strip() or DEFAULT_DOMAIN
            user = user_var.get().strip()
            pwd = password_var.get()
            result["value"] = (dom, user, pwd)
            dialog.destroy()

        def on_cancel() -> None:
            result["value"] = None
            dialog.destroy()

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=4, column=0, columnspan=2, pady=(8, 8))

        ok_btn = ttk.Button(button_frame, text="OK", command=on_ok)
        ok_btn.pack(side=tk.LEFT, padx=4)

        cancel_btn = ttk.Button(button_frame, text="Cancel", command=on_cancel)
        cancel_btn.pack(side=tk.LEFT, padx=4)

        dialog.columnconfigure(1, weight=1)
        user_entry.focus_set()
        dialog.bind("<Return>", lambda _event: on_ok())
        dialog.bind("<Escape>", lambda _event: on_cancel())

        self.wait_window(dialog)
        return result["value"]

    def _on_discover_finished(self) -> None:
        self.discover_button.config(state=tk.NORMAL)
        if self.discovered_servers:
            total = len(self.discovered_servers)
            if self.servers_ip_only == 0:
                # All servers resolved to hostnames
                message = f"Discovery complete: Found {total} SMB server(s), all with hostnames."
            elif self.servers_with_hostname == 0:
                # No servers resolved to hostnames
                message = (
                    f"Discovery complete: Found {total} SMB server(s), all IP-only. "
                    f"This is normal on networks without DNS/NetBIOS name resolution."
                )
            else:
                # Mixed results
                message = (
                    f"Discovery complete: Found {total} SMB server(s) "
                    f"({self.servers_with_hostname} named, {self.servers_ip_only} IP-only). "
                    f"Entries marked [IP-only] could not resolve hostnames via DNS/NetBIOS."
                )
            self.set_status(message)
        else:
            self.set_status("Discovery complete: No SMB servers found on LAN.")

    # -------- Connection handling --------

    def on_connect_clicked(self) -> None:
        if _IMPORT_ERROR is not None or SMBConnection is None:
            messagebox.showerror(
                "Missing dependency",
                f"pysmb is not installed or failed to import: {_IMPORT_ERROR}",
            )
            return

        server_text = self.server_entry.get().strip()
        if not server_text:
            messagebox.showerror("Error", "Please enter or select a server.")
            return

        server = self._resolve_server_host(server_text)
        # Make sure whatever the user typed (hostname or IP) is remembered
        # in the dropdown and mapped back to the resolved host.
        self._ensure_manual_server_in_list(server_text, server)

        try:
            port = int(self.port_entry.get().strip() or "445")
        except ValueError:
            messagebox.showerror("Error", "Port must be a number.")
            return

        creds = self.server_credentials.get(server)
        if creds is None:
            creds = self._prompt_credentials(server)
            if creds is None:
                # User cancelled
                return

        domain, username, password = creds

        self.connect_button.config(state=tk.DISABLED)
        self.set_status("Connecting...")

        thread = threading.Thread(
            target=self._connect_worker,
            args=(server, port, username, password, domain),
            daemon=True,
        )
        thread.start()

    def _connect_worker(
        self,
        server: str,
        port: int,
        username: str,
        password: str,
        domain: str,
    ) -> None:
        try:
            client_name = os.uname().nodename
        except Exception:
            client_name = "smb-client"

        try:
            conn = SMBConnection(
                username or "",
                password or "",
                client_name,
                server,
                domain=domain or "",
                use_ntlm_v2=True,
                is_direct_tcp=(port == 445),
            )
            ok = conn.connect(server, port, timeout=10)
            if not ok:
                raise OSError("Connection failed")
            # Remember the last-used credentials for this server
            self.server_credentials[server] = (domain or DEFAULT_DOMAIN, username or "", password or "")
        except Exception as exc:
            self.after(0, lambda exc=exc: self._on_connect_failed(exc))
            return

        self.state.connection = conn
        self.state.server = server
        self.state.port = port
        self.state.share = ""
        self.state.path_parts = []

        try:
            shares = [
                s.name
                for s in conn.listShares()
                if not s.isSpecial and s.name not in ("NETLOGON", "IPC$")
            ]
        except Exception as exc:
            self.after(0, lambda exc=exc: self._on_connect_failed(exc))
            return

        self.after(0, lambda shares=shares: self._on_connect_success(shares))

    def _on_connect_failed(self, exc: Exception) -> None:
        self.connect_button.config(state=tk.NORMAL)
        self.set_status("Connection failed.")
        messagebox.showerror("Connection failed", str(exc))

    def _on_connect_success(self, shares: List[str]) -> None:
        self.connect_button.config(state=tk.NORMAL)
        self.share_combo["values"] = shares
        if shares:
            self.share_combo.current(0)
            self.state.share = shares[0]
            self.refresh_listing()
        self.set_status(f"Connected to {self.state.server}.")

    # -------- Directory browsing --------

    def on_share_selected(self, _event: object) -> None:
        share = self.share_combo.get().strip()
        if not share:
            return
        self.state.share = share
        self.state.path_parts = []
        self.refresh_listing()

    def on_up_clicked(self) -> None:
        if not self.state.path_parts:
            return
        self.state.path_parts.pop()
        self.refresh_listing()

    def refresh_listing(self) -> None:
        conn = self.state.connection
        if conn is None:
            return
        share = self.state.share
        if not share:
            return

        path = "/".join(self.state.path_parts)
        path_display = "/" + path if path else "/"
        self.path_label.config(text=f"{share}:{path_display}")
        self.tree.delete(*self.tree.get_children())
        self.set_status("Loading directory...")

        def worker() -> None:
            try:
                remote_path = path or "/"
                entries = conn.listPath(share, remote_path)
            except Exception as exc:
                self.after(0, lambda exc=exc: self._on_list_failed(exc))
                return
            self.after(0, lambda entries=entries: self._on_list_success(entries))

        threading.Thread(target=worker, daemon=True).start()

    def _on_list_failed(self, exc: Exception) -> None:
        self.set_status("Failed to list directory.")
        messagebox.showerror("Error", str(exc))

    def _on_list_success(self, entries) -> None:
        for e in entries:
            if e.filename in (".", ".."):
                continue
            entry_type = "dir" if e.isDirectory else "file"
            size_str = "" if e.isDirectory else str(e.file_size)
            self.tree.insert(
                "",
                tk.END,
                values=(e.filename, entry_type, size_str),
            )
        self.set_status("Ready.")

    def on_tree_double_click(self, _event: object) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        item_id = selection[0]
        item = self.tree.item(item_id)
        values = item.get("values", [])
        if not values:
            return
        entry_type = values[1]
        name = values[0]
        if entry_type == "dir":
            self.state.path_parts.append(name)
            self.refresh_listing()
        else:
            self.on_download_clicked()

    # -------- Downloading --------

    def on_download_clicked(self) -> None:
        conn = self.state.connection
        if conn is None:
            messagebox.showerror("Error", "Not connected.")
            return
        share = self.state.share
        if not share:
            messagebox.showerror("Error", "No share selected.")
            return

        selection = self.tree.selection()
        if not selection:
            messagebox.showerror("Error", "No file selected.")
            return

        item_id = selection[0]
        item = self.tree.item(item_id)
        values = item.get("values", [])
        if not values or values[1] != "file":
            messagebox.showerror("Error", "Please select a file, not a folder.")
            return

        filename = values[0]
        local_dir = filedialog.askdirectory(
            title="Select destination folder",
        )
        if not local_dir:
            return

        remote_path = "/".join(self.state.path_parts + [filename])
        local_path = os.path.join(local_dir, filename)
        self.set_status(f"Downloading {filename}...")

        def worker() -> None:
            try:
                with open(local_path, "wb") as fh:
                    conn.retrieveFile(share, remote_path, fh)
            except Exception as exc:
                self.after(0, lambda exc=exc: self._on_download_failed(exc))
                return
            self.after(0, lambda p=local_path: self._on_download_success(p))

        threading.Thread(target=worker, daemon=True).start()

    def _on_download_failed(self, exc: Exception) -> None:
        self.set_status("Download failed.")
        messagebox.showerror("Download failed", str(exc))

    def _on_download_success(self, path: str) -> None:
        self.set_status("Download complete.")
        messagebox.showinfo("Download complete", f"Saved to:\n{path}")


def main() -> None:
    app = SambaBrowserApp()
    app.mainloop()


if __name__ == "__main__":
    main()
