"""Read-only data screens (My Roster / Power Rankings / Best Available) used
as tabs in both GUI editions. Each screen takes an `accent` color for its
"this is you" / "this position is a strength" highlights, so gui.py
(terracotta) and gui_user.py (Celadon) can share the exact same widgets
while keeping their own accent color -- see gui_theme.build_style() vs.
build_style_user() for the matching ttk style split.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from . import player_images
from .config import settings
from .db.session import get_session
from .draft import get_best_available
from .gui_theme import BG, SURFACE, SURFACE_ALT, TEXT, TEXT_MUTED
from .my_roster import MyRoster, get_my_roster
from .power_rankings import compute_power_rankings
from .roster_analysis import STANDARD_POSITIONS


def circular_headshot(path, size: int = 40, initials: str = "?") -> ImageTk.PhotoImage:
    """A circular player photo, or a circular initial-letter placeholder if
    Sleeper has no photo for this player (or the fetch failed)."""
    image = None
    if path is not None:
        try:
            source = Image.open(path).convert("RGB")
            # Sleeper's headshots aren't square (they're a tighter portrait
            # crop) -- resizing straight to (size, size) stretches faces
            # sideways. Scale so the shorter side fits, then center-crop to a
            # square instead, so the resulting circle isn't distorted.
            scale = size / min(source.size)
            scaled = source.resize(
                (max(1, round(source.width * scale)), max(1, round(source.height * scale))), Image.LANCZOS
            )
            left = (scaled.width - size) // 2
            top = (scaled.height - size) // 2
            image = scaled.crop((left, top, left + size, top + size))
        except OSError:
            image = None
    if image is None:
        image = Image.new("RGB", (size, size), SURFACE_ALT)
        draw = ImageDraw.Draw(image)
        draw.text((size // 2, size // 2), initials, fill=TEXT_MUTED, anchor="mm")

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    rgba = image.convert("RGBA")
    rgba.putalpha(mask)
    return ImageTk.PhotoImage(rgba)


class ScrollableFrame(ttk.Frame):
    """A vertically scrollable content area (plain ttk.Frame can't scroll on
    its own) using the minimal flat scrollbar style. `.body` is where callers
    should pack their rows."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self._canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        vbar = ttk.Scrollbar(
            self, orient="vertical", command=self._canvas.yview, style="Minimal.Vertical.TScrollbar"
        )
        self.body = ttk.Frame(self._canvas)
        self._window = self._canvas.create_window((0, 0), window=self.body, anchor="nw")
        self._canvas.configure(yscrollcommand=vbar.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")

        self.body.bind("<Configure>", lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(self._window, width=e.width))
        self._canvas.bind("<Enter>", lambda _e: self._canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self._canvas.bind("<Leave>", lambda _e: self._canvas.unbind_all("<MouseWheel>"))

    def _on_mousewheel(self, event: tk.Event) -> None:
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class _LoadingScreen(ttk.Frame):
    """Shared skeleton for the three data tabs: a status line, then a
    background-thread load that either renders rows into a ScrollableFrame
    or shows an error in the status line."""

    def __init__(self, parent: tk.Widget, loading_message: str) -> None:
        super().__init__(parent, padding=(18, 8, 18, 12))
        self.pack(fill="both", expand=True)
        self._images: list[ImageTk.PhotoImage] = []  # keep refs alive -- Tk drops unreferenced PhotoImages
        self._status = tk.StringVar(value=loading_message)
        ttk.Label(self, textvariable=self._status, style="Status.TLabel").pack(anchor="w", pady=(0, 8))
        self._body_holder = ttk.Frame(self)
        self._body_holder.pack(fill="both", expand=True)
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        raise NotImplementedError

    def _fail(self, message: str) -> None:
        self._status.set(message)

    def _scroll_body(self) -> ttk.Frame:
        self._status.set("")
        scroll = ScrollableFrame(self._body_holder)
        scroll.pack(fill="both", expand=True)
        return scroll.body

    def _player_row(
        self,
        parent: tk.Widget,
        *,
        image_path,
        initials: str,
        title: str,
        subtitle: str,
        right_text: str,
        right_color: str,
        extra_line: str | None = None,
    ) -> None:
        """One roster/draft-board row: circular headshot, name + position/team,
        an optional wrapped line below (e.g. best-available's reasoning), and a
        right-aligned label (rank)."""
        row = ttk.Frame(parent, style="Surface.TFrame", padding=10)
        row.pack(fill="x", pady=3)

        photo = circular_headshot(image_path, initials=initials)
        self._images.append(photo)
        ttk.Label(row, image=photo, background=SURFACE).pack(side="left", padx=(0, 12), anchor="n")

        info = ttk.Frame(row, style="Surface.TFrame")
        info.pack(side="left", fill="x", expand=True)
        ttk.Label(
            info, text=title, background=SURFACE, foreground=TEXT, font=("Segoe UI Semibold", 10)
        ).pack(anchor="w")
        ttk.Label(info, text=subtitle, background=SURFACE, foreground=TEXT_MUTED, font=("Segoe UI", 9)).pack(
            anchor="w"
        )
        if extra_line:
            ttk.Label(
                info, text=extra_line, background=SURFACE, foreground=TEXT_MUTED, font=("Segoe UI", 9),
                wraplength=560, justify="left",
            ).pack(anchor="w", pady=(4, 0))

        ttk.Label(
            row, text=right_text, background=SURFACE, foreground=right_color, font=("Segoe UI Semibold", 10)
        ).pack(side="right", padx=(12, 0))


class RosterScreen(_LoadingScreen):
    def __init__(self, parent: tk.Widget, accent: str = TEXT) -> None:
        self._accent = accent
        super().__init__(parent, "Loading your roster...")

    def _load(self) -> None:
        try:
            with get_session() as session:
                roster = get_my_roster(session)
            images = {p.player_id: player_images.get_player_image_path(p.player_id) for p in roster.players}
        except Exception as exc:
            self.after(0, lambda: self._fail(f"Couldn't load your roster: {exc}"))
            return
        self.after(0, lambda: self._render(roster, images))

    def _render(self, roster: MyRoster, images: dict) -> None:
        body = self._scroll_body()
        ttk.Label(body, text=roster.team_name, style="Title.TLabel").pack(anchor="w", pady=(0, 10))

        groups = [
            ("STARTERS", "starter"),
            ("BENCH", "bench"),
            ("INJURED RESERVE", "ir"),
            ("TAXI SQUAD", "taxi"),
        ]
        any_rows = False
        for label, key in groups:
            rows = [p for p in roster.players if p.group == key]
            if not rows:
                continue
            any_rows = True
            ttk.Label(body, text=label, style="Section.TLabel").pack(anchor="w", pady=(6, 6))
            for player in rows:
                rank_text = f"#{player.rank_ecr}" if player.rank_ecr is not None else "unranked"
                self._player_row(
                    body,
                    image_path=images.get(player.player_id),
                    initials=(player.position or "?")[:1],
                    title=player.name,
                    subtitle=f"{player.position or '-'} · {player.team or 'FA'}",
                    right_text=rank_text,
                    right_color=self._accent,
                )
        if not any_rows:
            ttk.Label(body, text="No players on your roster yet.", style="Status.TLabel").pack(anchor="w")


class PowerRankingsScreen(_LoadingScreen):
    def __init__(self, parent: tk.Widget, accent: str = TEXT) -> None:
        self._accent = accent
        super().__init__(parent, "Loading power rankings...")

    def _load(self) -> None:
        try:
            with get_session() as session:
                teams = compute_power_rankings(session)
        except Exception as exc:
            self.after(0, lambda: self._fail(str(exc)))
            return
        self.after(0, lambda: self._render(teams))

    def _render(self, teams: list) -> None:
        body = self._scroll_body()
        my_owner = settings.sleeper_owner_user_id
        strong_cutoff = max(1, len(teams) // 3) if teams else 1

        for team in teams:
            is_me = team.owner_user_id == my_owner
            row = ttk.Frame(body, style="Surface.TFrame", padding=12)
            row.pack(fill="x", pady=3)

            name = f"{team.rank}. {team.team_name}" + ("  (you)" if is_me else "")
            ttk.Label(
                row, text=name, background=SURFACE, foreground=(self._accent if is_me else TEXT),
                font=("Segoe UI Semibold", 11),
            ).pack(anchor="w")

            badges = ttk.Frame(row, style="Surface.TFrame")
            badges.pack(anchor="w", pady=(6, 0))
            for pos in STANDARD_POSITIONS:
                rank = team.positional_rank.get(pos)
                strong = rank is not None and rank <= strong_cutoff
                ttk.Label(
                    badges, text=f"{pos} #{rank}", background=SURFACE_ALT,
                    foreground=(self._accent if strong else TEXT_MUTED), font=("Segoe UI", 9), padding=(8, 3),
                ).pack(side="left", padx=(0, 6))


class BestAvailableScreen(_LoadingScreen):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, "Checking the live draft board...")

    def _load(self) -> None:
        try:
            with get_session() as session:
                players = get_best_available(session, limit=25)
            images = {p.player_id: player_images.get_player_image_path(p.player_id) for p in players}
        except Exception as exc:
            self.after(0, lambda: self._fail(str(exc)))
            return
        self.after(0, lambda: self._render(players, images))

    def _render(self, players: list, images: dict) -> None:
        body = self._scroll_body()
        if not players:
            ttk.Label(body, text="No available players found.", style="Status.TLabel").pack(anchor="w")
            return

        for p in players:
            self._player_row(
                body,
                image_path=images.get(p.player_id),
                initials=(p.position or "?")[:1],
                title=p.name,
                subtitle=f"{p.position} {p.team or 'FA'}",
                right_text=f"#{p.rank_ecr}",
                right_color=TEXT_MUTED,
                extra_line=p.reasoning,
            )
