"""Contract tests for the desktop app's PyInstaller spec (build_spec/vet_soap_notetaker.spec).

The real proof is CI's Windows exe build; this pins what the launcher relies on.
"""

from pathlib import Path

SPEC_PATH = Path(__file__).resolve().parents[2] / "build_spec" / "vet_soap_notetaker.spec"


def test_the_exe_starts_in_the_lightweight_launcher():
    # launcher.py puts the splash up before main's heavy imports, so it must be
    # the exe's script -- not main.py.
    text = SPEC_PATH.read_text(encoding="utf-8")
    assert '"vet_soap_notetaker" / "launcher.py"' in text
    assert '"main.py"' not in text


def test_the_deferred_main_import_is_still_bundled():
    # launcher imports main inside a function; name it so PyInstaller can't miss it.
    assert '"vet_soap_notetaker.main"' in SPEC_PATH.read_text(encoding="utf-8")
