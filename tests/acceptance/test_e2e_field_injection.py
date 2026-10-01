import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

if sys.platform != "win32":
    pytest.skip("requires a real Windows GUI environment", allow_module_level=True)

from pywinauto import Application

from vetscribe.avimark_injector import AvimarkInjector
from tests.acceptance.mock_avimark import SOAP_WINDOW_TITLE

MOCK_AVIMARK_SCRIPT = Path(__file__).parent / "mock_avimark.py"


@pytest.fixture
def mock_soap_window(tmp_path):
    """Launch the multi-box mock AVImark SOAP window and hand back its dump file."""
    log_path = tmp_path / "mock_avimark_soap.log"
    dump_path = tmp_path / "mock_avimark_soap_dump.json"
    log_file = log_path.open("w")
    process = subprocess.Popen(
        [sys.executable, str(MOCK_AVIMARK_SCRIPT), "--soap", str(dump_path)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    app = Application(backend="win32")
    connected = False
    for _ in range(50):
        if process.poll() is not None:
            pytest.fail(
                f"mock AVImark SOAP process exited early with code {process.returncode}:\n"
                f"{log_path.read_text()}"
            )
        try:
            app.connect(title=SOAP_WINDOW_TITLE, timeout=1)
            connected = True
            break
        except Exception:
            time.sleep(0.2)

    if not connected:
        pytest.fail(f"could not find mock AVImark SOAP window:\n{log_path.read_text()}")

    window = app.window(title=SOAP_WINDOW_TITLE)
    window.wait("visible", timeout=10)
    window.set_focus()
    time.sleep(0.3)
    yield window, dump_path

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    log_file.close()


def _read_boxes(dump_path, expected_last):
    """Poll the dump file until the last box has been filled (or time out)."""
    for _ in range(100):
        if dump_path.exists():
            try:
                boxes = json.loads(dump_path.read_text())
            except (ValueError, OSError):
                boxes = None
            if boxes and len(boxes) == 4 and expected_last in boxes[3]:
                return boxes
        time.sleep(0.1)
    return json.loads(dump_path.read_text()) if dump_path.exists() else []


def test_inject_fields_routes_each_soap_section_to_its_own_box(mock_soap_window):
    _window, dump_path = mock_soap_window
    fields = [
        "Patient bright, alert, and responsive.",
        "Temp 101.5F, HR 120bpm.",
        "Mild gastroenteritis.",
        "Bland diet for 3 days, recheck if not improved.",
    ]

    injector = AvimarkInjector(title_marker="AVImark")
    injected = injector.inject_fields(fields)
    assert injected is True

    boxes = _read_boxes(dump_path, expected_last="Bland diet")

    assert len(boxes) == 4
    assert boxes[0] == fields[0], "Subjective box got the wrong content"
    assert boxes[1] == fields[1], "Objective box got the wrong content"
    assert boxes[2] == fields[2], "Assessment box got the wrong content"
    assert boxes[3] == fields[3], "Plan box got the wrong content"
