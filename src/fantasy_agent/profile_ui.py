"""Profile-switcher widgets shared by both GUI editions: gui.py's header
button and gui_user.py's sidebar footer button both open the same quick-
switch menu and the same Add/Manage League dialogs (see gui.py/gui_user.py
for how each wires the callbacks into its own layout).

Deliberately built on plain tk.Toplevel/tk.Menu rather than swapping into
either app's own screen-stack: both callers just need "pop up a dialog,
tell me when something changed," not a full navigation flow, and a Toplevel
is the simplest thing that reliably works from *any* calling context (a
console-only dev build header button vs. a tabbed shell's sidebar).
Every ttk widget used here (Accent.TButton, Ghost.TButton, etc.) relies on
whichever app already registered its styles via build_style()/
build_style_user() before opening one of these -- ttk styles are global to
the Tk interpreter, so a Toplevel automatically picks up the right colors
without this module needing to know which app it's running inside.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import profiles
from .gui_theme import BG, SURFACE, SURFACE_ALT, TEXT, TEXT_MUTED, set_window_icon
from .sleeper.client import SleeperAPIError


def post_profile_menu(anchor: tk.Widget, *, on_switch, on_add, on_manage) -> None:
    """Pop up a small menu of every saved league (active one marked with a
    bullet) plus "+ Add League" / "Manage Leagues...", anchored just below
    `anchor`. Reads the profile store fresh on each open so it's never stale.
    """
    store = profiles.load_profile_store()
    menu = tk.Menu(
        anchor, tearoff=0, bg=SURFACE_ALT, fg=TEXT, activebackground=SURFACE,
        activeforeground=TEXT, borderwidth=0, relief="flat", font=("Segoe UI", 10),
    )
    if store is not None and store.profiles:
        for profile in store.profiles.values():
            bullet = "● " if profile.profile_id == store.active_profile_id else "  "
            menu.add_command(label=bullet + profile.name, command=lambda p=profile: on_switch(p))
        menu.add_separator()
    menu.add_command(label="+ Add League", command=on_add)
    menu.add_command(label="Manage Leagues...", command=on_manage)

    x = anchor.winfo_rootx()
    y = anchor.winfo_rooty() + anchor.winfo_height()
    try:
        menu.tk_popup(x, y)
    finally:
        menu.grab_release()


def switch_to_profile(root: tk.Misc, profile: profiles.Profile, *, on_status, on_done, on_error) -> None:
    """Autosync-then-switch, off the GUI thread. `on_status(str)`, `on_done()`,
    and `on_error(str)` are all called back on the GUI thread via `root.after`.
    Shared by the quick-switch menu and the Manage Leagues dialog's Switch
    button so there's exactly one implementation of "what switching means."
    """

    def worker() -> None:
        try:
            profiles.resync_profile(profile, on_status=lambda msg: root.after(0, lambda: on_status(msg)))
        except Exception as exc:  # network hiccups, revoked API key, etc.
            root.after(0, lambda: on_error(str(exc)))
            return
        root.after(0, on_done)

    threading.Thread(target=worker, daemon=True).start()


class AddLeagueDialog(tk.Toplevel):
    """Modal "connect a new league" form -- the same fields as gui_user.py's
    first-run SetupScreen, just in a popup instead of a full-screen swap,
    since this is opened from *within* an already-running app rather than at
    startup. Always creates a brand-new profile; editing the active profile's
    own settings happens through gui_user.py's Settings screen instead (see
    profiles.update_and_sync_profile's docstring for why editing is scoped
    that way).
    """

    def __init__(self, parent: tk.Misc, *, on_created) -> None:
        super().__init__(parent)
        self.title("Add League")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        set_window_icon(self)
        self._on_created = on_created
        self._build()
        self.grab_set()

    def _build(self) -> None:
        body = ttk.Frame(self, padding=24)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Add a League", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            body, text="Connect another league -- switch between them anytime.", style="Subtitle.TLabel"
        ).pack(anchor="w", pady=(0, 16))

        self._name = self._labeled_entry(body, "LEAGUE NICKNAME", "", hint="e.g. Dynasty League, Redraft w/ friends")
        self._league_id = self._labeled_entry(
            body, "LEAGUE ID", "", hint="Find this in your league's Sleeper URL."
        )
        self._username = self._labeled_entry(
            body, "YOUR SLEEPER USERNAME", "", hint="Used to figure out which roster is yours."
        )

        ttk.Label(body, text="OPENAI API KEY", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        key_row = ttk.Frame(body)
        key_row.pack(fill="x")
        self._api_key = tk.StringVar()
        self._key_entry = ttk.Entry(key_row, textvariable=self._api_key, font=("Segoe UI", 10), show="*", width=32)
        self._key_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self._key_visible = False
        self._show_btn = ttk.Button(key_row, text="Show", style="Ghost.TButton", command=self._toggle_key)
        self._show_btn.pack(side="left", padx=(8, 0))
        ttk.Label(body, text="Stored only on this computer.", style="Status.TLabel").pack(
            anchor="w", pady=(2, 16)
        )

        self._error = tk.StringVar()
        ttk.Label(body, textvariable=self._error, style="Error.TLabel", wraplength=380).pack(
            anchor="w", pady=(0, 8)
        )

        button_row = ttk.Frame(body)
        button_row.pack(fill="x")
        self._submit_btn = ttk.Button(
            button_row, text="Add League \U0001F3C8", style="Accent.TButton", command=self._submit
        )
        self._submit_btn.pack(side="left")
        ttk.Button(button_row, text="Cancel", style="Ghost.TButton", command=self.destroy).pack(
            side="left", padx=(8, 0)
        )
        self._status = tk.StringVar()
        ttk.Label(button_row, textvariable=self._status, style="Status.TLabel").pack(side="left", padx=(12, 0))

    def _labeled_entry(self, parent: tk.Widget, label: str, initial: str, hint: str) -> tk.StringVar:
        ttk.Label(parent, text=label, style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        var = tk.StringVar(value=initial)
        ttk.Entry(parent, textvariable=var, font=("Segoe UI", 10), width=32).pack(fill="x", ipady=4)
        ttk.Label(parent, text=hint, style="Status.TLabel").pack(anchor="w", pady=(2, 16))
        return var

    def _toggle_key(self) -> None:
        self._key_visible = not self._key_visible
        self._key_entry.configure(show="" if self._key_visible else "*")
        self._show_btn.configure(text="Hide" if self._key_visible else "Show")

    def _submit(self) -> None:
        name = self._name.get().strip()
        league_id = self._league_id.get().strip()
        username = self._username.get().strip()
        api_key = self._api_key.get().strip()

        if not name:
            self._error.set("Give this league a nickname.")
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
            target=self._do_create, args=(name, league_id, username, api_key), daemon=True
        ).start()

    def _do_create(self, name: str, league_id: str, username: str, api_key: str) -> None:
        try:
            profile = profiles.create_and_sync_profile(
                name=name, platform="sleeper", league_id=league_id, username=username, api_key=api_key,
                on_status=lambda msg: self.after(0, lambda: self._status.set(msg)),
            )
        except SleeperAPIError as exc:
            self.after(0, lambda: self._fail(str(exc)))
            return
        except Exception as exc:  # network hiccups, bad key format, etc. -- never crash the dialog
            self.after(0, lambda: self._fail(f"Couldn't add league: {exc}"))
            return
        self.after(0, lambda: self._succeed(profile))

    def _succeed(self, profile: profiles.Profile) -> None:
        self._on_created(profile)
        self.destroy()

    def _fail(self, message: str) -> None:
        self._error.set(message)
        self._status.set("")
        self._submit_btn.state(["!disabled"])


class ManageLeaguesDialog(tk.Toplevel):
    """Lists every saved league with Switch/Rename/Remove actions, plus a
    shortcut into AddLeagueDialog. `on_changed()` fires after anything here
    changes the active profile or the profile set, so the caller can refresh
    its own header/sidebar and currently-visible tab."""

    def __init__(self, parent: tk.Misc, *, on_changed) -> None:
        super().__init__(parent)
        self.title("Manage Leagues")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        set_window_icon(self)
        self._on_changed = on_changed
        self._build()
        self.grab_set()

    def _build(self) -> None:
        ttk.Label(self, text="Your Leagues", style="Title.TLabel", padding=(24, 20, 24, 4)).pack(anchor="w")
        self._list_frame = ttk.Frame(self, padding=(24, 0, 24, 12))
        self._list_frame.pack(fill="both", expand=True)
        self._refresh_list()

        button_row = ttk.Frame(self, padding=(24, 0, 24, 20))
        button_row.pack(fill="x")
        ttk.Button(
            button_row, text="+ Add League", style="Accent.TButton",
            command=lambda: AddLeagueDialog(self, on_created=self._handle_added),
        ).pack(side="left")
        ttk.Button(button_row, text="Close", style="Ghost.TButton", command=self.destroy).pack(side="right")

    def _refresh_list(self) -> None:
        for child in self._list_frame.winfo_children():
            child.destroy()

        store = profiles.load_profile_store()
        if store is None or not store.profiles:
            ttk.Label(self._list_frame, text="No leagues yet.", style="Status.TLabel").pack(anchor="w")
            return

        for profile in store.profiles.values():
            is_active = profile.profile_id == store.active_profile_id
            row = ttk.Frame(self._list_frame, style="Surface.TFrame", padding=12)
            row.pack(fill="x", pady=4)

            info = ttk.Frame(row, style="Surface.TFrame")
            info.pack(side="left", fill="x", expand=True)
            name_text = profile.name + ("  (active)" if is_active else "")
            ttk.Label(
                info, text=name_text, background=SURFACE, foreground=TEXT, font=("Segoe UI Semibold", 10)
            ).pack(anchor="w")
            ttk.Label(
                info, text=f"League ID {profile.league_id}", background=SURFACE, foreground=TEXT_MUTED,
                font=("Segoe UI", 9),
            ).pack(anchor="w")

            actions = ttk.Frame(row, style="Surface.TFrame")
            actions.pack(side="right")
            if not is_active:
                ttk.Button(
                    actions, text="Switch", style="Ghost.TButton", command=lambda p=profile: self._switch(p)
                ).pack(side="left", padx=(0, 6))
            ttk.Button(
                actions, text="Rename", style="Ghost.TButton", command=lambda p=profile: self._rename(p)
            ).pack(side="left", padx=(0, 6))
            ttk.Button(
                actions, text="Remove", style="Ghost.TButton", command=lambda p=profile: self._remove(p)
            ).pack(side="left")

    def _handle_added(self, _profile: profiles.Profile) -> None:
        self._refresh_list()
        self._on_changed()

    def _switch(self, profile: profiles.Profile) -> None:
        for child in self._list_frame.winfo_children():
            child.configure(cursor="wait")
        switch_to_profile(
            self,
            profile,
            on_status=lambda _msg: None,
            on_done=lambda: (self._refresh_list(), self._on_changed()),
            on_error=lambda msg: messagebox.showerror("Couldn't switch leagues", msg, parent=self),
        )

    def _rename(self, profile: profiles.Profile) -> None:
        new_name = simpledialog.askstring(
            "Rename League", "New name:", initialvalue=profile.name, parent=self
        )
        if not new_name or not new_name.strip():
            return
        store = profiles.load_profile_store()
        if store is None:
            return
        profile.name = new_name.strip()
        profiles.update_profile(store, profile)
        self._refresh_list()
        self._on_changed()

    def _remove(self, profile: profiles.Profile) -> None:
        store = profiles.load_profile_store()
        if store is None:
            return
        if len(store.profiles) <= 1:
            messagebox.showinfo("Can't remove", "You need at least one league.", parent=self)
            return
        if not messagebox.askyesno(
            "Remove League",
            f"Remove '{profile.name}'? Its cached data stays on disk, but the app will forget this "
            "connection -- you'd need to add it again with your league ID and API key.",
            parent=self,
        ):
            return

        was_active = profile.profile_id == store.active_profile_id
        profiles.remove_profile(store, profile.profile_id)

        if was_active:
            new_active = profiles.get_active_profile(store)
            if new_active is not None:
                switch_to_profile(
                    self,
                    new_active,
                    on_status=lambda _msg: None,
                    on_done=lambda: (self._refresh_list(), self._on_changed()),
                    on_error=lambda msg: messagebox.showerror("Couldn't switch leagues", msg, parent=self),
                )
                return

        self._refresh_list()
        self._on_changed()
