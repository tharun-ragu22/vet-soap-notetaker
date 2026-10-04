from pathlib import Path

from vet_soap_notetaker.paths import get_appdata_base_dir


def test_uses_appdata_on_windows_when_set(mocker):
    mocker.patch("vet_soap_notetaker.paths.sys.platform", "win32")
    mocker.patch.dict(
        "vet_soap_notetaker.paths.os.environ",
        {"APPDATA": r"C:\Users\vet\AppData\Roaming"},
    )

    result = get_appdata_base_dir()

    assert result == Path(r"C:\Users\vet\AppData\Roaming") / "VetScribe"


def test_falls_back_to_home_dot_vet_soap_notetaker_when_not_windows(mocker):
    mocker.patch("vet_soap_notetaker.paths.sys.platform", "linux")

    result = get_appdata_base_dir()

    assert result == Path.home() / ".vetscribe"


def test_falls_back_to_home_dot_vet_soap_notetaker_on_windows_without_appdata_env(mocker):
    mocker.patch("vet_soap_notetaker.paths.sys.platform", "win32")
    mocker.patch.dict("vet_soap_notetaker.paths.os.environ", {"APPDATA": ""})

    result = get_appdata_base_dir()

    assert result == Path.home() / ".vetscribe"
