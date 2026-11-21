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


def test_async_uploads_wait_next_to_the_exams_file():
    from vet_soap_notetaker_backend import main

    assert main._INCOMING_AUDIO_DIR == main._EXAMS_PATH.parent / "incoming"
    assert main.app.state.worker.audio_dir == main._INCOMING_AUDIO_DIR


def test_a_frozen_run_rotates_the_backend_log(monkeypatch, tmp_path):
    # The windowless exe has no console: everything (our lines, uvicorn's, and
    # anything printed) goes to backend.log, which must rotate, not grow forever.
    import logging
    import logging.handlers
    import sys

    from vet_soap_notetaker_backend import main

    run_kwargs = {}
    monkeypatch.setattr(main.uvicorn, "run", lambda *a, **k: run_kwargs.update(k))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(logging, "raiseExceptions", True)
    monkeypatch.setattr(main, "_frozen_log_path", lambda: tmp_path / "logs" / "backend.log")
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(logging.getLogger("vet_soap_notetaker_backend"), "handlers", [])
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        # As uvicorn's own default config leaves them (another test may apply it).
        monkeypatch.setattr(logging.getLogger(name), "propagate", False)
        monkeypatch.setattr(logging.getLogger(name), "handlers", [])

    main.run()
    print("stray print")
    logging.getLogger("uvicorn.error").warning("uvicorn says hi")
    for handler in root.handlers:
        handler.flush()

    [handler] = [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert (handler.maxBytes, handler.backupCount) == (5 * 1024 * 1024, 3)
    assert run_kwargs["log_config"] is None
    text = (tmp_path / "logs" / "backend.log").read_text()
    assert "stray print" in text
    assert "uvicorn says hi" in text
    for h in list(root.handlers):
        h.close()
