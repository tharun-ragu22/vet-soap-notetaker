"""Inspect the AVImark SOAP window's control tree.

Run this on the AVImark PC **with the SOAP note-entry window open and visible**,
then send the output back. It is strictly read-only: it enumerates windows and
prints their controls, and never clicks, types, or changes anything.

    uv run python tools/avimark_inspect.py            # matches windows titled "AVImark"
    uv run python tools/avimark_inspect.py SOAP       # match a different title substring

For each matching top-level window it prints, under both the Win32 and UIA
automation backends, every control's class name, control type, automation id,
visible text, and on-screen rectangle. The four S/O/A/P boxes we want to fill
will show up as Edit / Document controls; their identifiers tell us whether we
can address each box directly (robust) or must navigate between them with the
keyboard. Windows-only (uses pywinauto); run it inside the project venv.
"""

import sys


def dump(backend: str, title: str) -> None:
    try:
        from pywinauto import Desktop
    except ImportError:
        print("pywinauto not installed -- run inside the project venv: `uv run python tools/avimark_inspect.py`")
        return

    print(f"\n{'=' * 72}\nBACKEND: {backend}   (window title contains {title!r})\n{'=' * 72}")
    try:
        windows = [
            w
            for w in Desktop(backend=backend).windows()
            if title.lower() in (w.window_text() or "").lower()
        ]
    except Exception as exc:  # backend may be unavailable; keep going with the other
        print(f"  could not enumerate windows with the {backend} backend: {exc}")
        return

    if not windows:
        print("  no matching windows found -- is the AVImark SOAP window open and visible?")
        return

    for w in windows:
        print(f"\n--- window: {w.window_text()!r}  (handle={getattr(w, 'handle', '?')}) ---")
        try:
            # depth=None walks the full control tree, including nested panels/dialogs.
            w.print_control_identifiers(depth=None)
        except Exception as exc:
            print(f"  print_control_identifiers failed: {exc}")


def main() -> None:
    title = sys.argv[1] if len(sys.argv) > 1 else "AVImark"
    print(
        "VetScribe AVImark window inspector (read-only).\n"
        "Open the AVImark SOAP note-entry window first, then run this.\n"
    )
    for backend in ("win32", "uia"):
        dump(backend, title)
    print(
        "\nDone. Copy everything above and send it back. If nothing matched, try a\n"
        "different title substring, e.g. `uv run python tools/avimark_inspect.py SOAP`."
    )


if __name__ == "__main__":
    main()
