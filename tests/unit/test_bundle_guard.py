"""Tests for build_spec/bundle_guard.py, which fails the PyInstaller build if a
test or dev-only package gets traced into a shipped exe."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_GUARD_PATH = Path(__file__).resolve().parents[2] / "build_spec" / "bundle_guard.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("bundle_guard", _GUARD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bundle_guard = _load_guard()


@pytest.mark.parametrize(
    "name", ["pytest", "_pytest.config", "respx", "pydantic_ai.models", "pywinauto", "av"]
)
def test_dev_only_packages_and_their_submodules_are_flagged(name):
    assert bundle_guard.dev_only_modules([name]) == [name]


@pytest.mark.parametrize(
    "name", ["httpx", "avatar_lib", "pytestish", "vet_soap_notetaker.main", "posthog"]
)
def test_runtime_modules_are_not_flagged(name):
    # A shared prefix ("av" / "avatar_lib") is not a submodule.
    assert bundle_guard.dev_only_modules([name]) == []


def _analysis(pure=(), binaries=()):
    return SimpleNamespace(
        pure=[(name, f"/src/{name}.py", "PYMODULE") for name in pure],
        binaries=list(binaries),
    )


def test_a_clean_analysis_passes():
    bundle_guard.assert_runtime_only(
        _analysis(
            pure=["httpx", "vet_soap_notetaker.main"],
            binaries=[("scipy\\linalg\\_flapack.cp311-win_amd64.pyd", "/x", "EXTENSION")],
        )
    )


def test_a_bundled_dev_module_fails_the_build():
    with pytest.raises(SystemExit, match="pytest"):
        bundle_guard.assert_runtime_only(_analysis(pure=["httpx", "pytest"]))


def test_a_bundled_dev_extension_fails_the_build():
    # PyAV ships compiled code; it would show up in binaries, not pure.
    with pytest.raises(SystemExit, match="av"):
        bundle_guard.assert_runtime_only(
            _analysis(binaries=[("av\\_core.cp311-win_amd64.pyd", "/x", "EXTENSION")])
        )
