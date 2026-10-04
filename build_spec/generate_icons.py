"""Regenerate the committed Vet Soap Notetaker logo assets from ``vet_soap_notetaker.icon_art``.

The tray icon is drawn live (its collar colour changes with pipeline state),
but the taskbar/window/exe icon is a static file. This script bakes the
idle-green logo into a multi-resolution Windows ``.ico`` (used by PyInstaller
for the .exe and by Tk for window icons on Windows) and a 256px ``.png`` (used
by Tk's ``iconphoto`` on Linux/macOS).

Run from the repo root:

    uv run python build_spec/generate_icons.py
"""

from pathlib import Path

from vet_soap_notetaker.icon_art import render_logo

ASSETS = Path(__file__).resolve().parent.parent / "src" / "vet_soap_notetaker" / "assets"
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = render_logo(256, "green")
    master.save(ASSETS / "vet_soap_notetaker.png")
    master.save(
        ASSETS / "vet_soap_notetaker.ico",
        sizes=[(s, s) for s in ICO_SIZES],
    )
    print(f"Wrote {ASSETS / 'vet_soap_notetaker.png'} and {ASSETS / 'vet_soap_notetaker.ico'}")


if __name__ == "__main__":
    main()
