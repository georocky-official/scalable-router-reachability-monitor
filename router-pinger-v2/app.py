# ---------------------------------------------------------
# NOTE:
# This is a demonstration version of the project.
# Certain execution components have been intentionally disabled.
# ---------------------------------------------------------
import os
import sys
import threading
import customtkinter as ctk
from tkinter import messagebox, filedialog

#from ping_cisco import router_ping as cisco_ping
from ping_juniper import router_ping as juniper_ping

# Global stop flag
stop_flag = False

# Default input Excel path (used by single mode)
DEFAULT_EXCEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input_ips.xlsx")
input_excel_path = DEFAULT_EXCEL


# ---------------------------------------------------------------------------
# File picker helpers
# ---------------------------------------------------------------------------

def browse_file(label_widget, path_holder, key="path"):
    """Open file dialog and update label + path_holder dict."""
    path = filedialog.askopenfilename(
        title="Select Input IPs Excel File",
        filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
    )
    if path:
        path = os.path.normpath(path) # normalize slashes for current OS
        path_holder[key] = path
        display = path if len(path) <= 42 else "..." + path[-39:]
        label_widget.configure(text=display)
        print(f"[Browse] Router file set to: {path}")


def browse_single_file():
    """Browse for single-mode input file."""
    global input_excel_path
    path = filedialog.askopenfilename(
        title="Select Input IPs Excel File",
        filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
    )
    if path:
        path = os.path.normpath(path) # normalize slashes for current OS
        input_excel_path = path
        display = path if len(path) <= 55 else "..." + path[-52:]
        single_file_label.configure(text=display)
        print(f"[Browse] Single file set to: {path}")


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------

def build_config(router_ip, router_type, method, username, password):
    if router_type == "cisco":
        device_type = "cisco_ios" if method == "ssh" else "cisco_ios_telnet"
    elif router_type == "juniper":
        device_type = "juniper_junos"
    else:
        raise ValueError(f"Unsupported router type: {router_type}")
    return {
        "device_type": device_type,
        "host": router_ip,
        "username": username,
        "password": password,
    }


# ---------------------------------------------------------------------------
# Single-router thread
# ---------------------------------------------------------------------------

def update_single_progress(done, total):
    single_progress_label.configure(text=f"Progress: {done}/{total}")
    single_progress_bar.set(done / total if total else 0)


def run_single_thread(config, router_type, excel_path):
    global stop_flag
    stop_flag = False
    try:
        ping_fn = cisco_ping if router_type == "cisco" else juniper_ping
        ping_fn(
            config,
            input_excel=excel_path,
            stop_flag_fn=lambda: stop_flag,
            progress_cb=update_single_progress
        )
        if not stop_flag:
            messagebox.showinfo("Done", "Ping complete. Check CSV results.")
    except Exception as e:
        if not stop_flag:
            messagebox.showerror("Error", f"Ping failed: {e}")


# ---------------------------------------------------------------------------
# Multi-router — per-router progress + thread
# ---------------------------------------------------------------------------

router_widgets = []


def make_router_progress_cb(index):
    def cb(done, total):
        try:
            w = router_widgets[index]
            w["progress_label"].configure(text=f"{done}/{total}")
            w["progress_bar"].set(done / total if total else 0)
        except Exception:
            pass
    return cb


def run_single_router_thread(ping_fn, config, excel_path, progress_cb):
    """Thread target for one router in multi mode."""
    try:
        ping_fn(
            config,
            input_excel=excel_path,
            stop_flag_fn=lambda: stop_flag, # reads global directly
            progress_cb=progress_cb,
        )
    except Exception as e:
        if not stop_flag:
            print(f"[ERROR] Router {config['host']}: {e}")
            messagebox.showerror("Error", f"Router {config['host']} failed:\n{e}")


def run_multi_thread(routers_payload):
    """
    routers_payload: list of (ping_fn, config, excel_path, progress_cb)
    Each router gets its own thread with its own excel file.
    """
    global stop_flag
    stop_flag = False

    threads = []
    for ping_fn, config, excel_path, pcb in routers_payload:
        t = threading.Thread(
            target=run_single_router_thread,
            args=(ping_fn, config, excel_path, pcb),
            daemon=True
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    if not stop_flag:
        messagebox.showinfo("Done", "All routers complete. Check CSV results.")


# ---------------------------------------------------------------------------
# Begin / Stop handlers
# ---------------------------------------------------------------------------

def run_ping():
    raise RuntimeError("Execution disabled in public version")

    if mode_var.get() == "single":
        # Validate file
        if not os.path.exists(input_excel_path):
            messagebox.showerror("Error",
                f"Input file not found:\n{input_excel_path}\n\nUse Browse to select your file.")
            return

        ip = single_ip_entry.get().strip()
        user = single_user_entry.get().strip()
        password = single_pass_entry.get().strip()
        rtype = single_type_var.get().lower()
        method = single_method_var.get().lower()

        if not ip or not user or not password:
            messagebox.showerror("Error", "Please fill in all fields.")
            return
        try:
            config = build_config(ip, rtype, method, user, password)
        except ValueError as e:
            messagebox.showerror("Error", str(e))
            return

        update_single_progress(0, 1)
        threading.Thread(
            target=run_single_thread,
            args=(config, rtype, input_excel_path),
            daemon=True
        ).start()

    else:
        # Multi mode
        if not router_widgets:
            messagebox.showerror("Error", "Add at least one router.")
            return

        routers_payload = []
        for i, w in enumerate(router_widgets):
            ip = w["ip_entry"].get().strip()
            user = w["user_entry"].get().strip()
            password = w["pass_entry"].get().strip()
            rtype = w["type_var"].get().lower()
            method = w["method_var"].get().lower()
            excel = os.path.normpath(w["excel_path"].get("path", ""))
            print(f"[MultiPing] Router #{i+1} using file: {excel}")

            if not ip or not user or not password:
                messagebox.showerror("Error", f"Router #{i+1}: please fill in all fields.")
                return
            if not excel or not os.path.exists(excel):
                messagebox.showerror("Error",
                    f"Router #{i+1}: input file not found.\nPlease use Browse to select a file.")
                return
            try:
                config = build_config(ip, rtype, method, user, password)
            except ValueError as e:
                messagebox.showerror("Error", f"Router #{i+1}: {e}")
                return

            ping_fn = cisco_ping if rtype == "cisco" else juniper_ping

            w["progress_label"].configure(text="0/0")
            w["progress_bar"].set(0)
            routers_payload.append((ping_fn, config, excel, make_router_progress_cb(i)))

        threading.Thread(
            target=run_multi_thread,
            args=(routers_payload,),
            daemon=True
        ).start()


def stop_ping():
    global stop_flag
    stop_flag = True
    messagebox.showinfo("Stopped", "Ping process interrupted.")


# ---------------------------------------------------------------------------
# Multi-router row management
# ---------------------------------------------------------------------------

def add_router_row():
    index = len(router_widgets)

    # Each row tracks its own excel path
    excel_path_holder = {"path": DEFAULT_EXCEL}

    row_frame = ctk.CTkFrame(multi_scroll_frame, fg_color="transparent")
    row_frame.pack(fill="x", padx=6, pady=4)

    # ── Row header ──
    ctk.CTkLabel(row_frame, text=f"Router #{index + 1}",
                 font=("Arial", 12, "bold")).grid(
        row=0, column=0, columnspan=6, sticky="w", padx=4, pady=(6, 2))

    # ── Router credentials ──
    ip_entry = ctk.CTkEntry(row_frame, placeholder_text="Router IP", width=130)
    ip_entry.grid(row=1, column=0, padx=4, pady=2)

    user_entry = ctk.CTkEntry(row_frame, placeholder_text="Username", width=110)
    user_entry.grid(row=1, column=1, padx=4, pady=2)

    pass_entry = ctk.CTkEntry(row_frame, placeholder_text="Password", show="*", width=110)
    pass_entry.grid(row=1, column=2, padx=4, pady=2)

    type_var = ctk.StringVar(value="juniper")
    ctk.CTkOptionMenu(row_frame, variable=type_var,
                      values=["juniper", "cisco"], width=100).grid(
        row=1, column=3, padx=4, pady=2)

    method_var = ctk.StringVar(value="ssh")
    ctk.CTkOptionMenu(row_frame, variable=method_var,
                      values=["ssh", "telnet"], width=80).grid(
        row=1, column=4, padx=4, pady=2)

    ctk.CTkButton(row_frame, text="✕", width=32, fg_color="#c0392b",
                  command=lambda f=row_frame: remove_router_row(f)).grid(
        row=1, column=5, padx=4, pady=2)

    # ── Per-router file picker ──
    file_row = ctk.CTkFrame(row_frame, fg_color="transparent")
    file_row.grid(row=2, column=0, columnspan=6, sticky="ew", padx=4, pady=(4, 2))

    ctk.CTkLabel(file_row, text="IPs File:", font=("Arial", 11)).pack(side="left", padx=(0, 4))

    file_label = ctk.CTkLabel(
        file_row,
        text="input_ips.xlsx (default)",
        font=("Arial", 10),
        text_color="gray70",
        anchor="w",
        width=300
    )
    file_label.pack(side="left", padx=4)

    ctk.CTkButton(
        file_row, text="Browse", width=70,
        command=lambda lbl=file_label, ph=excel_path_holder: browse_file(lbl, ph)
    ).pack(side="right", padx=4)

    # ── Per-router progress ──
    prog_label = ctk.CTkLabel(row_frame, text="0/0", font=("Arial", 11))
    prog_label.grid(row=3, column=0, columnspan=2, sticky="w", padx=4)

    prog_bar = ctk.CTkProgressBar(row_frame, width=340)
    prog_bar.grid(row=3, column=2, columnspan=4, padx=4, pady=(2, 6))
    prog_bar.set(0)

    # ── Separator ──
    ctk.CTkFrame(row_frame, height=1, fg_color="gray40").grid(
        row=4, column=0, columnspan=6, sticky="ew", padx=4, pady=4)

    router_widgets.append({
        "frame": row_frame,
        "ip_entry": ip_entry,
        "user_entry": user_entry,
        "pass_entry": pass_entry,
        "type_var": type_var,
        "method_var": method_var,
        "excel_path": excel_path_holder, # ← per-router file path
        "progress_label": prog_label,
        "progress_bar": prog_bar,
    })


def remove_router_row(frame):
    frame.destroy()
    for i, w in enumerate(router_widgets):
        if w["frame"] == frame:
            router_widgets.pop(i)
            break
    # Renumber
    for i, w in enumerate(router_widgets):
        for child in w["frame"].winfo_children():
            if isinstance(child, ctk.CTkLabel) and child.cget("text").startswith("Router #"):
                child.configure(text=f"Router #{i + 1}")
                break


# ---------------------------------------------------------------------------
# Mode switch
# ---------------------------------------------------------------------------

def on_mode_change(value):
    if value == "multi":
        single_frame.pack_forget()
        multi_frame.pack(fill="both", expand=True, padx=10, pady=4)
    else:
        multi_frame.pack_forget()
        single_frame.pack(fill="x", padx=10, pady=4)


# ---------------------------------------------------------------------------
# GUI Layout
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

root = ctk.CTk()
root.title("Router Pinger v2.0")
root.geometry("640x700")
root.resizable(True, True)

if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))
root.iconbitmap(os.path.join(base_path, "PING.ico"))

# ── Mode toggle ────────────────────────────────────────────────────────────
mode_var = ctk.StringVar(value="single")
ctk.CTkSegmentedButton(root, values=["single", "multi"],
                        variable=mode_var, command=on_mode_change).pack(pady=10)

# ── Single mode frame ──────────────────────────────────────────────────────
single_frame = ctk.CTkFrame(root)
single_frame.pack(fill="x", padx=10, pady=4)

ctk.CTkLabel(single_frame, text="Single Router",
             font=("Arial", 13, "bold")).pack(pady=(8, 4))

single_ip_entry = ctk.CTkEntry(single_frame, placeholder_text="Router IP", width=260)
single_ip_entry.pack(pady=5)

single_type_var = ctk.StringVar(value="cisco")
ctk.CTkOptionMenu(single_frame, variable=single_type_var,
                  values=["cisco", "juniper"], width=260).pack(pady=5)

single_method_var = ctk.StringVar(value="ssh")
ctk.CTkOptionMenu(single_frame, variable=single_method_var,
                  values=["ssh", "telnet"], width=260).pack(pady=5)

single_user_entry = ctk.CTkEntry(single_frame, placeholder_text="Username", width=260)
single_user_entry.pack(pady=5)

single_pass_entry = ctk.CTkEntry(single_frame, placeholder_text="Password",
                                  show="*", width=260)
single_pass_entry.pack(pady=5)

# Single file picker
single_file_frame = ctk.CTkFrame(single_frame, fg_color="transparent")
single_file_frame.pack(fill="x", padx=20, pady=4)

ctk.CTkLabel(single_file_frame, text="IPs File:", font=("Arial", 12)).pack(side="left", padx=(0, 4))

default_display = DEFAULT_EXCEL if len(DEFAULT_EXCEL) <= 42 else "..." + DEFAULT_EXCEL[-39:]
single_file_label = ctk.CTkLabel(single_file_frame, text=default_display,
                                  font=("Arial", 11), text_color="gray70",
                                  anchor="w", width=300)
single_file_label.pack(side="left", padx=4)

ctk.CTkButton(single_file_frame, text="Browse",
              command=browse_single_file, width=80).pack(side="right", padx=4)

# Single progress
single_progress_label = ctk.CTkLabel(single_frame, text="Progress: 0/0")
single_progress_label.pack(pady=3)

single_progress_bar = ctk.CTkProgressBar(single_frame, width=300)
single_progress_bar.pack(pady=3)
single_progress_bar.set(0)

# ── Multi mode frame ───────────────────────────────────────────────────────
multi_frame = ctk.CTkFrame(root)

ctk.CTkLabel(multi_frame, text="Multiple Routers",
             font=("Arial", 13, "bold")).pack(pady=(8, 4))

ctk.CTkButton(multi_frame, text="＋ Add Router",
              command=add_router_row, width=160).pack(pady=4)

multi_scroll_frame = ctk.CTkScrollableFrame(multi_frame, height=400)
multi_scroll_frame.pack(fill="both", expand=True, padx=6, pady=4)

# ── Action buttons ─────────────────────────────────────────────────────────
btn_frame = ctk.CTkFrame(root)
btn_frame.pack(pady=10)

ctk.CTkButton(btn_frame, text="▶ Begin Ping",
              command=run_ping, width=140).grid(row=0, column=0, padx=12)
ctk.CTkButton(btn_frame, text="■ Stop Ping",
              command=stop_ping, fg_color="#c0392b", width=140).grid(row=0, column=1, padx=12)

# ── Footer ─────────────────────────────────────────────────────────────────

def show_instructions():
    messagebox.showinfo("Instructions",
        "📘 Router Pinger v2.0\n\n"
        "── SINGLE MODE ──\n"
        "Fill in Router IP, Type, Method, Username, Password.\n"
        "Use Browse to pick your destination IPs Excel file.\n"
        "Click Begin Ping.\n\n"
        "── MULTI MODE ──\n"
        "Click '＋ Add Router' for each router.\n"
        "Fill in credentials for each row.\n"
        "Each router has its own Browse button —\n"
        " different routers can use different IP files.\n"
        "All routers ping simultaneously.\n"
        "Each router shows its own live progress bar.\n"
        "Click ✕ to remove a router row.\n\n"
        "── BOTH MODES ──\n"
        "• Results saved live — safe to stop anytime.\n"
        "• Unknown/Error IPs are automatically retried.\n"
        "• Each router saves its own timestamped CSV.\n"
    )

footer = ctk.CTkFrame(root)
footer.pack(side="bottom", fill="x")
ctk.CTkButton(footer, text="Instructions",
              command=show_instructions).pack(pady=3, expand=True)
ctk.CTkLabel(footer, text="Router Pinger v2.0 ™",
             font=("Arial", 10)).pack(pady=3)

# Entry point intentionally disabled for public version
# root.mainloop()
