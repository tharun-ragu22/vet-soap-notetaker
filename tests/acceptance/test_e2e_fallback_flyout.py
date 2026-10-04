import sys
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock

import pytest

if sys.platform != "win32":
    pytest.skip("requires a real Windows GUI environment", allow_module_level=True)

from vet_soap_notetaker.api_client import SoapNote
from vet_soap_notetaker.avimark_injector import AvimarkInjector
from vet_soap_notetaker.flyout_ui import FlyoutWindow
from vet_soap_notetaker.pipeline import Pipeline


def test_pipeline_shows_safety_flyout_when_avimark_not_focused():
    recorder = MagicMock()
    recorder.save_wav.side_effect = lambda path: Path(path).write_bytes(b"fake-audio")
    api_client = MagicMock()
    api_client.generate_soap_note.return_value = SoapNote(
        subjective="sub", objective="obj", assessment="assess", plan="plan"
    )

    root = tk.Tk()
    root.withdraw()
    flyouts_shown = []

    def on_flyout_needed(soap_text):
        flyouts_shown.append(
            FlyoutWindow(
                master=root,
                soap_text=soap_text,
                on_copy_and_inject=lambda: None,
                on_copy_to_clipboard=lambda: None,
            )
        )

    pipeline = Pipeline(
        recorder=recorder,
        api_client=api_client,
        injector=AvimarkInjector(),
        on_flyout_needed=on_flyout_needed,
    )

    try:
        pipeline.toggle_recording()
        pipeline.toggle_recording()

        assert len(flyouts_shown) == 1
        flyout = flyouts_shown[0]
        displayed_text = flyout.text_widget.get("1.0", "end-1c")
        assert "SUBJECTIVE: sub" in displayed_text
        assert "PLAN: plan" in displayed_text
        assert flyout.attributes("-topmost") == 1
    finally:
        root.destroy()
