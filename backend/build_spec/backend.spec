# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the VetScribe backend (the reference SOAP-note server).
#
# Builds a --onedir, windowless build so the desktop app can launch it as a
# hidden background process on the clinic PC (see src/vetscribe/backend_supervisor.py
# in the desktop project). The combined installer drops this build under
# <install>\backend\ next to VetScribe.exe, with the keys ".env" beside the
# backend exe (see config._default_dotenv_path).
#
# --onedir (not --onefile) for the same reason as the desktop build: AV vendors
# flag self-extracting onefile executables far more often, which would block a
# clinic from installing at all.
#
# Build with (from the backend/ project root):
#   uv run pyinstaller build_spec/backend.spec --distpath dist --workpath build

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

repo_root = Path(SPECPATH).parent  # backend/
src_dir = repo_root / "src"

block_cipher = None

# The provider plugins are discovered dynamically at runtime (pkgutil.iter_modules
# + importlib over the note_generation/ and transcription/ packages), so
# PyInstaller's static analysis can't see them -- force the whole backend package
# in. uvicorn likewise imports its loop/protocol/lifespan backends lazily by
# string name, so collect those too or the server won't start when frozen.
#
# Drop the llm/evals/ subpackage: it's a dev-only eval harness (pydantic-evals /
# pydantic-ai) that the server never imports, so it has no place in the shipped
# exe -- forcing it in would needlessly bundle those heavy dev deps.
_collected = collect_submodules("vetscribe_backend") + collect_submodules("uvicorn")
hidden = [m for m in _collected if "evals" not in m.split(".")]

a = Analysis(
    [str(src_dir / "vetscribe_backend" / "main.py")],
    pathex=[str(src_dir)],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Belt and braces with the hidden-imports filter above: keep the eval harness
    # and its dev-only deps out of the shipped backend exe.
    excludes=["vetscribe_backend.llm.evals", "pydantic_evals", "pydantic_ai"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VetScribeBackend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # Windowless: no console flashes up when the desktop app launches it. The
    # backend redirects its own logs to a file when frozen (see main.run) so
    # nothing depends on a console stream existing.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VetScribeBackend",
)
