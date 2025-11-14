
"""
Simple Samba share browser with Tkinter GUI.

Requirements:
    pip install pysmb

This script lets you:
  - Connect to an SMB/CIFS (Samba) server
  - List available shares
  - Browse folders within a share
  - Download files to a local folder

Tested with Python 3.11+.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
import tkinter.messagebox as messagebox
import tkinter.filedialog as filedialog
import tkinter.ttk as ttk
from dataclasses import dataclass
from typing import Optional, List

try:
    from smb.SMBConnection import SMBConnection
except Exception as exc:  # pragma: no cover
    SMBConnection = None  # type: ignore[assignment]
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


class SambaBrowserApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Samba Share Browser")
        self.geometry("800x500")
        self.state = SMBState()
        self._build_ui()

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Server:").grid(row=0, column=0, sticky="w")
        self.server_entry = ttk.Entry(top, width=24)
        self.server_entry.grid(row=0, column=1, sticky="we", padx=4)

        ttk.Label(top, text="Port:").grid(row=0, column=2, sticky="w")
        self.port_entry = ttk.Entry(top, width=6)
        self.port_entry.insert(0, "445")
        self.port_entry.grid(row=0, column=3, sticky="w", padx=4)

        ttk.Label(top, text="Domain:").grid(row=1, column=0, sticky="w")
        self.domain_entry = ttk.Entry(top, width=24)
        self.domain_entry.grid(row=1, column=1, sticky="we", padx=4)

        ttk.Label(top, text="Username:").grid(row=1, column=2, sticky="w")
        self.username_entry = ttk.Entry(top, width=16)
        self.username_entry.grid(row=1, column=3, sticky="we", padx=4)

        ttk.Label(top, text="Password:").grid(row=2, column=0, sticky="w")
        self.password_entry = ttk.Entry(top, width=24, show="*")
        self.password_entry.grid(row=2, column=1, sticky="we", padx=4)

        self.connect_button = ttk.Button(
            top,
            text="Connect",
            command=self.on_connect_clicked,
        )
        self.connect_button.grid(row=2, column=3, sticky="e", padx=4)

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
            columns=("type", "size"),
            show="headings",
        )
        self.tree.heading("type", text="Type")
        self.tree.heading("size", text="Size (bytes)")
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

    def on_connect_clicked(self) -> None:
        if _IMPORT_ERROR is not None or SMBConnection is None:
            messagebox.showerror(
                "Missing dependency",
                f"pysmb is not installed or failed to import: {_IMPORT_ERROR}",
            )
            return

        server = self.server_entry.get().strip()
        if not server:
            messagebox.showerror("Error", "Please enter a server name or IP.")
            return

        try:
            port = int(self.port_entry.get().strip() or "445")
        except ValueError:
            messagebox.showerror("Error", "Port must be a number.")
            return

        username = self.username_entry.get().strip()
        password = self.password_entry.get()
        domain = self.domain_entry.get().strip()

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
        except Exception as exc:
            self.after(
                0,
                lambda: self._on_connect_failed(exc),
            )
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
            self.after(
                0,
                lambda: self._on_connect_failed(exc),
            )
            return

        self.after(
            0,
            lambda: self._on_connect_success(shares),
        )

    def _on_connect_failed(self, exc: Exception) -> None:
        self.connect_button.config(state=tk.NORMAL)
        self.set_status("Connection failed.")
        messagebox.showerror("Connection failed", str(exc))

    def _on_connect_success(self, shares: list[str]) -> None:
        self.connect_button.config(state=tk.NORMAL)
        self.share_combo["values"] = shares
        if shares:
            self.share_combo.current(0)
            self.state.share = shares[0]
            self.refresh_listing()
        self.set_status(f"Connected to {self.state.server}.")

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
                self.after(
                    0,
                    lambda: self._on_list_failed(exc),
                )
                return
            self.after(
                0,
                lambda: self._on_list_success(entries),
            )

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
                iid=e.filename,
                values=(entry_type, size_str),
                text=e.filename,
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
        entry_type = values[0]
        name = item_id
        if entry_type == "dir":
            self.state.path_parts.append(name)
            self.refresh_listing()
        else:
            self.on_download_clicked()

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
        if not values or values[0] != "file":
            messagebox.showerror("Error", "Please select a file, not a folder.")
            return

        filename = item_id
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
                self.after(
                    0,
                    lambda: self._on_download_failed(exc),
                )
                return
            self.after(
                0,
                lambda: self._on_download_success(local_path),
            )

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
