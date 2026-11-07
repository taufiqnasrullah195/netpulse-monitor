"""
NetPulse — main application window.

Layout (single window, no tabs):
  ┌────────────────────────────────────────────────────┐
  │  Header: title + mode badge + scan status          │
  ├─────────────────────────────────────────────┬──────┤
  │  Host table (HostTable)                     │      │
  │                                             │Detail│
  │                                             │Drawer│
  ├─────────────────────────────────────────────│      │
  │  Event log (EventLogPanel)                  │      │
  ├─────────────────────────────────────────────┴──────┤
  │  Footer: toolbar (Mode toggle, Export CSV/PDF, WoL)│
  └────────────────────────────────────────────────────┘

Threading contract:
  MonitorEngine runs in a daemon thread.
  GUI drain loop uses after() to pull EngineUpdate from gui_queue.
  No widget access from worker threads.
"""

from __future__ import annotations

import queue
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import db
import reporter
import wol
from config_loader import load as load_config
from monitor import EngineUpdate, MonitorEngine
from ui_eventlog import EventLogPanel
from ui_table import HostTable

# Editorial Light palette
BG         = "#F7F6F3"
BG_PANEL   = "#FFFFFF"
FG         = "#16171A"
FG_SOFT    = "#33343A"
FG_FAINT   = "#67686D"
ACCENT     = "#A94F1C"
ACCENT_D   = "#7E3A12"
ACCENT_S   = "#F0E2D8"
LINE       = "#DAD8D3"

DRAIN_MS   = 250   # GUI queue drain interval


class NetPulseApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self._config = load_config()
        self._engine = MonitorEngine(self._config)
        self._gui_queue: queue.Queue = queue.Queue(maxsize=64)
        self._selected_ip: Optional[str] = None

        self.title("NetPulse")
        self.minsize(900, 580)
        self.configure(bg=BG)
        self._apply_base_style()
        self._build()
        self._start_engine()
        self.after(DRAIN_MS, self._drain)

    # ------------------------------------------------------------------
    # Style
    # ------------------------------------------------------------------

    def _apply_base_style(self) -> None:
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",       background=BG)
        s.configure("Panel.TFrame", background=BG_PANEL)
        s.configure("TLabel",       background=BG, foreground=FG, font=("Segoe UI", 10))
        s.configure("Faint.TLabel", background=BG, foreground=FG_FAINT, font=("Segoe UI", 9))
        s.configure(
            "Accent.TButton",
            background=ACCENT, foreground="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            borderwidth=0, relief="flat", padding=(10, 5),
        )
        s.map("Accent.TButton",
              background=[("active", ACCENT_D), ("pressed", ACCENT_D)])
        s.configure(
            "Line.TButton",
            background=BG, foreground=ACCENT,
            font=("Segoe UI", 9),
            borderwidth=1, relief="solid", padding=(8, 4),
        )
        s.map("Line.TButton",
              background=[("active", ACCENT_S)])
        s.configure("TSeparator", background=LINE)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self._build_header()
        ttk.Separator(self, orient="horizontal").pack(fill="x")
        self._build_body()
        ttk.Separator(self, orient="horizontal").pack(fill="x")
        self._build_footer()

    def _build_header(self) -> None:
        hdr = ttk.Frame(self)
        hdr.pack(fill="x", padx=16, pady=(10, 6))

        tk.Label(
            hdr, text="NetPulse",
            font=("Georgia", 18, "bold"),
            bg=BG, fg=FG,
        ).pack(side="left")

        self._mode_badge = tk.Label(
            hdr,
            text=f"  {self._config.app.mode.upper()} MODE  ",
            font=("Consolas", 8, "bold"),
            bg=ACCENT, fg="#FFFFFF",
            padx=4, pady=2,
        )
        self._mode_badge.pack(side="left", padx=(10, 0))

        self._scan_label = tk.Label(
            hdr, text="Starting…",
            font=("Segoe UI", 9),
            bg=BG, fg=FG_FAINT,
        )
        self._scan_label.pack(side="right")

    def _build_body(self) -> None:
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=0)
        body.rowconfigure(0, weight=3)
        body.rowconfigure(1, weight=1)

        # Host table
        self._table = HostTable(body, on_select=self._on_host_select)
        self._table.grid(row=0, column=0, sticky="nsew", padx=(0, 0), pady=0)

        # Event log
        log_frame = ttk.Frame(body, style="Panel.TFrame")
        log_frame.grid(row=1, column=0, sticky="nsew")
        self._event_log = EventLogPanel(log_frame)
        self._event_log.pack(fill="both", expand=True)

        ttk.Separator(body, orient="vertical").grid(
            row=0, column=1, rowspan=2, sticky="ns", padx=1
        )

        # Detail drawer
        self._drawer = self._build_drawer(body)
        self._drawer.grid(row=0, column=2, rowspan=2, sticky="nsew", padx=(0, 0))
        body.columnconfigure(2, weight=1, minsize=220)

    def _build_drawer(self, parent: tk.Widget) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Panel.TFrame")

        tk.Label(
            frame, text="CLIENT DETAIL",
            font=("Consolas", 9, "bold"),
            bg=BG_PANEL, fg=FG_FAINT,
            anchor="w", pady=6,
        ).pack(fill="x", padx=10)

        ttk.Separator(frame, orient="horizontal").pack(fill="x")

        self._drawer_ip       = self._drawer_field(frame, "IP")
        self._drawer_hostname  = self._drawer_field(frame, "Hostname")
        self._drawer_mac       = self._drawer_field(frame, "MAC")
        self._drawer_status    = self._drawer_field(frame, "Status")
        self._drawer_latency   = self._drawer_field(frame, "Latency")
        self._drawer_since     = self._drawer_field(frame, "Since")

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=(8, 0))

        # WoL button — only enabled when host is offline and MAC is known
        self._wol_btn = ttk.Button(
            frame,
            text="Wake on LAN",
            style="Accent.TButton",
            command=self._send_wol,
            state="disabled",
        )
        self._wol_btn.pack(fill="x", padx=10, pady=(8, 4))

        tk.Label(
            frame, text="Sends magic packet to last known MAC",
            font=("Segoe UI", 8), bg=BG_PANEL, fg=FG_FAINT,
        ).pack(padx=10, anchor="w")

        return frame

    def _drawer_field(self, parent: tk.Widget, label: str) -> tk.Label:
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(
            row, text=label,
            font=("Consolas", 8), bg=BG_PANEL, fg=FG_FAINT,
            width=10, anchor="w",
        ).pack(side="left")
        value = tk.Label(
            row, text="—",
            font=("Segoe UI", 9), bg=BG_PANEL, fg=FG,
            anchor="w", wraplength=160,
        )
        value.pack(side="left", fill="x", expand=True)
        return value

    def _build_footer(self) -> None:
        footer = ttk.Frame(self)
        footer.pack(fill="x", padx=12, pady=6)

        ttk.Button(
            footer,
            text="Export CSV",
            style="Line.TButton",
            command=self._export_csv,
        ).pack(side="left", padx=(0, 6))

        ttk.Button(
            footer,
            text="Export PDF",
            style="Line.TButton",
            command=self._export_pdf,
        ).pack(side="left", padx=(0, 6))

        ttk.Button(
            footer,
            text="Toggle Demo / Live",
            style="Line.TButton",
            command=self._toggle_mode,
        ).pack(side="left", padx=(0, 6))

        self._status_bar = tk.Label(
            footer, text="",
            font=("Segoe UI", 9), bg=BG, fg=FG_FAINT,
        )
        self._status_bar.pack(side="right")

    # ------------------------------------------------------------------
    # Engine
    # ------------------------------------------------------------------

    def _start_engine(self) -> None:
        db.init_db()
        self._engine.start(
            gui_queue=self._gui_queue,
            on_alert=self._on_threshold_alert,
        )

    def _on_threshold_alert(self, ip: str, message: str) -> None:
        # Called from worker thread — schedule on main thread
        self.after(0, lambda: self._status_bar.configure(text=f"ALERT: {message}"))

    # ------------------------------------------------------------------
    # GUI drain
    # ------------------------------------------------------------------

    def _drain(self) -> None:
        try:
            while True:
                update: EngineUpdate = self._gui_queue.get_nowait()
                self._apply_update(update)
        except queue.Empty:
            pass
        self.after(DRAIN_MS, self._drain)

    def _apply_update(self, update: EngineUpdate) -> None:
        self._table.update_hosts(update.hosts)
        if update.events:
            self._event_log.append_events(update.events)
        self._scan_label.configure(
            text=f"Last scan: {update.timestamp[11:19]}"
        )
        # Refresh drawer if selected host was in this update
        if self._selected_ip:
            for s in update.hosts:
                if s.ip == self._selected_ip:
                    self._refresh_drawer(s)
                    break

    # ------------------------------------------------------------------
    # Host selection / drawer
    # ------------------------------------------------------------------

    def _on_host_select(self, ip: str) -> None:
        self._selected_ip = ip
        for s in self._engine._state.values():
            if s.ip == ip:
                self._refresh_drawer(s)
                return

    def _refresh_drawer(self, state) -> None:
        self._drawer_ip.configure(text=state.ip)
        self._drawer_hostname.configure(text=state.hostname or "—")
        self._drawer_mac.configure(text=state.mac or "—")
        self._drawer_status.configure(
            text="Online" if state.alive else "Offline",
            fg="#2E7D32" if state.alive else ACCENT,
        )
        self._drawer_latency.configure(
            text=f"{state.latency_ms} ms" if state.latency_ms else "—"
        )
        self._drawer_since.configure(
            text=state.changed_at[:19].replace("T", " ") if state.changed_at else "—"
        )
        # WoL enabled when offline AND MAC is known
        can_wake = not state.alive and bool(state.mac)
        self._wol_btn.configure(state="normal" if can_wake else "disabled")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _send_wol(self) -> None:
        if not self._selected_ip:
            return
        state = self._engine._state.get(self._selected_ip)
        if not state or not state.mac:
            messagebox.showwarning("Wake on LAN", "No MAC address known for this host.")
            return
        try:
            subnet = self._config.network.subnet
            broadcast = str(
                __import__("ipaddress").IPv4Network(subnet, strict=False).broadcast_address
            )
            wol.wake(state.mac, broadcast=broadcast)
            self._status_bar.configure(
                text=f"Magic packet sent to {state.mac} ({state.ip})"
            )
        except Exception as exc:
            messagebox.showerror("Wake on LAN", str(exc))

    def _export_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="netpulse_report.csv",
        )
        if not path:
            return
        try:
            reporter.export_csv(Path(path), days=1)
            self._status_bar.configure(text=f"CSV exported: {path}")
        except Exception as exc:
            messagebox.showerror("Export CSV", str(exc))

    def _export_pdf(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile="netpulse_report.pdf",
        )
        if not path:
            return
        try:
            reporter.export_pdf(Path(path), days=1)
            self._status_bar.configure(text=f"PDF exported: {path}")
        except Exception as exc:
            messagebox.showerror("Export PDF", str(exc))

    def _toggle_mode(self) -> None:
        current = self._config.app.mode
        self._config.app.mode = "live" if current == "demo" else "demo"
        self._mode_badge.configure(
            text=f"  {self._config.app.mode.upper()} MODE  "
        )
        self._status_bar.configure(
            text=f"Switched to {self._config.app.mode} mode — restart engine to apply"
        )

    def destroy(self) -> None:
        self._engine.stop()
        super().destroy()


def main() -> None:
    app = NetPulseApp()
    app.mainloop()


if __name__ == "__main__":
    main()
