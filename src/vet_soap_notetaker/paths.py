import os
import sys
from pathlib import Path


def get_appdata_base_dir() -> Path:
    # NOTE: the on-disk data dir keeps its legacy "VetScribe" / ".vetscribe" name
    # even though the product was renamed to Vet Soap Notetaker. Renaming it would
    # orphan existing installs' config.json and AVImark calibration, so it stays.
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "VetScribe"
    return Path.home() / ".vetscribe"


def get_asset_path(name: str) -> Path:
    # Bundled read-only assets (the logo .ico/.png) live next to the package
    # source in dev, but PyInstaller unpacks them under sys._MEIPASS at
    # runtime. Prefer the frozen location when it exists.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "vet_soap_notetaker" / "assets" / name
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parent / "assets" / name
