"""Fail a PyInstaller build that would ship a test or dev-only package.

CI freezes both exes in a runtime-only environment (``uv sync --no-dev --group
build``), so these packages shouldn't even be installed there. This is the
backstop for a build run from a full dev environment, or for runtime code that
starts importing test tooling: the build stops instead of quietly bundling it.

Pure Python with no PyInstaller import, so the unit tests can load it directly.
Both specs (``vet_soap_notetaker.spec`` and ``backend/build_spec/backend.spec``)
call :func:`assert_runtime_only` right after ``Analysis(...)``.
"""

import re

# Top-level import names. pywinauto drives the GUI acceptance tests only; av,
# pydantic_ai and pydantic_evals are the backend's eval harness.
DEV_ONLY_PACKAGES = (
    "pytest",
    "_pytest",
    "pytest_mock",
    "pytest_asyncio",
    "respx",
    "pywinauto",
    "PyInstaller",
    "av",
    "pydantic_ai",
    "pydantic_evals",
)


def dev_only_modules(module_names, banned=DEV_ONLY_PACKAGES) -> list[str]:
    """The names that are a banned package or one of its submodules."""
    return [
        name
        for name in module_names
        if any(name == package or name.startswith(package + ".") for package in banned)
    ]


def _binary_module_name(dest_name: str) -> str:
    # "av\\_core.cp311-win_amd64.pyd" -> "av._core"
    parts = re.split(r"[\\/]", dest_name)
    parts[-1] = parts[-1].split(".", 1)[0]
    return ".".join(parts)


def assert_runtime_only(analysis) -> None:
    """Raise ``SystemExit`` if the analysis traced in a dev-only package."""
    names = [entry[0] for entry in analysis.pure]
    names += [
        _binary_module_name(entry[0]) for entry in analysis.binaries if entry[2] == "EXTENSION"
    ]
    found = sorted(set(dev_only_modules(names)))
    if found:
        raise SystemExit("dev-only packages bundled into the exe: " + ", ".join(found))
