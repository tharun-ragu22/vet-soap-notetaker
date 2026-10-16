from pathlib import Path

from vet_soap_notetaker_backend.main import _frozen_log_path


def test_frozen_log_path_uses_appdata_when_set():
    env = {"APPDATA": r"C:\Users\vet\AppData\Roaming"}
    assert _frozen_log_path(env) == (
        Path(r"C:\Users\vet\AppData\Roaming") / "VetScribe" / "logs" / "backend.log"
    )


def test_frozen_log_path_falls_back_to_home_without_appdata():
    assert _frozen_log_path({}) == Path.home() / ".vetscribe" / "logs" / "backend.log"


def test_run_shows_the_backends_info_logs(monkeypatch):
    # uvicorn only configures its own loggers; without this, the backend's
    # timing and retry lines would be silently dropped.
    import logging

    from vet_soap_notetaker_backend import main

    monkeypatch.setattr(main.uvicorn, "run", lambda *a, **k: None)
    package_logger = logging.getLogger("vet_soap_notetaker_backend")
    monkeypatch.setattr(package_logger, "handlers", [])
    monkeypatch.setattr(package_logger, "level", logging.NOTSET)

    main.run()

    assert package_logger.getEffectiveLevel() == logging.INFO
    assert package_logger.handlers
