"""Minimal desktop launcher for the fantasy-agent CLI.

No venv activation needed: it shells out via `sys.executable`, which is
already the venv's python when this is launched through run_gui.bat (or the
standalone PyInstaller build -- see FantasyAgent.spec).
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

MODULE = "fantasy_agent.cli"

# Dark palette in the spirit of Claude's chat window, with a football accent.
BG = "#262624"
SURFACE = "#30302E"
SURFACE_ALT = "#3A3937"
BORDER = "#45443F"
TEXT = "#ECEBE4"
TEXT_MUTED = "#A8A599"
ACCENT = "#D97757"  # terracotta
ACCENT_HOVER = "#C2684A"
FIELD_GREEN = "#3A6B35"
FIELD_GREEN_HOVER = "#4C8A45"

QUICK_ACTIONS = [
    ("Sync", ["sync"]),
    ("Rankings Sync", ["rankings-sync"]),
    ("Keepers", ["keepers"]),
    ("Best Available", ["best-available"]),
    ("League", ["league"]),
    ("Rosters", ["rosters"]),
]

_DONE = object()


def _resource_path(relative: str) -> Path:
    """Resolve a bundled asset both in dev mode and inside a PyInstaller build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return base / relative


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


class FantasyAgentGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Fantasy Agent")
        root.geometry("900x620")
        root.minsize(680, 460)
        root.configure(bg=BG)
        self._set_icon()

        self._output_queue: "queue.Queue[object]" = queue.Queue()
        self._running = False
        self._buttons: list[ttk.Button] = []
        self._spinner_job: str | None = None
        self._spinner_frame = 0

        self._build_style()
        self._build_widgets()
        self._poll_output_queue()

    def _set_icon(self) -> None:
        icon_path = _resource_path("assets/icon.ico")
        if icon_path.exists():
            try:
                self.root.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass  # non-Windows or unsupported format -- cosmetic only

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")  # only fully-themable base available across platforms

        style.configure("TFrame", background=BG)
        style.configure("Surface.TFrame", background=SURFACE)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 20))
        style.configure("Subtitle.TLabel", background=BG, foreground=TEXT_MUTED, font=("Segoe UI", 10))
        style.configure(
            "Section.TLabel", background=BG, foreground=TEXT_MUTED, font=("Segoe UI Semibold", 9)
        )
        style.configure("Status.TLabel", background=BG, foreground=TEXT_MUTED, font=("Segoe UI", 9))

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
            foreground="#20201E",
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

    def _build_widgets(self) -> None:
        header = ttk.Frame(self.root, padding=(18, 16, 18, 10))
        header.pack(fill="x")
        ttk.Label(header, text="\U0001F3C8 Fantasy Agent", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header, text="Superflex keeper league assistant", style="Subtitle.TLabel"
        ).pack(anchor="w")

        self._yard_line = tk.Canvas(self.root, height=14, bg=BG, highlightthickness=0)
        self._yard_line.pack(fill="x", padx=18)
        self._yard_line.bind("<Configure>", self._draw_yard_line)

        actions_wrap = ttk.Frame(self.root, padding=(18, 14, 18, 6))
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

        ask_wrap = ttk.Frame(self.root, padding=(18, 10, 18, 12))
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

        output_wrap = ttk.Frame(self.root, style="Surface.TFrame", padding=1)
        output_wrap.pack(fill="both", expand=True, padx=18, pady=(0, 6))
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
            selectforeground="#20201E",
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
        ttk.Label(self.root, textvariable=self._status, style="Status.TLabel", padding=(18, 0, 18, 12)).pack(
            fill="x"
        )

    def _draw_yard_line(self, _event: tk.Event | None = None) -> None:
        canvas = self._yard_line
        canvas.delete("all")
        width = canvas.winfo_width()
        if width <= 1:
            return
        y = 7
        canvas.create_line(0, y, width, y, fill=BORDER, width=1)
        step = 40
        for x in range(0, width, step):
            canvas.create_line(x, y - 4, x, y + 4, fill=ACCENT, width=2)

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
