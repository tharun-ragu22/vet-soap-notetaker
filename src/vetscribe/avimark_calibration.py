"""AVImark SOAP-box calibration: the data model and the pure control-matching.

The vet's AVImark exam screen has four separate boxes (Subjective / Objective /
Assessment / Plan) and we can't know their layout in advance -- and we can't just
Tab between them, because unrelated checkboxes sit in the keyboard order. So the
desktop app is *calibrated* once per site: with AVImark's note window open, the vet
clicks inside each of the four boxes, and we record a stable descriptor of each
control (``BoxControl``). From then on, injection resolves each descriptor back to
the live control and pastes that section straight into its box.

This module is deliberately Win32-free. ``BoxControl`` / ``BoxCalibration`` are
plain serializable data (persisted in the desktop config), and ``choose_control``
is a pure function over a list of candidate controls the injector enumerates. The
actual Win32 work -- reading the control under the cursor, enumerating child
windows, focusing a control and pasting -- lives in ``avimark_injector`` where it
can be exercised against the mock window.
"""

from __future__ import annotations

from dataclasses import dataclass

# The four SOAP sections, in the order they're pasted down the form. Matches the
# keys used on the backend exam / SoapNote.
SOAP_SECTIONS = ("subjective", "objective", "assessment", "plan")


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


@dataclass(frozen=True)
class BoxControl:
    """A stable-ish descriptor of one AVImark box, captured during calibration.

    ``control_id`` (the Win32 dialog control id) is the primary key: it's stable
    across the window being re-created for a new patient, as long as AVImark's
    layout doesn't change. ``class_name`` tie-breaks when several controls share an
    id. ``rel_x`` / ``rel_y`` are the click position as a fraction of the parent
    window, used as a fallback when the id is missing (0) or ambiguous.
    """

    control_id: int
    class_name: str
    rel_x: float
    rel_y: float

    def to_dict(self) -> dict:
        return {
            "control_id": self.control_id,
            "class_name": self.class_name,
            "rel_x": self.rel_x,
            "rel_y": self.rel_y,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BoxControl":
        return cls(
            control_id=int(data["control_id"]),
            class_name=str(data["class_name"]),
            rel_x=float(data["rel_x"]),
            rel_y=float(data["rel_y"]),
        )


@dataclass(frozen=True)
class BoxCalibration:
    """The captured boxes, keyed by SOAP section."""

    boxes: dict[str, BoxControl]

    def get(self, section: str) -> BoxControl | None:
        return self.boxes.get(section)

    def is_complete(self) -> bool:
        return all(section in self.boxes for section in SOAP_SECTIONS)

    def to_dict(self) -> dict:
        return {section: box.to_dict() for section, box in self.boxes.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "BoxCalibration":
        return cls(boxes={section: BoxControl.from_dict(d) for section, d in data.items()})


class CalibrationSession:
    """Drives capturing the four boxes, one click at a time.

    Pure orchestration: it holds the current section, calls ``capture_fn`` (the
    injector's ``capture_calibration_box``) on each click, and assembles the
    result. The UI layer owns the window and the mouse hook; it reads
    ``current_section`` for the prompt and calls ``record_click`` per click.
    """

    def __init__(self, capture_fn):
        self._capture = capture_fn
        self._index = 0
        self._boxes: dict[str, BoxControl] = {}

    @property
    def current_section(self) -> str | None:
        if self._index < len(SOAP_SECTIONS):
            return SOAP_SECTIONS[self._index]
        return None

    @property
    def progress(self) -> tuple[int, int]:
        """(boxes captured so far, total)."""
        return (self._index, len(SOAP_SECTIONS))

    def is_complete(self) -> bool:
        return self._index >= len(SOAP_SECTIONS)

    def record_click(self, screen_x: int, screen_y: int) -> str:
        """Capture the current section's box from a click; return that section."""
        if self.is_complete():
            raise RuntimeError("calibration already complete")
        section = SOAP_SECTIONS[self._index]
        self._boxes[section] = self._capture(screen_x, screen_y)
        self._index += 1
        return section

    def result(self) -> "BoxCalibration":
        if not self.is_complete():
            raise RuntimeError("calibration is not complete")
        return BoxCalibration(boxes=dict(self._boxes))


def descriptor_from_capture(
    control_id: int,
    class_name: str,
    parent_rect: tuple[int, int, int, int],
    screen_x: int,
    screen_y: int,
) -> BoxControl:
    """Build a ``BoxControl`` from a calibration click.

    ``parent_rect`` is the top-level AVImark window's screen rect ``(l, t, r, b)``;
    the click position is stored relative to it so it survives the window moving or
    being recreated at a different screen position.
    """
    left, top, right, bottom = parent_rect
    width = right - left
    height = bottom - top
    rel_x = _clamp01((screen_x - left) / width) if width else 0.0
    rel_y = _clamp01((screen_y - top) / height) if height else 0.0
    return BoxControl(control_id=control_id, class_name=class_name, rel_x=rel_x, rel_y=rel_y)


def _area(rect: tuple[int, int, int, int]) -> int:
    left, top, right, bottom = rect
    return max(0, right - left) * max(0, bottom - top)


def _contains(rect: tuple[int, int, int, int], x: float, y: float) -> bool:
    left, top, right, bottom = rect
    return left <= x <= right and top <= y <= bottom


def _center(rect: tuple[int, int, int, int]) -> tuple[float, float]:
    left, top, right, bottom = rect
    return (left + right) / 2.0, (top + bottom) / 2.0


def _closest_by_position(candidates, box: BoxControl, parent_rect):
    """Pick the candidate nearest the calibrated position.

    Preference order: the smallest control whose rect *contains* the target point
    (the innermost box, not the panel around it); failing that, the control whose
    center is nearest the target.
    """
    if not candidates:
        return None
    left, top, right, bottom = parent_rect
    target_x = left + box.rel_x * (right - left)
    target_y = top + box.rel_y * (bottom - top)

    containing = [c for c in candidates if _contains(c["rect"], target_x, target_y)]
    if containing:
        return min(containing, key=lambda c: _area(c["rect"]))["hwnd"]

    def _distance(c):
        cx, cy = _center(c["rect"])
        return (cx - target_x) ** 2 + (cy - target_y) ** 2

    return min(candidates, key=_distance)["hwnd"]


def choose_control(candidates, box: BoxControl, parent_rect):
    """Resolve a calibrated ``box`` to one of the live ``candidates``' hwnds.

    ``candidates`` is a list of ``{"hwnd", "control_id", "class_name", "rect"}``
    (rect is the control's screen rect). Returns the chosen hwnd, or ``None`` if
    there are no candidates at all. Strategy: a non-zero control id is the stable
    key, tie-broken by class then position; otherwise fall back to position.
    """
    if box.control_id:
        id_matches = [c for c in candidates if c["control_id"] == box.control_id]
        if len(id_matches) == 1:
            return id_matches[0]["hwnd"]
        if id_matches:
            class_matches = [c for c in id_matches if c["class_name"] == box.class_name]
            return _closest_by_position(class_matches or id_matches, box, parent_rect)
    return _closest_by_position(candidates, box, parent_rect)
