"""
NetPulse UI — event log panel.

Scrollable text widget showing state-transition events in reverse-chron order.
Timestamps in Consolas mono; event text in regular weight.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from db import EventRow

BG_PANEL    = "#FFFFFF"
BG          = "#F7F6F3"
FG          = "#16171A"
FG_FAINT    = "#67686D"
ACCENT      = "#A94F1C"
LINE        = "#DAD8D3"


class EventLogPanel(ttk.Frame):
    """
    Embeds a read-only Text widget showing event log entries.
    Call .append_events(events) with a list[EventRow] after each scan cycle.
    Call .clear() to reset.
    """

    def __init__(self, parent: tk.Widget, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self._build()

    def _build(self) -> None:
        label = tk.Label(
            self,
            text="EVENT LOG",
            font=("Consolas", 9, "bold"),
            bg=BG,
            fg=FG_FAINT,
            anchor="w",
            pady=4,
        )
        label.pack(fill="x", padx=8)

        vsb = ttk.Scrollbar(self, orient="vertical")
        self._text = tk.Text(
            self,
            state="disabled",
            wrap="word",
            font=("Segoe UI", 10),
            bg=BG_PANEL,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=6,
            yscrollcommand=vsb.set,
        )
        vsb.configure(command=self._text.yview)

        self._text.tag_configure("ts",   font=("Consolas", 9), foreground=FG_FAINT)
        self._text.tag_configure("down", foreground=ACCENT, font=("Segoe UI", 10, "bold"))
        self._text.tag_configure("up",   foreground="#2E7D32", font=("Segoe UI", 10, "bold"))
        self._text.tag_configure("info", foreground=FG)

        self._text.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def append_events(self, events: list[EventRow]) -> None:
        if not events:
            return
        self._text.configure(state="normal")
        for ev in events:
            ts = ev.occurred_at[:19].replace("T", " ")
            tag = "down" if "offline" in ev.event.lower() else "up"
            self._text.insert("1.0", f"  {ev.event}\n", (tag,))
            self._text.insert("1.0", f"{ts}  ", ("ts",))
        self._text.configure(state="disabled")

    def clear(self) -> None:
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")
