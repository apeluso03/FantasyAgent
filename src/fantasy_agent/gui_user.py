"""Production/user-edition desktop app: a chat-and-dashboard interface with
no visible tool-call trace, meant for someone other than the developer to
run. See gui.py for the dev build this is paired with -- from here on, GUI
changes should land in both.

Startup flow: if no saved config exists yet (user_config.py, stored outside
the repo in the OS's per-user app-data dir), show a setup wizard collecting
league platform + ID + OpenAI key before anything else can run; otherwise
load the saved config and go straight to the tabbed main shell (Chat / My
Roster / Power Rankings / Best Available).
"""

from __future__ import annotations

import re
import threading
import tkinter as tk
from tkinter import ttk

from . import user_config
from .db.session import get_session
from .gui_screens import BestAvailableScreen, PowerRankingsScreen, RosterScreen
from .gui_theme import (
    BG,
    BORDER,
    CELADON,
    CELADON_TEXT,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    TEXT_MUTED,
    RoundedCard,
    build_style_user,
    draw_yard_line,
    rounded_rect_points,
    set_window_icon,
)
from .sleeper.client import SleeperAPIError, SleeperClient

EXAMPLE_PROMPTS = [
    "Who should I keep this season?",
    "Rank the league by team strength",
    "Is trading my WR2 for their RB2 a fair deal?",
    "Who's the best available RB right now?",
]

TABS = [
    ("chat", "\U0001F4AC", "Chat"),
    ("roster", "\U0001F3C8", "My Roster"),
    ("rankings", "\U0001F4CA", "Power Rankings"),
    ("available", "\U0001F50D", "Best Available"),
]

TAB_META = {
    "chat": ("Chat", "Ask me anything about your league."),
    "roster": ("My Roster", "Your current lineup, ordered like a real roster card."),
    "rankings": ("Power Rankings", "Every team ranked by starting lineup strength."),
    "available": ("Best Available", "Live draft board, polled fresh from Sleeper."),
}

_BOLD_RE = re.compile(r"(\*\*[^*]+?\*\*)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)")


def _insert_markdown_lite(widget: tk.Text, text: str, base_tag: str) -> None:
    """Very small markdown renderer: **bold**, "- " bullets, and "#" headings.
    Good enough for the model's actual output style (we've seen it use all
    three) without pulling in a real markdown/HTML rendering dependency.
    """
    for i, line in enumerate(text.split("\n")):
        if i > 0:
            widget.insert("end", "\n", (base_tag,))

        heading = _HEADING_RE.match(line)
        if heading:
            widget.insert("end", heading.group(2), (base_tag, "heading"))
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            widget.insert("end", "  •  ", (base_tag,))
            line = bullet.group(1)

        for chunk in _BOLD_RE.split(line):
            if not chunk:
                continue
            if chunk.startswith("**") and chunk.endswith("**"):
                widget.insert("end", chunk[2:-2], (base_tag, "bold"))
            else:
                widget.insert("end", chunk, (base_tag,))


class ChatLog(tk.Frame):
    """The scrollable message list, wrapped in a rounded card so the panel
    itself reads as one of the app's "bubble block" containers. Individual
    messages are still tagged paragraphs inside a single Text widget --
    Tkinter can't give a background that hugs just the text (it always spans
    the paragraph's full margin-to-margin width), so those read as
    chat-style highlighted blocks rather than literal rounded bubbles,
    differentiated by side/color and a sender label.
    """

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bg=BG)
        card = RoundedCard(self, bg=SURFACE, parent_bg=BG, radius=16, padding=1, fill_height=True)
        card.pack(fill="both", expand=True)
        self._text = tk.Text(
            card.content,
            wrap="word",
            state="disabled",
            font=("Segoe UI", 10),
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground=CELADON,
            selectforeground=CELADON_TEXT,
            relief="flat",
            borderwidth=0,
            padx=8,
            pady=12,
            spacing1=2,
        )
        vbar = ttk.Scrollbar(
            card.content, orient="vertical", command=self._text.yview, style="Minimal.Vertical.TScrollbar"
        )
        self._text.configure(yscrollcommand=vbar.set)
        self._text.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")

        from .gui_theme import ASSISTANT_BUBBLE, ERROR_BUBBLE, USER_BUBBLE

        self._text.tag_configure(
            "user", background=USER_BUBBLE, foreground=TEXT, justify="right",
            lmargin1=90, lmargin2=90, rmargin=14, spacing1=6, spacing3=14,
        )
        self._text.tag_configure(
            "assistant", background=ASSISTANT_BUBBLE, foreground=TEXT, justify="left",
            lmargin1=14, lmargin2=14, rmargin=90, spacing1=6, spacing3=14,
        )
        self._text.tag_configure(
            "error", background=ERROR_BUBBLE, foreground=TEXT, justify="left",
            lmargin1=14, lmargin2=14, rmargin=90, spacing1=6, spacing3=14,
        )
        self._text.tag_configure(
            "sender_user", foreground=TEXT_MUTED, justify="right", font=("Segoe UI", 8),
            lmargin1=90, rmargin=14, spacing3=2,
        )
        self._text.tag_configure(
            "sender_assistant", foreground=TEXT_MUTED, justify="left", font=("Segoe UI", 8),
            lmargin1=14, spacing3=2,
        )
        self._text.tag_configure("bold", font=("Segoe UI Semibold", 10))
        self._text.tag_configure("heading", font=("Segoe UI Semibold", 12))

        self._typing_range: tuple[str, str] | None = None

    def add_message(self, role: str, text: str) -> None:
        self._text.configure(state="normal")
        sender_tag = f"sender_{role}" if role in ("user", "assistant") else None
        if sender_tag:
            label = "You" if role == "user" else "Fantasy Agent"
            self._text.insert("end", label + "\n", (sender_tag,))
        _insert_markdown_lite(self._text, text, role)
        self._text.insert("end", "\n")
        self._text.configure(state="disabled")
        self._text.see("end")

    def show_typing(self) -> None:
        self._text.configure(state="normal")
        start = self._text.index("end-1c")
        self._text.insert("end", "Fantasy Agent\n", ("sender_assistant",))
        self._text.insert("end", "thinking...", ("assistant", "typing"))
        self._text.insert("end", "\n")
        end = self._text.index("end-1c")
        self._text.configure(state="disabled")
        self._text.see("end")
        self._typing_range = (start, end)

    def hide_typing(self) -> None:
        if self._typing_range is None:
            return
        start, end = self._typing_range
        self._text.configure(state="normal")
        self._text.delete(start, end)
        self._text.configure(state="disabled")
        self._typing_range = None


class SetupScreen(ttk.Frame):
    def __init__(self, parent: tk.Widget, on_complete, prefill: user_config.UserConfig | None = None) -> None:
        super().__init__(parent, padding=28)
        self.pack(fill="both", expand=True)
        self._on_complete = on_complete
        self._build(prefill)

    def _build(self, prefill: user_config.UserConfig | None) -> None:
        ttk.Label(self, text="\U0001F3C8 Fantasy Agent", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self, text="Connect your league to get started.", style="Subtitle.TLabel"
        ).pack(anchor="w", pady=(0, 4))

        yard_line = tk.Canvas(self, height=14, bg=BG, highlightthickness=0)
        yard_line.pack(fill="x", pady=(4, 20))
        yard_line.bind("<Configure>", lambda _e: draw_yard_line(yard_line))

        ttk.Label(self, text="FANTASY PLATFORM", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        self._platform = tk.StringVar(value=(prefill.platform if prefill else "sleeper"))
        platform_row = ttk.Frame(self)
        platform_row.pack(fill="x", pady=(0, 18))
        for label, value, enabled in (
            ("Sleeper", "sleeper", True),
            ("ESPN (coming soon)", "espn", False),
            ("Yahoo (coming soon)", "yahoo", False),
        ):
            rb = ttk.Radiobutton(platform_row, text=label, value=value, variable=self._platform)
            if not enabled:
                rb.state(["disabled"])
            rb.pack(side="left", padx=(0, 18))

        self._league_id = self._labeled_entry(
            "LEAGUE ID",
            prefill.league_id if prefill else "",
            hint="Find this in your league's Sleeper URL, e.g. sleeper.com/leagues/123456789/team",
        )
        self._username = self._labeled_entry(
            "YOUR SLEEPER USERNAME",
            prefill.sleeper_username if prefill else "",
            hint="Used to figure out which roster in the league is yours.",
        )

        ttk.Label(self, text="OPENAI API KEY", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        key_row = ttk.Frame(self)
        key_row.pack(fill="x")
        self._api_key = tk.StringVar(value=(prefill.openai_api_key if prefill else ""))
        self._key_entry = ttk.Entry(key_row, textvariable=self._api_key, font=("Segoe UI", 10), show="*")
        self._key_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self._key_visible = False
        self._show_btn = ttk.Button(key_row, text="Show", style="Ghost.TButton", command=self._toggle_key)
        self._show_btn.pack(side="left", padx=(8, 0))
        ttk.Label(
            self, text="Get one at platform.openai.com/api-keys -- stored only on this computer.",
            style="Status.TLabel",
        ).pack(anchor="w", pady=(2, 20))

        self._error = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._error, style="Error.TLabel", wraplength=520).pack(
            anchor="w", pady=(0, 8)
        )

        button_row = ttk.Frame(self)
        button_row.pack(anchor="w")
        self._submit_btn = ttk.Button(
            button_row,
            text=("Save Changes" if prefill else "Get Started") + " \U0001F3C8",
            style="Accent.TButton",
            command=self._submit,
        )
        self._submit_btn.pack(side="left")
        self._status = tk.StringVar(value="")
        ttk.Label(button_row, textvariable=self._status, style="Status.TLabel").pack(
            side="left", padx=(12, 0)
        )

    def _labeled_entry(self, label: str, initial: str, hint: str) -> tk.StringVar:
        ttk.Label(self, text=label, style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        var = tk.StringVar(value=initial)
        ttk.Entry(self, textvariable=var, font=("Segoe UI", 10)).pack(fill="x", ipady=4)
        ttk.Label(self, text=hint, style="Status.TLabel").pack(anchor="w", pady=(2, 16))
        return var

    def _toggle_key(self) -> None:
        self._key_visible = not self._key_visible
        self._key_entry.configure(show="" if self._key_visible else "*")
        self._show_btn.configure(text="Hide" if self._key_visible else "Show")

    def _submit(self) -> None:
        platform = self._platform.get()
        league_id = self._league_id.get().strip()
        username = self._username.get().strip()
        api_key = self._api_key.get().strip()

        if platform != "sleeper":
            self._error.set(f"{platform.title()} support is coming soon -- Sleeper works today.")
            return
        if not league_id:
            self._error.set("League ID is required.")
            return
        if not username:
            self._error.set("Your Sleeper username is required.")
            return
        if not api_key:
            self._error.set("An OpenAI API key is required to use the chat.")
            return

        self._error.set("")
        self._submit_btn.state(["disabled"])
        self._status.set("Connecting to Sleeper...")
        threading.Thread(
            target=self._do_setup, args=(platform, league_id, username, api_key), daemon=True
        ).start()

    def _do_setup(self, platform: str, league_id: str, username: str, api_key: str) -> None:
        try:
            with SleeperClient() as client:
                user = client.get_user(username)
                client.get_league(league_id)  # raises if the league ID doesn't exist

            config = user_config.UserConfig(
                platform=platform,
                league_id=league_id,
                openai_api_key=api_key,
                sleeper_username=username,
                sleeper_owner_user_id=user.user_id,
            )
            user_config.save_user_config(config)
            user_config.apply_user_config(config)

            self.after(0, lambda: self._status.set("Syncing your league..."))
            from .sync import sync_all, sync_rankings_all

            sync_all(league_id)
            self.after(0, lambda: self._status.set("Fetching player rankings..."))
            sync_rankings_all()

            self.after(0, lambda: self._on_complete(config))
        except SleeperAPIError as exc:
            self.after(0, lambda: self._fail(str(exc)))
        except Exception as exc:  # network hiccups, bad key format, etc. -- never crash the wizard
            self.after(0, lambda: self._fail(f"Setup failed: {exc}"))

    def _fail(self, message: str) -> None:
        self._error.set(message)
        self._status.set("")
        self._submit_btn.state(["!disabled"])


class ChatScreen(ttk.Frame):
    """Chat tab content. The app-level title/settings live in MainShell now,
    so this is just the log + input row."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self.pack(fill="both", expand=True)
        self._running = False
        self._build()
        self._seed_welcome()

    def _build(self) -> None:
        self._chat_log = ChatLog(self)
        self._chat_log.pack(fill="both", expand=True, padx=18, pady=(8, 6))

        input_row = ttk.Frame(self, padding=(18, 0, 18, 16))
        input_row.pack(fill="x")
        self._question = tk.StringVar()
        entry = ttk.Entry(input_row, textvariable=self._question, font=("Segoe UI", 10))
        entry.pack(side="left", fill="x", expand=True, ipady=6)
        entry.bind("<Return>", lambda _e: self._send())
        self._entry = entry
        self._send_btn = ttk.Button(input_row, text="Send \U0001F3C8", style="Accent.TButton", command=self._send)
        self._send_btn.pack(side="left", padx=(8, 0))
        entry.focus_set()

    def _seed_welcome(self) -> None:
        bullets = "\n".join(f"- {p}" for p in EXAMPLE_PROMPTS)
        self._chat_log.add_message(
            "assistant",
            f"Welcome! I'm your fantasy football assistant. Try asking things like:\n{bullets}",
        )

    def _send(self) -> None:
        if self._running:
            return
        question = self._question.get().strip()
        if not question:
            return
        self._question.set("")
        self._chat_log.add_message("user", question)
        self._running = True
        self._send_btn.state(["disabled"])
        self._chat_log.show_typing()
        threading.Thread(target=self._ask, args=(question,), daemon=True).start()

    def _ask(self, question: str) -> None:
        # Imported lazily: run_agent pulls in the openai SDK, which the setup
        # wizard's own code path never needs to touch.
        from .agent.core import run_agent

        try:
            with get_session() as session:
                answer = run_agent(question, session)
        except Exception as exc:  # API errors, network issues -- never crash the chat
            self.after(0, lambda: self._finish("error", f"Something went wrong: {exc}"))
            return
        self.after(0, lambda: self._finish("assistant", answer))

    def _finish(self, role: str, text: str) -> None:
        self._chat_log.hide_typing()
        self._chat_log.add_message(role, text)
        self._running = False
        self._send_btn.state(["!disabled"])
        self._entry.focus_set()


class _SidebarItem(tk.Canvas):
    """One sidebar nav row. Drawn entirely on a single Canvas (rounded pill
    background + label, both canvas items) rather than a Label sitting on
    top of one -- that would need pixel-perfect alignment between the two to
    avoid the label's square corners covering the pill's rounded ones; one
    canvas drawing both atomically sidesteps that."""

    def __init__(self, parent: tk.Widget, *, icon: str, label: str, sidebar_bg: str, on_click) -> None:
        super().__init__(parent, bg=sidebar_bg, highlightthickness=0, height=40)
        self._sidebar_bg = sidebar_bg
        self._icon = icon
        self._label = label
        self._active = False
        self._hover = False
        self._accent = TEXT_MUTED
        self._accent_text = TEXT
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Button-1>", lambda _e: on_click())
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))

    def set_active(self, active: bool, accent: str, accent_text: str) -> None:
        self._active = active
        self._accent = accent
        self._accent_text = accent_text
        self._redraw()

    def _set_hover(self, hovering: bool) -> None:
        self._hover = hovering
        self._redraw()

    def _redraw(self) -> None:
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1:
            return
        self.delete("all")
        if self._active:
            points = rounded_rect_points(10, 4, width - 10, height - 4, 10)
            self.create_polygon(points, smooth=True, fill=self._accent, outline="")
            fg = self._accent_text
        elif self._hover:
            points = rounded_rect_points(10, 4, width - 10, height - 4, 10)
            self.create_polygon(points, smooth=True, fill=SURFACE_ALT, outline="")
            fg = TEXT
        else:
            fg = TEXT_MUTED
        # Two separate text items, not one combined string: Canvas text doesn't
        # do font-fallback the way a Label does, so a color-emoji glyph next to
        # plain Latin text in a single font spec renders the emoji as a "tofu"
        # box -- explicitly using an emoji-capable font for just the icon fixes it.
        self.create_text(24, height // 2, text=self._icon, anchor="w", fill=fg, font=("Segoe UI Emoji", 11))
        self.create_text(48, height // 2, text=self._label, anchor="w", fill=fg, font=("Segoe UI Semibold", 10))
        self.configure(cursor="hand2")


class Sidebar(tk.Frame):
    """Persistent left nav: logo, tab items (active one gets a rounded pill
    highlight), and a footer with the connected league + a Settings button."""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        tabs: list[tuple[str, str, str]],
        on_select,
        accent: str,
        accent_text: str,
        footer_text: str,
        on_settings,
    ) -> None:
        super().__init__(parent, bg=BG, width=210)
        self.pack_propagate(False)
        self._accent = accent
        self._accent_text = accent_text
        self._items: dict[str, _SidebarItem] = {}
        self._on_select = on_select

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=18, pady=(22, 18))
        tk.Label(
            header, text="\U0001F3C8 Fantasy Agent", bg=BG, fg=TEXT, font=("Segoe UI Semibold", 13)
        ).pack(anchor="w")

        nav = tk.Frame(self, bg=BG)
        nav.pack(fill="x", padx=8)
        for key, icon, label in tabs:
            item = _SidebarItem(
                nav, icon=icon, label=label, sidebar_bg=BG, on_click=lambda k=key: self._on_select(k)
            )
            item.pack(fill="x", pady=2)
            self._items[key] = item

        tk.Frame(self, bg=BG).pack(fill="both", expand=True)  # spacer pushes the footer down

        divider = tk.Frame(self, bg=BORDER, height=1)
        divider.pack(fill="x", padx=18)
        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", padx=18, pady=16)
        tk.Label(
            footer, text=footer_text, bg=BG, fg=TEXT_MUTED, font=("Segoe UI", 9),
            wraplength=170, justify="left",
        ).pack(anchor="w", pady=(10, 10))
        ttk.Button(footer, text="⚙ Settings", style="Ghost.TButton", command=on_settings).pack(fill="x")

    def set_active(self, key: str) -> None:
        for item_key, item in self._items.items():
            item.set_active(item_key == key, self._accent, self._accent_text)


class MainShell(ttk.Frame):
    """Hub shown once setup is complete: a left sidebar switches between
    Chat / My Roster / Power Rankings / Best Available (the sidebar's active
    item gets a rounded highlight pill, matching the reference dashboard
    design). Each tab's content is rebuilt fresh on selection (cheap local DB
    reads, plus one live call for Best Available) so it always reflects the
    latest sync."""

    def __init__(self, parent: tk.Widget, config: user_config.UserConfig, on_settings) -> None:
        super().__init__(parent)
        self.pack(fill="both", expand=True)
        self._config = config
        self._on_settings = on_settings
        self._current_key: str | None = None
        self._build()
        self._select("chat")

    def _build(self) -> None:
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        team = self._config.sleeper_username or "your league"
        self._sidebar = Sidebar(
            body,
            tabs=TABS,
            on_select=self._select,
            accent=CELADON,
            accent_text=CELADON_TEXT,
            footer_text=f"Connected as {team}",
            on_settings=lambda: self._on_settings(self._config),
        )
        self._sidebar.pack(side="left", fill="y")

        divider = tk.Frame(body, bg=BORDER, width=1)
        divider.pack(side="left", fill="y")

        content_col = tk.Frame(body, bg=BG)
        content_col.pack(side="left", fill="both", expand=True)

        self._page_header = tk.Frame(content_col, bg=BG)
        self._page_header.pack(fill="x", padx=24, pady=(22, 4))
        self._page_title = tk.Label(
            self._page_header, text="", bg=BG, fg=TEXT, font=("Segoe UI Semibold", 18)
        )
        self._page_title.pack(anchor="w")
        self._page_subtitle = tk.Label(
            self._page_header, text="", bg=BG, fg=TEXT_MUTED, font=("Segoe UI", 10)
        )
        self._page_subtitle.pack(anchor="w", pady=(2, 0))

        self._content = ttk.Frame(content_col)
        self._content.pack(fill="both", expand=True, padx=24, pady=(8, 20))

    def _select(self, key: str) -> None:
        if key == self._current_key:
            return
        self._current_key = key
        self._sidebar.set_active(key)

        title, subtitle = TAB_META[key]
        self._page_title.configure(text=title)
        self._page_subtitle.configure(text=subtitle)

        for child in self._content.winfo_children():
            child.destroy()

        if key == "chat":
            ChatScreen(self._content)
        elif key == "roster":
            RosterScreen(self._content, accent=CELADON)
        elif key == "rankings":
            PowerRankingsScreen(self._content, accent=CELADON)
        elif key == "available":
            BestAvailableScreen(self._content)


class FantasyAgentUserApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Fantasy Agent")
        root.geometry("880x720")
        root.minsize(640, 520)
        root.configure(bg=BG)
        set_window_icon(root)
        build_style_user(root)

        self._container = ttk.Frame(root)
        self._container.pack(fill="both", expand=True)

        existing = user_config.load_user_config()
        if existing is not None:
            user_config.apply_user_config(existing)
            self._show_main(existing)
        else:
            self._show_setup(prefill=None)

    def _clear(self) -> None:
        for child in self._container.winfo_children():
            child.destroy()

    def _show_setup(self, prefill: user_config.UserConfig | None) -> None:
        self._clear()
        SetupScreen(self._container, on_complete=self._show_main, prefill=prefill)

    def _show_main(self, config: user_config.UserConfig) -> None:
        self._clear()
        MainShell(self._container, config=config, on_settings=self._show_setup)


def main() -> None:
    root = tk.Tk()
    FantasyAgentUserApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
