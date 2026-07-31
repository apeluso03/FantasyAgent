"""Single entry point for the PyInstaller build of the user edition.

Unlike launcher.py (the dev build), gui_user.py never shells out to a CLI
subprocess -- it calls run_agent() and the sync/pipeline functions directly
in-process -- so this launcher has nothing to dispatch on argv for. It just
starts the GUI.
"""

from __future__ import annotations


def main() -> None:
    from fantasy_agent.gui_user import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
