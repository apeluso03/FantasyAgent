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
    CELADON,
    CELADON_TEXT,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    TEXT_MUTED,
    build_style_user,
    draw_yard_line,
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
    ("chat", "\U0001F4AC Chat"),
    ("roster", "\U0001F3C8 My Roster"),
    ("rankings", "\U0001F4CA Power Rankings"),
    ("available", "\U0001F50D Best Available"),
]

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


class ChatLog(ttk.Frame):
    """The scrollable message list. Each message is one tagged paragraph --
    Tkinter's Text widget can't give a background that hugs just the text
    (it always spans the paragraph's full margin-to-margin width), so these
    read as chat-style highlighted message blocks rather than literal
    rounded bubbles, differentiated by side/color and a sender label.
    """

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, style="Surface.TFrame", padding=1)
        self._text = tk.Text(
            self,
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
            self, orient="vertical", command=self._text.yview, style="Minimal.Vertical.TScrollbar"
        )
        self._text.configure(yscrollcommand=vbar.set)
        self._text.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
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


class MainShell(ttk.Frame):
    """Tabbed hub shown once setup is complete: a top tab bar switches
    between Chat / My Roster / Power Rankings / Best Available. Each tab's
    content is rebuilt fresh on selection (cheap local DB reads, plus one
    live call for Best Available) so it always reflects the latest sync."""

    def __init__(self, parent: tk.Widget, config: user_config.UserConfig, on_settings) -> None:
        super().__init__(parent)
        self.pack(fill="both", expand=True)
        self._config = config
        self._on_settings = on_settings
        self._current_key: str | None = None
        self._tab_buttons: dict[str, ttk.Button] = {}
        self._build()
        self._select("chat")

    def _build(self) -> None:
        header = ttk.Frame(self, padding=(18, 16, 18, 8))
        header.pack(fill="x")
        title_col = ttk.Frame(header)
        title_col.pack(side="left", fill="x", expand=True)
        ttk.Label(title_col, text="\U0001F3C8 Fantasy Agent", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_col, text="Your league, at a glance.", style="Subtitle.TLabel").pack(anchor="w")
        ttk.Button(
            header, text="⚙ Settings", style="Ghost.TButton",
            command=lambda: self._on_settings(self._config),
        ).pack(side="right", anchor="n")

        tab_row = ttk.Frame(self, padding=(18, 0, 18, 0))
        tab_row.pack(fill="x")
        for key, label in TABS:
            btn = ttk.Button(tab_row, text=label, style="Tab.TButton", command=lambda k=key: self._select(k))
            btn.pack(side="left", padx=(0, 6), pady=(0, 8))
            self._tab_buttons[key] = btn

        yard_line = tk.Canvas(self, height=14, bg=BG, highlightthickness=0)
        yard_line.pack(fill="x", padx=18)
        yard_line.bind("<Configure>", lambda _e: draw_yard_line(yard_line))

        self._content = ttk.Frame(self)
        self._content.pack(fill="both", expand=True)

    def _select(self, key: str) -> None:
        if key == self._current_key:
            return
        self._current_key = key
        for k, btn in self._tab_buttons.items():
            btn.configure(style="TabActive.TButton" if k == key else "Tab.TButton")

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
