# Build with: pyinstaller FantasyAgentUser.spec  (after `pip install -e ".[build]"`)
# Produces dist/FantasyAgentUser/FantasyAgentUser.exe + a supporting _internal/ folder.
#
# --onedir for the same reason as FantasyAgent.spec. This build never bundles
# .env.example: the user edition has no concept of a checked-out .env file --
# all per-user settings are collected by its own setup wizard and stored under
# %APPDATA%\FantasyAgent (see user_config.py). Keep the exe and the
# _internal/ folder together -- don't move just the .exe on its own.

from pathlib import Path

project_root = Path(SPECPATH)

a = Analysis(
    ["launcher_user.py"],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[
        (str(project_root / "assets" / "icon.ico"), "assets"),
    ],
    hiddenimports=[
        # SQLAlchemy picks its dialect module via a dynamic, string-based
        # import keyed off the sqlite:/// URL scheme, which PyInstaller's
        # static analysis can't see -- without this, the build works until
        # the first `create_engine("sqlite:///...")` call, which fails.
        "sqlalchemy.dialects.sqlite",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FantasyAgentUser",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(project_root / "assets" / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="FantasyAgentUser",
)
