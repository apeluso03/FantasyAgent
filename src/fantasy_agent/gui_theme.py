"""Shared look-and-feel for both desktop GUIs (gui.py, the dev build, and
gui_user.py, the production/user edition) -- one palette and one ttk style
so the two editions read as the same product and a theme tweak only needs
to happen in one place.
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

# Dark palette in the spirit of Claude's chat window, with a football accent.
BG = "#262624"
SURFACE = "#30302E"
SURFACE_ALT = "#3A3937"
BORDER = "#45443F"
TEXT = "#ECEBE4"
TEXT_MUTED = "#A8A599"
ACCENT = "#D97757"  # terracotta
ACCENT_HOVER = "#C2684A"
ACCENT_TEXT = "#20201E"  # readable foreground on top of ACCENT
FIELD_GREEN = "#3A6B35"
FIELD_GREEN_HOVER = "#4C8A45"

# Chat-bubble-specific accents (gui_user.py), kept here so both GUIs could use
# them for consistency if the dev build ever grows a similar view.
USER_BUBBLE = "#4A3A2E"  # warm brown-terracotta, distinct from assistant bubbles
ASSISTANT_BUBBLE = SURFACE_ALT
ERROR_BUBBLE = "#4A2E2E"

# User-edition-only accent palette (build_style_user / gui_user.py). Deliberately
# distinct from the dev build's terracotta so the two editions read as
# "internal tool" vs. "polished product" rather than reskins of each other;
# still grounded in the same dark BG/SURFACE/TEXT base.
CELADON = "#A1CCA5"
CELADON_HOVER = "#8FBD94"
CELADON_TEXT = "#1D2B1E"  # dark, readable foreground on top of Celadon
HUNTER_GREEN = "#415D43"
HUNTER_GREEN_HOVER = "#365038"


def resource_path(relative: str) -> Path:
    """Resolve a bundled asset both in dev mode and inside a PyInstaller build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return base / relative


def set_window_icon(root: tk.Tk) -> None:
    icon_path = resource_path("assets/icon.ico")
    if icon_path.exists():
        try:
            root.iconbitmap(default=str(icon_path))
        except tk.TclError:
            pass  # non-Windows or unsupported format -- cosmetic only


def build_style(root: tk.Tk) -> ttk.Style:
    style = ttk.Style(root)
    style.theme_use("clam")  # only fully-themable base available across platforms

    style.configure("TFrame", background=BG)
    style.configure("Surface.TFrame", background=SURFACE)
    style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 20))
    style.configure("Subtitle.TLabel", background=BG, foreground=TEXT_MUTED, font=("Segoe UI", 10))
    style.configure("Section.TLabel", background=BG, foreground=TEXT_MUTED, font=("Segoe UI Semibold", 9))
    style.configure("Status.TLabel", background=BG, foreground=TEXT_MUTED, font=("Segoe UI", 9))
    style.configure("Error.TLabel", background=BG, foreground="#E0897A", font=("Segoe UI", 9))

    style.configure(
        "TEntry",
        fieldbackground=SURFACE,
        foreground=TEXT,
        insertcolor=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        borderwidth=1,
        padding=8,
    )
    style.map("TEntry", fieldbackground=[("focus", SURFACE_ALT)])

    style.configure(
        "TCombobox",
        fieldbackground=SURFACE,
        background=SURFACE,
        foreground=TEXT,
        arrowcolor=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=6,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", SURFACE)],
        foreground=[("disabled", TEXT_MUTED)],
    )

    style.configure(
        "Ghost.TButton",
        background=SURFACE_ALT,
        foreground=TEXT,
        font=("Segoe UI", 9),
        padding=(10, 7),
        borderwidth=1,
        relief="flat",
    )
    style.map(
        "Ghost.TButton",
        background=[("active", BORDER), ("disabled", SURFACE)],
        foreground=[("disabled", TEXT_MUTED)],
    )

    style.configure(
        "Accent.TButton",
        background=ACCENT,
        foreground=ACCENT_TEXT,
        font=("Segoe UI Semibold", 10),
        padding=(16, 8),
        borderwidth=0,
        relief="flat",
    )
    style.map(
        "Accent.TButton",
        background=[("active", ACCENT_HOVER), ("disabled", SURFACE_ALT)],
        foreground=[("disabled", TEXT_MUTED)],
    )

    # Top tab bar (both editions' tabbed shells): inactive tabs sit flush with
    # the header background; the active tab gets a solid fill so it reads as
    # "selected" without needing a separate underline indicator. Colors here
    # are the dev build's own terracotta-tinted defaults -- build_style_user()
    # recolors both to Celadon/Hunter Green, structure stays identical.
    style.configure(
        "Tab.TButton",
        background=BG,
        foreground=TEXT_MUTED,
        font=("Segoe UI Semibold", 10),
        padding=(14, 9),
        borderwidth=0,
        relief="flat",
    )
    style.map("Tab.TButton", background=[("active", SURFACE_ALT)], foreground=[("active", TEXT)])

    style.configure(
        "TabActive.TButton",
        background=ACCENT,
        foreground=ACCENT_TEXT,
        font=("Segoe UI Semibold", 10),
        padding=(14, 9),
        borderwidth=0,
        relief="flat",
    )
    style.map("TabActive.TButton", background=[("active", ACCENT_HOVER)])

    # Flat, thin scrollbar with no arrow buttons -- just a trough + thumb,
    # colored to match the palette instead of the OS's default gray bar.
    style.element_create("Minimal.trough", "from", "clam", "Vertical.Scrollbar.trough")
    style.element_create("Minimal.thumb", "from", "clam", "Vertical.Scrollbar.thumb")
    style.layout(
        "Minimal.Vertical.TScrollbar",
        [
            (
                "Minimal.trough",
                {
                    "sticky": "ns",
                    "children": [("Minimal.thumb", {"expand": "1", "sticky": "nswe"})],
                },
            )
        ],
    )
    style.configure(
        "Minimal.Vertical.TScrollbar",
        troughcolor=BG,
        background=ACCENT,
        bordercolor=BG,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
        gripcount=0,
        width=8,
        relief="flat",
    )
    style.map("Minimal.Vertical.TScrollbar", background=[("active", ACCENT_HOVER)])

    return style


def build_style_user(root: tk.Tk) -> ttk.Style:
    """Same base look as build_style(), but with the user edition's Celadon/
    Hunter Green accent recolored in for buttons/tabs/scrollbars (structure --
    layouts, fonts, padding -- stays identical to the dev build's, only the
    colors differ)."""
    style = build_style(root)

    style.configure("Accent.TButton", background=CELADON, foreground=CELADON_TEXT)
    style.map(
        "Accent.TButton",
        background=[("active", CELADON_HOVER), ("disabled", SURFACE_ALT)],
        foreground=[("disabled", TEXT_MUTED)],
    )

    style.configure("TabActive.TButton", background=HUNTER_GREEN, foreground=TEXT)
    style.map("TabActive.TButton", background=[("active", HUNTER_GREEN_HOVER)])

    style.configure(
        "Minimal.Vertical.TScrollbar",
        background=HUNTER_GREEN,
        lightcolor=HUNTER_GREEN,
        darkcolor=HUNTER_GREEN,
    )
    style.map("Minimal.Vertical.TScrollbar", background=[("active", CELADON)])

    return style


def rounded_rect_points(x1: float, y1: float, x2: float, y2: float, radius: float) -> list[float]:
    """Corner points for a rounded rectangle, meant for Canvas.create_polygon
    with smooth=True (Tk's polygon spline rounds the corners for us -- this
    just keeps the straight edges straight by duplicating each corner)."""
    r = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
    return [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]


class RoundedCard(tk.Frame):
    """A rounded-corner "bubble block" container. Tkinter has no native
    rounded-rect widget, so a Canvas draws the rounded background and
    `.content` (a plain Frame sitting on top of it, inset by `padding`) is
    where callers pack/grid their real widgets.

    Two sizing modes:
    - `fill_height=False` (default, for list rows/stat cards): the card
      auto-sizes its height to whatever gets packed into `.content`; width
      follows the parent layout (pack with fill="x").
    - `fill_height=True` (for a panel that should occupy the rest of the
      window, e.g. the chat log): height instead follows whatever space the
      parent's geometry manager gives it (pack with fill="both", expand=True),
      same as a plain Frame would.
    """

    def __init__(
        self,
        parent: tk.Widget,
        *,
        bg: str,
        parent_bg: str,
        radius: int = 14,
        padding: int = 10,
        fill_height: bool = False,
    ) -> None:
        super().__init__(parent, bg=parent_bg, highlightthickness=0)
        self._bg = bg
        self._radius = radius
        self._fill_height = fill_height
        self._canvas = tk.Canvas(self, bg=parent_bg, highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)
        self.body = tk.Frame(self._canvas, bg=bg)
        self.content = tk.Frame(self.body, bg=bg)
        self.content.pack(fill="both", expand=True, padx=padding, pady=padding)
        self._window = self._canvas.create_window((0, 0), window=self.body, anchor="nw")
        if not fill_height:
            self.body.bind("<Configure>", self._sync_size)
        self._canvas.bind("<Configure>", self._sync_size)

    def refresh(self) -> None:
        """Recompute the card's height from `.content`'s current natural
        size. Needed after adding/removing content dynamically (e.g. an
        expand/collapse toggle): once `_sync_size` has pinned the canvas
        window item to an explicit height, nothing else triggers a resize on
        its own -- `.content`'s size is governed by `fill="both", expand=True`
        against that pinned area, so growing its children doesn't emit a
        `<Configure>` on anything upstream. Callers that mutate `.content`
        after initial layout must call this explicitly."""
        self.body.update_idletasks()
        self._sync_size()

    def _sync_size(self, _event: tk.Event | None = None) -> None:
        width = self._canvas.winfo_width()
        if width <= 1:
            return
        if self._fill_height:
            height = self._canvas.winfo_height()
            if height <= 1:
                return
        else:
            height = self.body.winfo_reqheight()
            self._canvas.configure(height=height)
        self._canvas.itemconfig(self._window, width=width, height=height)
        self._canvas.delete("card_bg")
        points = rounded_rect_points(1, 1, max(width - 1, 2), max(height - 1, 2), self._radius)
        self._canvas.create_polygon(points, smooth=True, fill=self._bg, outline="", tags="card_bg")
        self._canvas.tag_lower("card_bg")


def draw_yard_line(canvas: tk.Canvas) -> None:
    """Decorative separator: a horizontal line with yard-marker ticks."""
    canvas.delete("all")
    width = canvas.winfo_width()
    if width <= 1:
        return
    y = 7
    canvas.create_line(0, y, width, y, fill=BORDER, width=1)
    step = 40
    for x in range(0, width, step):
        canvas.create_line(x, y - 4, x, y + 4, fill=ACCENT, width=2)
