"""Tests for the Windows per-monitor DPI helpers.

The real work is ctypes against user32/shcore, which only exists on Windows; here
we pin the pure mapping and the off-Windows no-op behaviour (so the Linux suite and
the fallbacks stay correct), and drive the Windows paths through a fake DLL.
"""

from vet_soap_notetaker import dpi


def test_awareness_name_maps_known_codes():
    assert dpi._awareness_name(0) == "UNAWARE"
    assert dpi._awareness_name(1) == "SYSTEM_AWARE"
    assert dpi._awareness_name(2) == "PER_MONITOR_AWARE"


def test_awareness_name_falls_back_for_unknown_code():
    assert dpi._awareness_name(99) == "code=99"


def test_current_awareness_is_unknown_without_windows(mocker):
    mocker.patch.object(dpi, "_user32", return_value=None)
    assert dpi.current_awareness() == "unknown"


def test_describe_point_is_unavailable_without_windows(mocker):
    mocker.patch.object(dpi, "_user32", return_value=None)
    mocker.patch.object(dpi, "_shcore", return_value=None)
    # never raises, even though win32/ctypes isn't here
    assert dpi.describe_point(10, 20) == "unavailable"


class _FakeUser32:
    """Records SetThreadDpiAwarenessContext calls and hands back a prior handle."""

    def __init__(self):
        self.calls = []

    def SetThreadDpiAwarenessContext(self, ctx):
        self.calls.append(ctx)
        return "previous-ctx"  # what the OS returns: the context that was in effect


def test_physical_pixels_sets_per_monitor_v2_then_restores(mocker):
    fake = _FakeUser32()
    mocker.patch.object(dpi, "_user32", return_value=fake)

    with dpi.physical_pixels():
        # entered: switched this thread to Per-Monitor-v2
        assert fake.calls == [dpi._PER_MONITOR_AWARE_V2]

    # exited: restored whatever was in effect before
    assert fake.calls == [dpi._PER_MONITOR_AWARE_V2, "previous-ctx"]


def test_physical_pixels_is_a_noop_without_windows(mocker):
    mocker.patch.object(dpi, "_user32", return_value=None)
    entered = False
    with dpi.physical_pixels():
        entered = True
    assert entered  # yields and never raises off Windows


def test_physical_pixels_restores_even_if_body_raises(mocker):
    fake = _FakeUser32()
    mocker.patch.object(dpi, "_user32", return_value=fake)

    try:
        with dpi.physical_pixels():
            raise ValueError("boom")
    except ValueError:
        pass

    assert fake.calls == [dpi._PER_MONITOR_AWARE_V2, "previous-ctx"]


def test_current_awareness_reads_the_thread_context(mocker):
    class FakeUser32:
        def GetThreadDpiAwarenessContext(self):
            return "ctx-handle"

        def GetAwarenessFromDpiAwarenessContext(self, ctx):
            assert ctx == "ctx-handle"
            return 1  # SYSTEM_AWARE

    mocker.patch.object(dpi, "_user32", return_value=FakeUser32())
    assert dpi.current_awareness() == "SYSTEM_AWARE"
