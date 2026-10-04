# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Vet Soap Notetaker.
#
# Builds a --onedir (folder) distribution rather than a single --onefile
# binary: AV vendors are much more likely to flag a self-extracting onefile
# executable as a false positive, which would block clinics from installing
# the app at all.
#
# Build with:
#   uv run pyinstaller build_spec/vet_soap_notetaker.spec --distpath dist --workpath build

from pathlib import Path

repo_root = Path(SPECPATH).parent
src_dir = repo_root / "src"
assets_dir = src_dir / "vet_soap_notetaker" / "assets"

block_cipher = None

a = Analysis(
    [str(src_dir / "vet_soap_notetaker" / "main.py")],
    pathex=[str(src_dir)],
    binaries=[],
    # Ship the logo so Tk can set window icons at runtime; it lands under
    # sys._MEIPASS/vet_soap_notetaker/assets/ (see paths.get_asset_path).
    datas=[(str(assets_dir), "vet_soap_notetaker/assets")],
    hiddenimports=[],
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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VetSoapNotetaker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(assets_dir / "vet_soap_notetaker.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VetSoapNotetaker",
)
