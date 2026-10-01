"""Minimal desktop launcher for the fantasy-agent CLI -- the dev build.

No venv activation needed: it shells out via `sys.executable`, which is
already the venv's python when this is launched through run_gui.bat (or the
standalone PyInstaller build -- see FantasyAgent.spec).

Tabbed shell: the Console tab (quick actions, ask box, raw CLI output -- the
"here's how it thinks" dev view) is built once and persists across tab
switches so command history/spinner state survive; the My Roster/Power
Rankings/Best Available tabs are the same shared read-only screens the user
edition uses (gui_screens.py), just recolored to this build's terracotta
accent -- see gui_theme.build_style() vs. build_style_user().

League switcher: shares gui_user.py's profile store (profiles.py/
profile_ui.py) -- if you've added leagues from either build, both can switch
between them. With no profile store yet, this build falls back to `.env` as
before (it's still a standalone dev tool, not something that requires
onboarding). Because the Console tab's quick actions/Ask box shell out to a
*separate* `fantasy-agent` process rather than calling the data layer
in-process, switching leagues here also has to pass the active profile's
settings through as environment variables (see _run_subprocess) -- otherwise
that subprocess would just re-read `.env` and silently ignore the switch.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from . import profile_ui, profiles
from .config import settings
from .gui_screens import BestAvailableScreen, PowerRankingsScreen, RosterScreen
from .gui_theme import (
    ACCENT,
    ACCENT_TEXT,
    BG,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    TEXT_MUTED,
    build_style,
    draw_yard_line,
    set_window_icon,
)

MODULE = "fantasy_agent.cli"

QUICK_ACTIONS = [
    ("Sync", ["sync"]),
    ("Rankings Sync", ["rankings-sync"]),
    ("Keepers", ["keepers"]),
    ("Best Available", ["best-available"]),
    ("League", ["league"]),
    ("Rosters", ["rosters"]),
]

TABS = [
    ("console", "Console"),
    ("roster", "My Roster"),
    ("rankings", "Power Rankings"),
    ("available", "Best Available"),
]

_DONE = object()


def _cli_command(args: list[str]) -> list[str]:
    """Build the subprocess argv for a CLI call.

    Frozen builds have no separate python.exe: `sys.executable` there is
    FantasyAgent.exe itself, and launcher.py dispatches to the CLI when given
    arguments (see launcher.py). In dev mode `sys.executable` is the venv's
    python, so we invoke the module the normal way.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", MODULE, *args]


def _subprocess_env() -> dict[str, str]:
    """Environment for the CLI subprocess, with the *current in-process*
    settings overlaid on top of the inherited environment.

    Without this, switching leagues in this GUI (profiles.apply_profile, see
    _switch_profile) would only affect the in-process screens (Roster/Power
    Rankings/Best Available, which call the data layer directly) -- the
    Console tab's quick actions/Ask box run in a *separate* process that
    would just re-read `.env` from scratch and silently keep using whatever
    league that says, ignoring the switch. pydantic-settings prefers real
    environment variables over `.env`, so setting these here is enough to
    make the subprocess agree with what's on screen.
    """
    env = os.environ.copy()
    if settings.sleeper_league_id:
        env["SLEEPER_LEAGUE_ID"] = settings.sleeper_league_id
    if settings.sleeper_owner_user_id:
        env["SLEEPER_OWNER_USER_ID"] = settings.sleeper_owner_user_id
    env["DATABASE_URL"] = settings.database_url
    if settings.openai_api_key:
        env["OPENAI_API_KEY"] = settings.openai_api_key
    env["OPENAI_MODEL"] = settings.openai_model
    return env


class FantasyAgentGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Fantasy Agent")
        root.geometry("900x680")
        root.minsize(680, 480)
        root.configure(bg=BG)
        set_window_icon(root)

        self._output_queue: "queue.Queue[object]" = queue.Queue()
        self._running = False
        self._buttons: list[ttk.Button] = []
        self._spinner_job: str | None = None
        self._spinner_frame = 0
        self._current_key: str | None = None
        self._tab_buttons: dict[str, ttk.Button] = {}

        store = profiles.load_profile_store()
        active = profiles.get_active_profile(store) if store else None
        if active is not None:
            profiles.apply_profile(active)
        self._active_profile = active

        build_style(self.root)
        self._build_shell()
        self._console_frame = ttk.Frame(self._content)
        self._build_console(self._console_frame)
        self._select("console")
        self._poll_output_queue()

    def _build_shell(self) -> None:
        header = ttk.Frame(self.root, padding=(18, 16, 18, 8))
        header.pack(fill="x")
        title_col = ttk.Frame(header)
        title_col.pack(side="left", fill="x", expand=True)
        ttk.Label(title_col, text="\U0001F3C8 Fantasy Agent", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            title_col, text="Superflex keeper league assistant -- dev build", style="Subtitle.TLabel"
        ).pack(anchor="w")

        league_label = self._active_profile.name if self._active_profile else "League (.env)"
        self._league_btn = ttk.Button(
            header, text=f"{league_label}  ▾", style="Ghost.TButton", command=self._open_switcher_menu
        )
        self._league_btn.pack(side="right", anchor="n")

        tab_row = ttk.Frame(self.root, padding=(18, 0, 18, 0))
        tab_row.pack(fill="x")
        for key, label in TABS:
            btn = ttk.Button(tab_row, text=label, style="Tab.TButton", command=lambda k=key: self._select(k))
            btn.pack(side="left", padx=(0, 6), pady=(0, 8))
            self._tab_buttons[key] = btn

        yard_line = tk.Canvas(self.root, height=14, bg=BG, highlightthickness=0)
        yard_line.pack(fill="x", padx=18)
        yard_line.bind("<Configure>", lambda _e: draw_yard_line(yard_line))

        self._content = ttk.Frame(self.root)
        self._content.pack(fill="both", expand=True)

    def _open_switcher_menu(self) -> None:
        profile_ui.post_profile_menu(
            self._league_btn,
            on_switch=self._switch_profile,
            on_add=lambda: profile_ui.AddLeagueDialog(self.root, on_created=self._on_switch_done),
            on_manage=lambda: profile_ui.ManageLeaguesDialog(self.root, on_changed=self._sync_from_store),
        )

    def _sync_from_store(self) -> None:
        store = profiles.load_profile_store()
        active = profiles.get_active_profile(store) if store else None
        if active is None:
            return
        self._on_switch_done(active)

    def _switch_profile(self, profile: profiles.Profile) -> None:
        if self._active_profile is not None and profile.profile_id == self._active_profile.profile_id:
            return
        self._league_btn.state(["disabled"])
        self._status.set(f"\U0001F3C8 Switching to {profile.name}...")
        profile_ui.switch_to_profile(
            self.root,
            profile,
            on_status=lambda msg: self._status.set(f"\U0001F3C8 {msg}"),
            on_done=lambda: self._on_switch_done(profile),
            on_error=self._on_switch_error,
        )

    def _on_switch_done(self, profile: profiles.Profile) -> None:
        self._active_profile = profile
        self._league_btn.configure(text=f"{profile.name}  ▾")
        self._league_btn.state(["!disabled"])
        self._status.set("Ready.")
        if self._current_key in ("roster", "rankings", "available"):
            self._select(self._current_key, force=True)

    def _on_switch_error(self, message: str) -> None:
        self._league_btn.state(["!disabled"])
        self._status.set(f"Switch failed: {message}")

    def _select(self, key: str, *, force: bool = False) -> None:
        if key == self._current_key and not force:
            return
        self._current_key = key
        for k, btn in self._tab_buttons.items():
            btn.configure(style="TabActive.TButton" if k == key else "Tab.TButton")

        for child in self._content.winfo_children():
            if child is self._console_frame:
                child.pack_forget()
            else:
                child.destroy()

        if key == "console":
            self._console_frame.pack(fill="both", expand=True)
        elif key == "roster":
            RosterScreen(self._content, accent=ACCENT)
        elif key == "rankings":
            PowerRankingsScreen(self._content, accent=ACCENT)
        elif key == "available":
            BestAvailableScreen(self._content)

    def _build_console(self, parent: tk.Widget) -> None:
        actions_wrap = ttk.Frame(parent, padding=(0, 8, 0, 6))
        actions_wrap.pack(fill="x")
        ttk.Label(actions_wrap, text="QUICK ACTIONS", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        actions = ttk.Frame(actions_wrap)
        actions.pack(fill="x")
        for label, args in QUICK_ACTIONS:
            btn = ttk.Button(
                actions, text=label, style="Ghost.TButton", command=lambda a=args: self._run(a)
            )
            btn.pack(side="left", padx=(0, 8))
            self._buttons.append(btn)

        ask_wrap = ttk.Frame(parent, padding=(0, 10, 0, 12))
        ask_wrap.pack(fill="x")
        ttk.Label(ask_wrap, text="ASK THE AGENT", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        ask_row = ttk.Frame(ask_wrap)
        ask_row.pack(fill="x")
        self._question = tk.StringVar()
        entry = ttk.Entry(ask_row, textvariable=self._question, font=("Segoe UI", 10))
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        entry.bind("<Return>", lambda _e: self._ask())
        ask_btn = ttk.Button(ask_row, text="Ask \U0001F3C8", style="Accent.TButton", command=self._ask)
        ask_btn.pack(side="left", padx=(8, 0))
        self._buttons.append(ask_btn)

        output_wrap = ttk.Frame(parent, style="Surface.TFrame", padding=1)
        output_wrap.pack(fill="both", expand=True, pady=(0, 6))
        ttk.Label(
            output_wrap, text="OUTPUT", style="Section.TLabel", background=SURFACE, padding=(10, 6, 10, 0)
        ).pack(anchor="w")
        self._output = ScrolledText(
            output_wrap,
            wrap="word",
            state="disabled",
            font=("Consolas", 10),
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground=ACCENT,
            selectforeground=ACCENT_TEXT,
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=8,
        )
        self._output.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        self._output.vbar.configure(
            bg=SURFACE_ALT, troughcolor=SURFACE, activebackground=ACCENT, highlightthickness=0, bd=0
        )
        self._append_tag("prompt", ACCENT)
        self._append_tag("muted", TEXT_MUTED)

        self._status = tk.StringVar(value="Ready.")
        ttk.Label(parent, textvariable=self._status, style="Status.TLabel", padding=(0, 0, 0, 4)).pack(
            fill="x"
        )

    def _append_tag(self, name: str, color: str) -> None:
        self._output.tag_configure(name, foreground=color)

    def _ask(self) -> None:
        question = self._question.get().strip()
        if not question:
            return
        self._run(["ask", question])

    def _run(self, args: list[str]) -> None:
        if self._running:
            self._append("Still running the previous command -- please wait.\n", tag="muted")
            return
        self._running = True
        for btn in self._buttons:
            btn.state(["disabled"])
        self._start_spinner("Running fantasy-agent " + " ".join(args[:1]))
        self._append(f"\n$ fantasy-agent {' '.join(args)}\n", tag="prompt")
        threading.Thread(target=self._run_subprocess, args=(args,), daemon=True).start()

    def _run_subprocess(self, args: list[str]) -> None:
        try:
            process = subprocess.Popen(
                _cli_command(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=_subprocess_env(),
            )
            assert process.stdout is not None
            for line in process.stdout:
                self._output_queue.put(line)
            process.wait()
        except Exception as exc:  # surfaced in the output pane rather than crashing the GUI
            self._output_queue.put(f"Error launching command: {exc}\n")
        finally:
            self._output_queue.put(_DONE)

    def _poll_output_queue(self) -> None:
        try:
            while True:
                item = self._output_queue.get_nowait()
                if item is _DONE:
                    self._running = False
                    self._stop_spinner()
                    for btn in self._buttons:
                        btn.state(["!disabled"])
                    self._status.set("Ready.")
                else:
                    self._append(item)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.root.after(100, self._poll_output_queue)

    def _append(self, text: str, tag: str | None = None) -> None:
        self._output.configure(state="normal")
        self._output.insert("end", text, tag or ())
        self._output.see("end")
        self._output.configure(state="disabled")

    def _start_spinner(self, label: str) -> None:
        self._spinner_frame = 0
        self._spinner_label = label
        self._tick_spinner()

    def _tick_spinner(self) -> None:
        dots = "." * (self._spinner_frame % 4)
        self._status.set(f"\U0001F3C8 {self._spinner_label}{dots}")
        self._spinner_frame += 1
        self._spinner_job = self.root.after(400, self._tick_spinner)

    def _stop_spinner(self) -> None:
        if self._spinner_job is not None:
            self.root.after_cancel(self._spinner_job)
            self._spinner_job = None


def main() -> None:
    root = tk.Tk()
    FantasyAgentGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
