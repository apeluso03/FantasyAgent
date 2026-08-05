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
from .gui_theme import BG, SURFACE, SURFACE_ALT, TEXT, TEXT_MUTED, RoundedCard
from .my_roster import MyRoster, get_my_roster
from .player_analysis import get_player_analysis
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
        # Expandable player-detail state (see _toggle_detail), shared by any
        # screen that passes on_click= to _player_row -- both RosterScreen and
        # BestAvailableScreen use this for their "recent stats" dropdown.
        self._cards_by_id: dict[str, RoundedCard] = {}
        self._detail_frames: dict[str, tk.Widget] = {}
        self._analysis_cache: dict[str, object] = {}
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
        on_click=None,
    ) -> RoundedCard:
        """One roster/draft-board row: circular headshot, name + position/team,
        an optional wrapped line below (e.g. best-available's reasoning), and a
        right-aligned label (rank). Returns the RoundedCard itself -- callers
        that pass `on_click` (e.g. Best Available's expandable detail) can pack
        more into `.content` below the header (the whole header becomes
        clickable and shows a chevron hinting that), then must call
        `.refresh()` on the returned card so it resizes to fit the new content.
        """
        card = RoundedCard(parent, bg=SURFACE, parent_bg=BG, radius=12, padding=10)
        card.pack(fill="x", pady=4)
        row = card.content

        header = tk.Frame(row, bg=SURFACE)
        header.pack(fill="x")

        photo = circular_headshot(image_path, initials=initials)
        self._images.append(photo)
        ttk.Label(header, image=photo, background=SURFACE).pack(side="left", padx=(0, 12), anchor="n")

        info = ttk.Frame(header, style="Surface.TFrame")
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

        if on_click:
            chevron = ttk.Label(
                header, text="▾", background=SURFACE, foreground=TEXT_MUTED, font=("Segoe UI", 10)
            )
            chevron.pack(side="right", padx=(8, 0))
        ttk.Label(
            header, text=right_text, background=SURFACE, foreground=right_color, font=("Segoe UI Semibold", 10)
        ).pack(side="right", padx=(12, 0))

        if on_click:
            def handle(_event=None, c=card) -> None:
                on_click(c)

            self._bind_click_recursive(header, handle)

        return card

    def _bind_click_recursive(self, widget: tk.Widget, handler) -> None:
        try:
            widget.configure(cursor="hand2")
        except tk.TclError:
            pass
        widget.bind("<Button-1>", handler)
        for child in widget.winfo_children():
            self._bind_click_recursive(child, handler)

    def _toggle_detail(self, player, card: RoundedCard) -> None:
        """Expand/collapse a player's "recent stats" panel below its row.
        `player` just needs `.player_id` and `.position` -- both
        BestAvailablePlayer and RosterPlayer qualify, so this one
        implementation covers both screens' dropdowns."""
        existing = self._detail_frames.pop(player.player_id, None)
        if existing is not None and existing.winfo_exists():
            existing.destroy()
            card.refresh()
            return

        detail = tk.Frame(card.content, bg=SURFACE)
        detail.pack(fill="x", pady=(10, 0))
        self._detail_frames[player.player_id] = detail
        self._cards_by_id[player.player_id] = card

        divider = tk.Frame(detail, bg=SURFACE_ALT, height=1)
        divider.pack(fill="x", pady=(0, 10))

        cached = self._analysis_cache.get(player.player_id)
        if cached is not None:
            self._render_detail(detail, cached)
            card.refresh()
            return

        ttk.Label(
            detail, text="Loading recent stats...", background=SURFACE, foreground=TEXT_MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w")
        card.refresh()
        threading.Thread(target=self._load_detail, args=(player, detail), daemon=True).start()

    def _load_detail(self, player, detail: tk.Widget) -> None:
        try:
            analysis = get_player_analysis(player.player_id, position=player.position)
            self._analysis_cache[player.player_id] = analysis
        except Exception as exc:
            self.after(0, lambda: self._render_detail_error(player.player_id, detail, str(exc)))
            return
        self.after(0, lambda: self._render_detail_and_resize(player.player_id, detail, analysis))

    def _render_detail_and_resize(self, player_id: str, detail: tk.Widget, analysis) -> None:
        self._render_detail(detail, analysis)
        card = self._cards_by_id.get(player_id)
        if card is not None:
            card.refresh()

    def _render_detail_error(self, player_id: str, detail: tk.Widget, message: str) -> None:
        if not detail.winfo_exists():
            return
        for child in detail.winfo_children():
            child.destroy()
        ttk.Label(
            detail, text=f"Couldn't load recent stats: {message}", background=SURFACE,
            foreground=TEXT_MUTED, font=("Segoe UI", 9), wraplength=560, justify="left",
        ).pack(anchor="w")
        card = self._cards_by_id.get(player_id)
        if card is not None:
            card.refresh()

    def _render_detail(self, detail: tk.Widget, analysis) -> None:
        if not detail.winfo_exists():
            return
        for child in detail.winfo_children():
            child.destroy()

        ttk.Label(
            detail, text=f"LAST {len(analysis.games) or 5} GAMES · {analysis.season} SEASON",
            background=SURFACE, foreground=TEXT_MUTED, font=("Segoe UI Semibold", 8),
        ).pack(anchor="w", pady=(0, 6))

        if not analysis.games:
            ttk.Label(
                detail, text="No recent game logs found for this player.", background=SURFACE,
                foreground=TEXT_MUTED, font=("Segoe UI", 9),
            ).pack(anchor="w", pady=(0, 8))
        else:
            games_row = tk.Frame(detail, bg=SURFACE)
            games_row.pack(fill="x", pady=(0, 10))
            for game in analysis.games:
                chip = tk.Frame(games_row, bg=SURFACE_ALT)
                chip.pack(side="left", padx=(0, 8))
                pts = f"{game.points_ppr:.1f}" if game.points_ppr is not None else "-"
                ttk.Label(
                    chip, text=f"WK {game.week}", background=SURFACE_ALT, foreground=TEXT_MUTED,
                    font=("Segoe UI", 8), padding=(10, 6, 10, 0),
                ).pack()
                ttk.Label(
                    chip, text=pts, background=SURFACE_ALT, foreground=TEXT, font=("Segoe UI Semibold", 12),
                    padding=(10, 0, 10, 2),
                ).pack()
                ttk.Label(
                    chip, text=game.stat_line, background=SURFACE_ALT, foreground=TEXT_MUTED,
                    font=("Segoe UI", 7), padding=(10, 0, 10, 6), wraplength=90, justify="center",
                ).pack()

        ttk.Label(
            detail, text=analysis.blurb, background=SURFACE, foreground=TEXT, font=("Segoe UI", 9),
            wraplength=560, justify="left",
        ).pack(anchor="w")


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
                    on_click=lambda c, p=player: self._toggle_detail(p, c),
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
            card = RoundedCard(body, bg=SURFACE, parent_bg=BG, radius=12, padding=12)
            card.pack(fill="x", pady=4)
            row = card.content

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
    """Live draft board. A search box filters by name across every available
    player (not just the default top slice); each row expands on click into a
    small analysis panel: last-5-games PPR scoring (player_analysis.py, a
    fast rule-based lookup -- no LLM call) plus a trend blurb, alongside the
    roster-fit reasoning already shown in the collapsed row."""

    DEFAULT_ROWS = 25
    SEARCH_ROWS = 25

    def __init__(self, parent: tk.Widget) -> None:
        self._all_players: list = []
        self._image_cache: dict[str, object] = {}
        self._search_var = tk.StringVar()
        super().__init__(parent, "Checking the live draft board...")

    def _load(self) -> None:
        try:
            with get_session() as session:
                # A generous limit -- cheap here, since get_best_available's only
                # per-player-network-call cost is images, fetched separately
                # (and only for whichever rows actually end up displayed).
                players = get_best_available(session, limit=300)
            # Prefetch images for the default (no-search) view here, on the
            # background thread, same as every other screen. Search-result
            # images for players outside that slice are fetched on demand in
            # _get_image -- a minor tradeoff, since typing a query is a less
            # latency-sensitive moment than the tab's initial open.
            for p in players[: self.DEFAULT_ROWS]:
                self._image_cache[p.player_id] = player_images.get_player_image_path(p.player_id)
        except Exception as exc:
            self.after(0, lambda: self._fail(str(exc)))
            return
        self._all_players = players
        self.after(0, self._render_shell)

    def _render_shell(self) -> None:
        body = self._scroll_body()
        if not self._all_players:
            ttk.Label(body, text="No available players found.", style="Status.TLabel").pack(anchor="w")
            return

        search_wrap = ttk.Frame(body, padding=(0, 0, 0, 10))
        search_wrap.pack(fill="x")
        entry = ttk.Entry(search_wrap, textvariable=self._search_var, font=("Segoe UI", 10))
        entry.pack(fill="x", ipady=4)
        ttk.Label(
            search_wrap, text="Search any available player by name (not just the top 25 shown by default).",
            style="Status.TLabel",
        ).pack(anchor="w", pady=(4, 0))
        self._search_var.trace_add("write", lambda *_args: self._apply_filter())

        self._list_holder = ttk.Frame(body)
        self._list_holder.pack(fill="both", expand=True)
        self._apply_filter()

    def _apply_filter(self) -> None:
        for child in self._list_holder.winfo_children():
            child.destroy()
        self._cards_by_id.clear()
        self._detail_frames.clear()

        query = self._search_var.get().strip().lower()
        if query:
            matches = [p for p in self._all_players if query in p.name.lower()][: self.SEARCH_ROWS]
        else:
            matches = self._all_players[: self.DEFAULT_ROWS]

        if not matches:
            ttk.Label(self._list_holder, text="No matching players found.", style="Status.TLabel").pack(
                anchor="w"
            )
            return

        for p in matches:
            image_path = self._get_image(p.player_id)
            self._player_row(
                self._list_holder,
                image_path=image_path,
                initials=(p.position or "?")[:1],
                title=p.name,
                subtitle=f"{p.position} {p.team or 'FA'}",
                right_text=f"#{p.rank_ecr}",
                right_color=TEXT_MUTED,
                extra_line=p.reasoning,
                on_click=lambda c, player=p: self._toggle_detail(player, c),
            )

    def _get_image(self, player_id: str):
        # Disk-cached by player_images itself, so this is a fast local read
        # after the first time any given player is shown -- only a genuinely
        # new player (never displayed this session) costs a network round trip.
        if player_id not in self._image_cache:
            self._image_cache[player_id] = player_images.get_player_image_path(player_id)
        return self._image_cache[player_id]
