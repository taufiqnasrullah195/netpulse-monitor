"""
NetPulse UI — host table widget.

Renders a Treeview with columns: Status, IP, Hostname, MAC, Latency, Since.
Status column shows a colored dot (via Unicode) keyed on alive state.
Rows zebra-striped using Editorial Light palette.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from monitor import HostState

# Editorial Light palette (matches taufiq-portfolio css/style.css :root)
BG          = "#F7F6F3"
BG_PANEL    = "#FFFFFF"
BG_ROW_ALT = "#F0E2D8"
FG          = "#16171A"
FG_SOFT     = "#33343A"
FG_FAINT    = "#67686D"
ACCENT      = "#A94F1C"
ACCENT_DEEP = "#7E3A12"
LINE        = "#DAD8D3"

DOT_UP   = "●"   # green
DOT_DOWN = "●"   # red
DOT_UNK  = "○"   # grey

COLUMNS = ("status", "ip", "hostname", "mac", "latency", "since")
HEADINGS = {
    "status":   "St.",
    "ip":       "IP Address",
    "hostname": "Hostname",
    "mac":      "MAC",
    "latency":  "Latency",
    "since":    "Since",
}
WIDTHS = {
    "status":   36,
    "ip":       130,
    "hostname": 160,
    "mac":      140,
    "latency":  80,
    "since":    150,
}


class HostTable(ttk.Frame):
    """
    Embeddable Treeview showing live host state.
    Call .update_hosts(states) from the GUI drain loop.
    on_select(ip) fires when the user clicks a row.
    """

    def __init__(
        self,
        parent: tk.Widget,
        on_select: Optional[Callable[[str], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(parent, **kwargs)
        self._on_select = on_select
        self._build()

    def _build(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(
            "NP.Treeview",
            background=BG_PANEL,
            fieldbackground=BG_PANEL,
            foreground=FG,
            rowheight=26,
            font=("Consolas", 10),
            borderwidth=0,
        )
        style.configure(
            "NP.Treeview.Heading",
            background=BG,
            foreground=FG_SOFT,
            font=("Consolas", 9, "bold"),
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "NP.Treeview",
            background=[("selected", ACCENT)],
            foreground=[("selected", "#FFFFFF")],
        )

        vsb = ttk.Scrollbar(self, orient="vertical")
        self._tree = ttk.Treeview(
            self,
            columns=COLUMNS,
            show="headings",
            style="NP.Treeview",
            yscrollcommand=vsb.set,
        )
        vsb.configure(command=self._tree.yview)

        for col in COLUMNS:
            self._tree.heading(col, text=HEADINGS[col], anchor="w")
            self._tree.column(
                col,
                width=WIDTHS[col],
                minwidth=WIDTHS[col],
                anchor="w",
                stretch=(col == "hostname"),
            )

        self._tree.tag_configure("up",   foreground="#2E7D32")
        self._tree.tag_configure("down", foreground=ACCENT)
        self._tree.tag_configure("alt",  background=BG_ROW_ALT)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._tree.bind("<<TreeviewSelect>>", self._on_row_select)

    def _on_row_select(self, _event: tk.Event) -> None:
        sel = self._tree.selection()
        if sel and self._on_select:
            ip = self._tree.item(sel[0], "values")[1]
            self._on_select(ip)

    def update_hosts(self, states: list[HostState]) -> None:
        existing = {self._tree.item(iid, "values")[1]: iid for iid in self._tree.get_children()}
        seen: set[str] = set()

        for idx, s in enumerate(states):
            dot = DOT_UP if s.alive else (DOT_DOWN if s.ip in existing else DOT_UNK)
            tag = "up" if s.alive else "down"
            alt_tag = "alt" if idx % 2 == 1 else ""

            latency = f"{s.latency_ms} ms" if s.latency_ms is not None else "-"
            since = s.changed_at[:19].replace("T", " ") if s.changed_at else "-"

            values = (dot, s.ip, s.hostname or "-", s.mac or "-", latency, since)

            if s.ip in existing:
                iid = existing[s.ip]
                self._tree.item(iid, values=values, tags=(tag, alt_tag))
            else:
                iid = self._tree.insert("", "end", values=values, tags=(tag, alt_tag))

            seen.add(s.ip)

        for ip, iid in existing.items():
            if ip not in seen:
                self._tree.delete(iid)
