"""Contract tests for the Inno Setup installer script (build_spec/installer.iss).

The installer itself can only be compiled and run on Windows (via `iscc`), so the
real proof is the CI compile step and the on-site install. What we *can* pin here,
on any platform, is that the script keeps honoring the contracts the rest of the
app depends on:

- it drops the backend onedir exactly where ``backend_supervisor.find_bundled_backend``
  looks for it (``<app>\\<BACKEND_SUBDIR>\\<BACKEND_EXE_NAME>``),
- the autostart entry it writes matches the key/value the ``autostart`` module
  manages, so ``is_enabled()``/``disable()`` and the uninstaller stay consistent,
- it opens *and closes* the backend's firewall port,
- it seeds config pointing the desktop app at the *local* backend over http (the
  bundled backend serves plain http, not the https default in ``config``),
- removing it is reversible: autostart entry, firewall rule and (on the vet's
  confirmation) the data dirs all get torn down.

These are deliberately tolerant text assertions over the declarative script, not a
line-for-line mirror of it.
"""

import json
from pathlib import Path

from vet_soap_notetaker.autostart import APP_NAME, RUN_KEY_PATH
from vet_soap_notetaker.backend_supervisor import BACKEND_EXE_NAME, BACKEND_SUBDIR

ISS_PATH = Path(__file__).resolve().parents[2] / "build_spec" / "installer.iss"
CLINIC_CONFIG_PATH = ISS_PATH.parent / "clinic_config.json"


def _iss_text() -> str:
    return ISS_PATH.read_text(encoding="utf-8")


def test_installer_bundles_the_desktop_app_into_the_app_dir():
    text = _iss_text()
    assert r"..\dist\VetSoapNotetaker\*" in text
    assert 'DestDir: "{app}"' in text


def test_installer_bundles_the_backend_under_the_supervised_subdir():
    # backend_supervisor.find_bundled_backend() resolves <app>\<BACKEND_SUBDIR>\<exe>,
    # so the installer must place the backend onedir exactly there or the desktop
    # app won't find the backend to launch.
    text = _iss_text()
    assert r"..\backend\dist\VetSoapNotetakerBackend\*" in text
    assert f'DestDir: "{{app}}\\{BACKEND_SUBDIR}"' in text
    # guard the exe-name assumption the supervisor and PyInstaller spec share
    assert BACKEND_EXE_NAME == "VetSoapNotetakerBackend.exe"


def test_installer_registers_autostart_matching_the_autostart_module():
    text = _iss_text()
    assert "[Registry]" in text
    assert "HKCU" in text
    assert RUN_KEY_PATH in text
    assert f'ValueName: "{APP_NAME}"' in text
    # the frozen exe launches with no args (no `-m vet_soap_notetaker.main`)
    assert r"{app}\VetSoapNotetaker.exe" in text
    # torn down on uninstall
    assert "uninsdeletevalue" in text


def test_installer_opens_and_closes_the_backend_firewall_port():
    text = _iss_text()
    assert "[Run]" in text
    assert "[UninstallRun]" in text
    assert "advfirewall firewall add rule" in text
    assert "advfirewall firewall delete rule" in text
    assert "8443" in text


def test_installer_seeds_config_pointing_at_the_local_backend():
    text = _iss_text()
    assert "clinic_config.json" in text
    assert "config.json" in text
    # never clobber a config the vet/you already tuned
    assert "onlyifdoesntexist" in text


def test_seeded_clinic_config_targets_the_local_http_backend():
    cfg = json.loads(CLINIC_CONFIG_PATH.read_text())
    # bundled backend is plain http on 8443, unlike config.DEFAULT_CONFIG's https
    assert cfg["api_endpoint"] == "http://localhost:8443/api/soap"


def test_installer_seeds_provider_keys_beside_the_backend_exe_if_present():
    # config._default_dotenv_path (frozen) reads .env beside the backend exe.
    # Optional at build time (skipifsourcedoesntexist) so the repo never carries
    # secrets -- the real keyed .env is dropped in only when building the shipped
    # installer.
    text = _iss_text()
    assert ".env" in text
    assert "skipifsourcedoesntexist" in text


def test_installer_requires_admin_for_firewall_and_program_files():
    assert "PrivilegesRequired=admin" in _iss_text()


def test_uninstaller_offers_to_remove_both_data_dirs():
    text = _iss_text()
    assert "[Code]" in text
    # data dirs keep their legacy names: %APPDATA%\VetScribe (logs/recordings) and
    # ~\.vetscribe (config/history) -- renaming them would orphan existing installs
    assert ".vetscribe" in text
    assert r"{userappdata}\VetScribe" in text
    # a prompt -- removal is the vet's choice, so uninstall isn't silently destructive
    assert "MsgBox" in text
