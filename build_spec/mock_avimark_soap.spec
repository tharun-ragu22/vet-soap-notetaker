# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the native-Win32 mock AVImark SOAP window
# (tests/acceptance/mock_avimark_soap.py).
#
# This produces a standalone, self-contained MockAvimarkSoap.exe you can copy
# to a Windows test computer (no Python, no repo, no uv needed there) to try
# calibration + per-box injection against real native Win32 EDIT/BUTTON
# controls. It is a dev/test tool, NOT part of the shipped clinic app.
#
# WINDOWS ONLY: mock_avimark_soap imports pywin32 and exits on any non-win32
# platform, so this must be built on Windows. PyInstaller cannot cross-compile.
#
# Build (from the repo root, on Windows):
#   uv sync --group build
#   uv run pyinstaller build_spec/mock_avimark_soap.spec --distpath dist --workpath build
#
# Result: dist/MockAvimarkSoap.exe  (a single file). Then on the test box:
#   MockAvimarkSoap.exe --layout 3          # just show layout 3
#   MockAvimarkSoap.exe --layout 3 --demo   # auto calibrate + inject into it
# Double-clicking it opens layout 1. A console window stays open for the
# --demo prints and so arguments can be passed.

from pathlib import Path

repo_root = Path(SPECPATH).parent
src_dir = repo_root / "src"
assets_dir = src_dir / "vet_soap_notetaker" / "assets"
entry = repo_root / "tests" / "acceptance" / "mock_avimark_soap.py"

block_cipher = None

a = Analysis(
    [str(entry)],
    # src/ on the path so `import vet_soap_notetaker...` resolves (the mock pulls
    # in avimark_calibration, and avimark_injector on the --demo path).
    pathex=[str(src_dir)],
    binaries=[],
    datas=[],
    # The --demo import of AvimarkInjector is inside a function; list it so the
    # whole injection path is bundled even if static analysis misses it.
    hiddenimports=[
        "vet_soap_notetaker.avimark_injector",
        "vet_soap_notetaker.avimark_calibration",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# --onefile: a single .exe is the easiest thing to drop onto a test machine.
# (The shipped app uses --onedir to dodge AV false positives; this throwaway
# test tool favours portability instead.)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MockAvimarkSoap",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Keep the console: it carries the --demo output and lets args be passed.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(assets_dir / "vet_soap_notetaker.ico"),
)
