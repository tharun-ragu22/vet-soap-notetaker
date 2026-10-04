import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

if sys.platform != "win32":
    pytest.skip("requires a real Windows GUI environment", allow_module_level=True)

from pywinauto import Application

from vet_soap_notetaker.api_client import SoapNote
from vet_soap_notetaker.avimark_injector import AvimarkInjector
from vet_soap_notetaker.pipeline import Pipeline
from tests.acceptance.mock_avimark import WINDOW_TITLE

MOCK_AVIMARK_SCRIPT = Path(__file__).parent / "mock_avimark.py"


@pytest.fixture
def mock_avimark_window(tmp_path):
    log_path = tmp_path / "mock_avimark_output.log"
    dump_path = tmp_path / "mock_avimark_dump.txt"
    log_file = log_path.open("w")
    process = subprocess.Popen(
        [sys.executable, str(MOCK_AVIMARK_SCRIPT), str(dump_path)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    app = Application(backend="win32")
    connected = False
    for _ in range(50):
        if process.poll() is not None:
            pytest.fail(
                f"mock AVImark process exited early with code {process.returncode}:\n"
                f"{log_path.read_text()}"
            )
        try:
            app.connect(title=WINDOW_TITLE, timeout=1)
            connected = True
            break
        except Exception:
            time.sleep(0.2)

    if not connected:
        pytest.fail(f"could not find mock AVImark window:\n{log_path.read_text()}")

    window = app.window(title=WINDOW_TITLE)
    window.wait("visible", timeout=10)
    window.set_focus()
    time.sleep(0.2)
    yield window, dump_path

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    log_file.close()


def test_full_pipeline_injects_soap_note_into_focused_avimark_window(mock_avimark_window):
    _window, dump_path = mock_avimark_window
    recorder = MagicMock()
    recorder.save_wav.side_effect = lambda path: Path(path).write_bytes(b"fake-audio")
    api_client = MagicMock()
    api_client.generate_soap_note.return_value = SoapNote(
        subjective="Patient bright, alert, and responsive.",
        objective="Temp 101.5F, HR 120bpm.",
        assessment="Mild gastroenteritis.",
        plan="Bland diet for 3 days, recheck if not improved.",
    )
    on_flyout_needed = MagicMock()

    pipeline = Pipeline(
        recorder=recorder,
        api_client=api_client,
        injector=AvimarkInjector(),
        on_flyout_needed=on_flyout_needed,
    )

    pipeline.toggle_recording()
    pipeline.toggle_recording()

    on_flyout_needed.assert_not_called()

    for _ in range(50):
        if dump_path.exists():
            break
        time.sleep(0.1)

    injected_text = dump_path.read_text()
    assert "SUBJECTIVE" in injected_text
    assert "OBJECTIVE" in injected_text
    assert "ASSESSMENT" in injected_text
    assert "PLAN" in injected_text
