"""Contract tests for the desktop app's PyInstaller spec (build_spec/vet_soap_notetaker.spec).

The real proof is CI's Windows exe build; this pins what the launcher relies on.
"""

import tomllib
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


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SPEC_PATH = REPO_ROOT / "backend" / "build_spec" / "backend.spec"


def test_both_specs_fail_the_build_on_a_bundled_dev_package():
    for spec in (SPEC_PATH, BACKEND_SPEC_PATH):
        assert "assert_runtime_only(a)" in spec.read_text(encoding="utf-8"), spec


def test_pywinauto_is_a_test_dependency_not_a_runtime_one():
    # Only the Windows acceptance tests drive the GUI with it.
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert not any(d.startswith("pywinauto") for d in pyproject["project"]["dependencies"])
    assert any(d.startswith("pywinauto") for d in pyproject["dependency-groups"]["dev"])


def _build_job_commands():
    # The build-windows-exe job runs to the end of ci.yml (it's the last job).
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = workflow.split("\n  build-windows-exe:\n", 1)[1]
    return [
        line.strip()
        for line in job.splitlines()
        if line.strip().startswith("run: uv ")
    ]


def test_the_exes_are_frozen_without_the_dev_group():
    commands = _build_job_commands()
    assert len(commands) == 4  # sync + pyinstaller, for the desktop and the backend
    for command in commands:
        assert "--no-dev" in command, command
        assert "--locked" in command, command
