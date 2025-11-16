#!/usr/bin/env python3
"""
Pi SD Image Password Helper with Tk GUI + old-school ncurses fallback.

- Primary UI: Tkinter GUI
- Fallback UI: ncurses TUI styled like classic DOS utilities

Run inside WSL or Linux. Uses sudo in the terminal for mount/umount/chroot.
"""

import os
import sys
import subprocess
from typing import Callable, List, Tuple

# Try to import tkinter; if it fails, we will fall back to curses UI
TK_AVAILABLE = True
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
    from tkinter import ttk
except Exception:
    TK_AVAILABLE = False

import curses

StatusSink = Callable[[str], None]
status_sink: StatusSink = lambda msg: None  # replaced by UI layer


# ---------------------------------------------------------------------------
# Shared backend logic
# ---------------------------------------------------------------------------

def set_status_sink(sink: StatusSink) -> None:
    global status_sink
    status_sink = sink


def append_status(msg: str) -> None:
    status_sink(msg)
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def run_cmd(cmd: List[str]) -> Tuple[int, str]:
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def detect_linux_partition_start(img_path: str) -> int:
    result = subprocess.run(
        ["fdisk", "-l", img_path],
        check=True,
        capture_output=True,
        text=True,
    )
    lines = result.stdout.splitlines()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if img_path in stripped and "Linux" in stripped:
            parts = stripped.split()
            if len(parts) < 5:
                continue

            has_boot_flag = parts[1] == "*"
            start_index = 2 if has_boot_flag else 1

            try:
                return int(parts[start_index])
            except (ValueError, IndexError) as exc:
                raise RuntimeError(
                    f"Failed to parse fdisk line: {stripped}"
                ) from exc

    raise RuntimeError("No Linux partition with type 'Linux' found in image.")


def change_pi_password(img_path: str, new_pi_password: str) -> None:
    mount_point = "/mnt/sdroot"
    bind_mounts = [
        ("/dev", "/mnt/sdroot/dev"),
        ("/dev/pts", "/mnt/sdroot/dev/pts"),
        ("/proc", "/mnt/sdroot/proc"),
        ("/sys", "/mnt/sdroot/sys"),
        ("/run", "/mnt/sdroot/run"),
    ]

    append_status("Detecting Linux partition via fdisk...")
    start_sector = detect_linux_partition_start(img_path)
    offset = start_sector * 512

    append_status(f"Linux partition start sector: {start_sector}")
    append_status(f"Offset (bytes): {offset}")
    append_status(f"Mount point: {mount_point}")

    try:
        os.makedirs(mount_point, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Failed to create mount point {mount_point}: {exc}"
        ) from exc

    append_status("Cleaning up any previous mount on /mnt/sdroot...")
    run_cmd(["sudo", "umount", mount_point])

    append_status("Mounting ext4 partition (sudo will prompt in terminal)...")
    code, out = run_cmd(
        [
            "sudo",
            "mount",
            "-o",
            f"loop,offset={offset}",
            img_path,
            mount_point,
        ]
    )
    if code != 0:
        raise RuntimeError(f"mount failed (exit {code}):\n{out}")

    mounted_main = True
    mounted_binds: List[Tuple[str, str]] = []

    try:
        qemu_src = "/usr/bin/qemu-aarch64-static"
        qemu_dst = os.path.join(
            mount_point,
            "usr",
            "bin",
            "qemu-aarch64-static",
        )
        if os.path.exists(qemu_src):
            append_status("Copying qemu-aarch64-static into chroot...")
            code, out = run_cmd(
                [
                    "sudo",
                    "cp",
                    qemu_src,
                    qemu_dst,
                ]
            )
            if code != 0:
                append_status(
                    "Warning: failed to copy qemu-aarch64-static:\n" + out
                )
        else:
            append_status(
                "Warning: qemu-aarch64-static not found; "
                "install qemu-user-static for ARM images."
            )

        append_status("Bind-mounting /dev, /dev/pts, /proc, /sys, /run...")
        for src, dst in bind_mounts:
            os.makedirs(dst, exist_ok=True)
            code, out = run_cmd(["sudo", "mount", "--bind", src, dst])
            if code == 0:
                mounted_binds.append((src, dst))
            else:
                append_status(
                    f"Warning: failed to bind-mount {src} -> {dst}:\n{out}"
                )

        append_status("Changing 'pi' user password inside chroot...")
        chpasswd_cmd = [
            "sudo",
            "chroot",
            mount_point,
            "/usr/sbin/chpasswd",
        ]
        proc = subprocess.run(
            chpasswd_cmd,
            input=f"pi:{new_pi_password}\n",
            text=True,
            capture_output=True,
        )
        ch_out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            raise RuntimeError(
                f"chpasswd failed (exit {proc.returncode}):\n{ch_out}"
            )

        append_status("Password for user 'pi' changed successfully.")
    finally:
        append_status("Unmounting bind mounts...")
        for _src, dst in reversed(mounted_binds):
            run_cmd(["sudo", "umount", dst])

        if mounted_main:
            append_status("Unmounting main image mount...")
            run_cmd(["sudo", "umount", mount_point])

        append_status("Cleanup complete.")


# ---------------------------------------------------------------------------
# Tkinter GUI front-end
# ---------------------------------------------------------------------------

def build_tk_gui() -> "tk.Tk":
    window = tk.Tk()
    window.title("Pi SD Image Password Helper")

    window.columnconfigure(0, weight=1)
    window.rowconfigure(0, weight=1)

    frame = ttk.Frame(window, padding=10)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.columnconfigure(1, weight=1)
    frame.rowconfigure(3, weight=1)

    ttk.Label(frame, text="SD image path:").grid(
        row=0,
        column=0,
        sticky="w",
        padx=(0, 5),
        pady=(0, 5),
    )
    entry_img = ttk.Entry(frame, textvariable=tk_img_var)
    entry_img.grid(
        row=0,
        column=1,
        sticky="ew",
        pady=(0, 5),
    )
    ttk.Button(frame, text="Browse...", command=tk_browse_image).grid(
        row=0,
        column=2,
        sticky="w",
        padx=(5, 0),
        pady=(0, 5),
    )

    ttk.Label(frame, text="New 'pi' password:").grid(
        row=1,
        column=0,
        sticky="w",
        padx=(0, 5),
        pady=(0, 5),
    )
    entry_pw = ttk.Entry(
        frame,
        textvariable=tk_password_var,
        show="*",
    )
    entry_pw.grid(
        row=1,
        column=1,
        sticky="ew",
        pady=(0, 5),
    )
    ttk.Button(frame, text="Go", command=tk_on_go).grid(
        row=1,
        column=2,
        sticky="w",
        padx=(5, 0),
        pady=(0, 5),
    )

    ttk.Label(frame, text="Status:").grid(
        row=2,
        column=0,
        sticky="nw",
        padx=(0, 5),
        pady=(10, 0),
    )
    lbl_status = ttk.Label(
        frame,
        textvariable=tk_status_var,
        anchor="nw",
        justify="left",
        relief="solid",
        padding=5,
        wraplength=520,
    )
    lbl_status.grid(
        row=2,
        column=1,
        columnspan=2,
        sticky="nsew",
        pady=(10, 0),
    )

    return window


def tk_browse_image() -> None:
    path = filedialog.askopenfilename(
        title="Select SD card image",
        filetypes=[
            ("Image files", "*.img *.dd *.bin *.raw"),
            ("All files", "*.*"),
        ],
    )
    if path:
        tk_img_var.set(path)


def tk_status_sink(msg: str) -> None:
    current = tk_status_var.get()
    if current:
        current += "\n"
    tk_status_var.set(current + msg)
    root_tk.update_idletasks()


def tk_on_go() -> None:
    tk_status_var.set("")
    img_path = tk_img_var.get().strip()
    new_pw = tk_password_var.get()

    if not img_path:
        messagebox.showerror("Error", "Please select an SD card image first.")
        return

    if not os.path.exists(img_path):
        messagebox.showerror(
            "Error",
            f"Image file does not exist:\n{img_path}",
        )
        return

    if not new_pw:
        messagebox.showerror(
            "Error",
            "Please enter a new password for user 'pi'.",
        )
        return

    append_status(f"Image: {img_path}")
    append_status("Starting password change operation...")

    try:
        change_pi_password(img_path, new_pw)
    except Exception as exc:
        messagebox.showerror("Error", f"Operation failed:\n{exc}")
        append_status(f"Error: {exc}")
        return

    messagebox.showinfo(
        "Done",
        "Password for user 'pi' changed successfully.\n\n"
        "You can now boot the Pi with this SD card and log in using "
        "the new password.",
    )


# ---------------------------------------------------------------------------
# ncurses front-end (old-school style)
# ---------------------------------------------------------------------------

def curses_input_line(
    win: "curses._CursesWindow",
    y: int,
    x: int,
    max_len: int,
    hidden: bool = False,
) -> str:
    buf: List[str] = []
    while True:
        win.move(y, x + len(buf))
        ch = win.getch()

        if ch in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            break
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
                win.move(y, x + len(buf))
                win.delch()
            continue
        if ch == curses.KEY_RESIZE:
            continue

        if 32 <= ch <= 126 and len(buf) < max_len:
            buf.append(chr(ch))
            win.addch(
                y,
                x + len(buf) - 1,
                ord("*") if hidden else ch,
            )

    return "".join(buf)


class CursesStatusSink:
    def __init__(
        self,
        win: "curses._CursesWindow",
    ) -> None:
        self.win = win
        self.row = 1

    def __call__(self, msg: str) -> None:
        max_y, max_x = self.win.getmaxyx()
        lines: List[str] = []
        current = ""
        for word in msg.split():
            if len(current) + len(word) + 1 > max_x - 2:
                lines.append(current)
                current = word
            else:
                current = (current + " " + word).strip()
        if current:
            lines.append(current)

        for line in lines:
            if self.row >= max_y - 1:
                self.win.scroll(1)
                self.row = max_y - 2
            self.win.move(self.row, 1)
            self.win.clrtoeol()
            self.win.addstr(self.row, 1, line)
            self.row += 1
        self.win.box()
        self.win.refresh()


def curses_main(stdscr: "curses._CursesWindow") -> None:
    curses.curs_set(1)
    curses.start_color()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLUE)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_CYAN)

    max_y, max_x = stdscr.getmaxyx()
    stdscr.bkgd(" ", curses.color_pair(1))
    stdscr.clear()

    title = " Pi SD Image Password Helper "
    stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
    stdscr.addstr(0, max(0, (max_x - len(title)) // 2), title)
    stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)

    bottom = " F10=Exit "
    stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
    stdscr.addstr(max_y - 1, 1, bottom)
    stdscr.addstr(max_y - 1, len(bottom) + 2, "Classic Mode")
    stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)

    form_height = 7
    form_width = max_x - 4
    form_y = 2
    form_x = 2
    form_win = curses.newwin(form_height, form_width, form_y, form_x)
    form_win.bkgd(" ", curses.color_pair(1))
    form_win.box()
    form_win.addstr(1, 2, "SD image path:")
    form_win.addstr(3, 2, "New 'pi' password:")
    form_win.refresh()

    input_x = 19
    max_input = form_width - input_x - 3
    img_path = curses_input_line(
        form_win,
        1,
        input_x,
        max_input,
        hidden=False,
    )
    pw = curses_input_line(
        form_win,
        3,
        input_x,
        max_input,
        hidden=True,
    )

    status_height = max_y - form_height - 4
    status_width = max_x - 4
    status_y = form_y + form_height + 1
    status_x = 2
    status_win = curses.newwin(
        status_height,
        status_width,
        status_y,
        status_x,
    )
    status_win.bkgd(" ", curses.color_pair(1))
    status_win.box()
    status_win.addstr(0, 2, " Status ")
    status_win.refresh()

    sink = CursesStatusSink(status_win)
    set_status_sink(sink)

    if not img_path:
        sink("No image path provided. Press any key.")
        stdscr.getch()
        return
    if not os.path.exists(img_path):
        sink(f"Image file does not exist: {img_path}")
        stdscr.getch()
        return
    if not pw:
        sink("No password provided. Press any key.")
        stdscr.getch()
        return

    sink(f"Image: {img_path}")
    sink("Starting password change operation...")

    try:
        change_pi_password(img_path, pw)
        sink("SUCCESS: 'pi' password changed.")
        sink("Press any key to exit.")
    except Exception as exc:
        sink(f"ERROR: {exc}")
        sink("Press any key to exit.")

    stdscr.getch()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if TK_AVAILABLE:
        try:
            tk_img_var = tk.StringVar()
            tk_password_var = tk.StringVar()
            tk_status_var = tk.StringVar()

            root_tk = build_tk_gui()
            set_status_sink(tk_status_sink)
            root_tk.minsize(620, 260)
            root_tk.mainloop()
            sys.exit(0)
        except Exception:
            # any Tk failure (X/Wayland/WSLg/etc) falls back to curses
            pass

    set_status_sink(lambda _msg: None)
    curses.wrapper(curses_main)
