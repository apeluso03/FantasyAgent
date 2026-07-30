"""Single entry point for the PyInstaller build.

A frozen build has no separate python.exe to shell out to, so the GUI
re-invokes this same exe as a subprocess to run CLI commands (see
fantasy_agent/gui.py -- _cli_command). This launcher dispatches on argv: no
arguments means "launch the GUI", any arguments mean "run the CLI with
these args," which is how that self-invocation works.
"""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1:
        from fantasy_agent.cli import app

        app()
    else:
        from fantasy_agent.gui import main as gui_main

        gui_main()


if __name__ == "__main__":
    main()
