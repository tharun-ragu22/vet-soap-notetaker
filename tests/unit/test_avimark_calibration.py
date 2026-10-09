"""Unit tests for the pure AVImark box-calibration model and resolution logic.

These carry no Win32 dependency: the model is plain data (serializable into the
desktop config) and ``choose_control`` is a pure algorithm over a list of
candidate controls, so the brittle Windows parts (enumerating child windows,
focusing a control, pasting) stay in the injector and are exercised separately.
"""

import pytest

from vet_soap_notetaker.avimark_calibration import (
    SOAP_SECTIONS,
    BoxCalibration,
    BoxControl,
    choose_control,
    descriptor_from_capture,
)


def _candidate(hwnd, control_id, class_name, rect):
    return {"hwnd": hwnd, "control_id": control_id, "class_name": class_name, "rect": rect}


# --- model + serialization ---------------------------------------------------


def test_soap_sections_are_the_four_in_paste_order():
    assert SOAP_SECTIONS == ("subjective", "objective", "assessment", "plan")


def test_box_control_round_trips_through_dict():
    box = BoxControl(control_id=1007, class_name="RichEdit20W", rel_x=0.25, rel_y=0.4)
    assert BoxControl.from_dict(box.to_dict()) == box


def test_box_calibration_round_trips_through_dict():
    cal = BoxCalibration(
        boxes={
            section: BoxControl(control_id=i, class_name="Edit", rel_x=0.1 * i, rel_y=0.2 * i)
            for i, section in enumerate(SOAP_SECTIONS, start=1)
        }
    )
    assert BoxCalibration.from_dict(cal.to_dict()) == cal


def test_is_complete_requires_all_four_sections():
    partial = BoxCalibration(boxes={"subjective": BoxControl(1, "Edit", 0.1, 0.1)})
    assert partial.is_complete() is False
    full = BoxCalibration(
        boxes={s: BoxControl(i, "Edit", 0.1, 0.1) for i, s in enumerate(SOAP_SECTIONS)}
    )
    assert full.is_complete() is True


def test_get_returns_the_box_for_a_section_or_none():
    box = BoxControl(5, "Edit", 0.1, 0.1)
    cal = BoxCalibration(boxes={"objective": box})
    assert cal.get("objective") is box
    assert cal.get("plan") is None


def test_has_duplicate_controls_flags_sections_sharing_a_nonzero_id():
    # The multi-monitor collapse: every click captured the same control, so all
    # four sections carry one control id -- resolving them all to one box.
    collapsed = BoxCalibration(
        boxes={s: BoxControl(1001, "Edit", 0.1 * i, 0.1 * i) for i, s in enumerate(SOAP_SECTIONS)}
    )
    assert collapsed.has_duplicate_controls() is True


def test_has_duplicate_controls_is_false_for_distinct_ids():
    good = BoxCalibration(
        boxes={s: BoxControl(1001 + i, "Edit", 0.1, 0.1) for i, s in enumerate(SOAP_SECTIONS)}
    )
    assert good.has_duplicate_controls() is False


def test_has_duplicate_controls_ignores_zero_ids():
    # id 0 means "no control id" (owner-drawn / unlabeled); those are matched by
    # position, so repeated zeros are not a collapse and must not be flagged.
    zeros = BoxCalibration(
        boxes={s: BoxControl(0, "Edit", 0.1 * i, 0.1 * i) for i, s in enumerate(SOAP_SECTIONS)}
    )
    assert zeros.has_duplicate_controls() is False


# --- descriptor_from_capture -------------------------------------------------


def test_descriptor_from_capture_stores_position_relative_to_parent():
    # parent window spans screen (100,200)->(500,600): 400 wide, 400 tall.
    box = descriptor_from_capture(
        control_id=42,
        class_name="Edit",
        parent_rect=(100, 200, 500, 600),
        screen_x=200,  # 100px into a 400px-wide window -> 0.25
        screen_y=400,  # 200px into a 400px-tall window -> 0.5
    )
    assert box.control_id == 42
    assert box.class_name == "Edit"
    assert box.rel_x == pytest.approx(0.25)
    assert box.rel_y == pytest.approx(0.5)


def test_descriptor_from_capture_clamps_out_of_bounds_points():
    box = descriptor_from_capture(1, "Edit", (0, 0, 100, 100), screen_x=-20, screen_y=250)
    assert box.rel_x == 0.0
    assert box.rel_y == 1.0


def test_descriptor_from_capture_handles_zero_area_parent():
    # degenerate rect must not divide by zero
    box = descriptor_from_capture(1, "Edit", (10, 10, 10, 10), screen_x=10, screen_y=10)
    assert box.rel_x == 0.0
    assert box.rel_y == 0.0


# --- choose_control ----------------------------------------------------------

PARENT = (0, 0, 1000, 1000)


def test_choose_control_prefers_a_unique_control_id_match():
    box = BoxControl(control_id=1007, class_name="Edit", rel_x=0.9, rel_y=0.9)
    candidates = [
        _candidate(10, 1007, "Edit", (0, 0, 50, 50)),   # far from rel pos, but id matches
        _candidate(20, 2000, "Edit", (890, 890, 950, 950)),
    ]
    # control-id wins over position: it's the stable key.
    assert choose_control(candidates, box, PARENT) == 10


def test_choose_control_breaks_id_ties_by_class_then_position():
    box = BoxControl(control_id=1007, class_name="RichEdit20W", rel_x=0.1, rel_y=0.1)
    candidates = [
        _candidate(10, 1007, "Edit", (0, 0, 100, 100)),            # same id, wrong class
        _candidate(20, 1007, "RichEdit20W", (50, 50, 150, 150)),   # same id, right class
    ]
    assert choose_control(candidates, box, PARENT) == 20


def test_choose_control_ignores_zero_control_id_and_uses_position():
    # control_id 0 is what Windows hands unlabeled controls -- not a stable key,
    # so fall straight to position matching.
    box = BoxControl(control_id=0, class_name="Edit", rel_x=0.8, rel_y=0.8)
    candidates = [
        _candidate(10, 0, "Edit", (0, 0, 100, 100)),
        _candidate(20, 0, "Edit", (700, 700, 900, 900)),  # contains (800,800)
    ]
    assert choose_control(candidates, box, PARENT) == 20


def test_choose_control_position_fallback_picks_the_containing_control():
    box = BoxControl(control_id=999, class_name="Edit", rel_x=0.3, rel_y=0.3)
    candidates = [
        _candidate(10, 111, "Edit", (0, 0, 400, 400)),      # contains (300,300)
        _candidate(20, 222, "Edit", (500, 500, 900, 900)),
    ]
    # no id match (999 absent) -> position; point (300,300) lands in hwnd 10.
    assert choose_control(candidates, box, PARENT) == 10


def test_choose_control_position_fallback_prefers_the_innermost_container():
    box = BoxControl(control_id=0, class_name="Edit", rel_x=0.5, rel_y=0.5)
    candidates = [
        _candidate(10, 0, "Panel", (0, 0, 1000, 1000)),   # outer, also contains (500,500)
        _candidate(20, 0, "Edit", (400, 400, 600, 600)),  # inner, smaller
    ]
    assert choose_control(candidates, box, PARENT) == 20


def test_choose_control_falls_back_to_nearest_center_when_none_contains_point():
    box = BoxControl(control_id=0, class_name="Edit", rel_x=0.5, rel_y=0.5)  # target (500,500)
    candidates = [
        _candidate(10, 0, "Edit", (0, 0, 100, 100)),        # center (50,50)
        _candidate(20, 0, "Edit", (400, 400, 480, 480)),    # center (440,440) -> closest
    ]
    assert choose_control(candidates, box, PARENT) == 20


def test_choose_control_returns_none_when_no_candidates():
    box = BoxControl(control_id=1, class_name="Edit", rel_x=0.5, rel_y=0.5)
    assert choose_control([], box, PARENT) is None


# --- CalibrationSession ------------------------------------------------------

from vet_soap_notetaker.avimark_calibration import CalibrationSession  # noqa: E402


def _fake_capture(x, y):
    # stand-in for injector.capture_calibration_box: encode the click into the box
    return BoxControl(control_id=x, class_name="Edit", rel_x=0.0, rel_y=0.0)


def test_session_starts_on_the_first_section():
    session = CalibrationSession(capture_fn=_fake_capture)
    assert session.current_section == "subjective"
    assert session.is_complete() is False
    assert session.progress == (0, 4)


def test_session_records_clicks_and_advances_through_sections():
    session = CalibrationSession(capture_fn=_fake_capture)

    assert session.record_click(11, 0) == "subjective"
    assert session.current_section == "objective"
    assert session.progress == (1, 4)

    session.record_click(22, 0)
    session.record_click(33, 0)
    assert session.current_section == "plan"

    session.record_click(44, 0)
    assert session.is_complete() is True
    assert session.current_section is None
    assert session.progress == (4, 4)


def test_session_result_rehydrates_a_full_calibration():
    session = CalibrationSession(capture_fn=_fake_capture)
    for i, _ in enumerate(SOAP_SECTIONS, start=1):
        session.record_click(i * 100, 0)

    result = session.result()
    assert isinstance(result, BoxCalibration)
    assert result.is_complete()
    # each section captured the control id from its own click
    assert result.get("subjective").control_id == 100
    assert result.get("plan").control_id == 400


def test_session_result_before_complete_raises():
    session = CalibrationSession(capture_fn=_fake_capture)
    session.record_click(1, 0)
    with pytest.raises(RuntimeError):
        session.result()


def test_session_record_click_after_complete_raises():
    session = CalibrationSession(capture_fn=_fake_capture)
    for i in range(4):
        session.record_click(i, 0)
    with pytest.raises(RuntimeError):
        session.record_click(99, 0)
