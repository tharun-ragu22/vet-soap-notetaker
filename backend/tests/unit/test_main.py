from pathlib import Path

from vetscribe_backend.main import _frozen_log_path


def test_frozen_log_path_uses_appdata_when_set():
    env = {"APPDATA": r"C:\Users\vet\AppData\Roaming"}
    assert _frozen_log_path(env) == (
        Path(r"C:\Users\vet\AppData\Roaming") / "VetScribe" / "logs" / "backend.log"
    )


def test_frozen_log_path_falls_back_to_home_without_appdata():
    assert _frozen_log_path({}) == Path.home() / ".vetscribe" / "logs" / "backend.log"
