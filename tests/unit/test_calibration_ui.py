"""Tests for CalibrationController -- the logic that drives a box calibration.

The controller owns a CalibrationSession and sequences the prompt/capture/save
steps; the actual instruction window and the global mouse hook are injected as
plain callables, so the sequencing is testable without a display or pynput.
"""

from vet_soap_notetaker.avimark_calibration import SOAP_SECTIONS, BoxCalibration, BoxControl
from vet_soap_notetaker.calibration_ui import CalibrationController


def _make(capture=None):
    events = {"prompts": [], "saved": [], "closed": 0}

    def capture_fn(x, y):
        return (capture or (lambda x, y: BoxControl(x, "Edit", 0.0, 0.0)))(x, y)

    def prompt(section, done, total):
        events["prompts"].append((section, done, total))

    def save(calibration):
        events["saved"].append(calibration)

    def close():
        events["closed"] += 1

    controller = CalibrationController(
        capture=capture_fn, save=save, prompt=prompt, close=close
    )
    return controller, events


def test_start_prompts_for_the_first_box():
    controller, events = _make()

    controller.start()

    assert events["prompts"] == [("subjective", 0, 4)]


def test_each_click_advances_the_prompt_to_the_next_box():
    controller, events = _make()
    controller.start()

    controller.on_click(10, 20)  # subjective captured -> prompt objective
    controller.on_click(10, 40)  # objective -> assessment
    controller.on_click(10, 60)  # assessment -> plan

    assert events["prompts"] == [
        ("subjective", 0, 4),
        ("objective", 1, 4),
        ("assessment", 2, 4),
        ("plan", 3, 4),
    ]
    # not done yet -- nothing saved or closed
    assert events["saved"] == []
    assert events["closed"] == 0


def test_final_click_saves_the_calibration_and_closes():
    controller, events = _make()
    controller.start()
    for i in range(4):
        controller.on_click(100 + i, 0)

    assert len(events["saved"]) == 1
    saved = events["saved"][0]
    assert isinstance(saved, BoxCalibration)
    assert saved.is_complete()
    # each section captured its own click (control_id == x in the fake)
    assert [saved.get(s).control_id for s in SOAP_SECTIONS] == [100, 101, 102, 103]
    assert events["closed"] == 1


def test_clicks_after_completion_are_ignored():
    controller, events = _make()
    controller.start()
    for i in range(4):
        controller.on_click(i, 0)

    controller.on_click(999, 0)  # stray click after we're done

    assert len(events["saved"]) == 1  # not saved again
    assert events["closed"] == 1
