# Build with: pyinstaller FantasyAgent.spec  (after `pip install -e ".[build]"`)
# Produces dist/FantasyAgent/FantasyAgent.exe + a supporting _internal/ folder.
#
# Deliberately --onedir, not --onefile: the GUI re-invokes this same exe as a
# subprocess for every CLI command a button/Ask triggers (see gui.py's
# _cli_command). Onefile mode re-extracts its whole bundle to a temp dir on
# every launch, which would make each GUI action noticeably slower; onedir
# runs directly from disk with no such penalty. Keep the exe and the
# _internal/ folder together -- don't move just the .exe on its own.

from pathlib import Path

project_root = Path(SPECPATH)

a = Analysis(
    ["launcher.py"],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[
        (str(project_root / "assets" / "icon.ico"), "assets"),
        (str(project_root / ".env.example"), "."),
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
    name="FantasyAgent",
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
    name="FantasyAgent",
)
