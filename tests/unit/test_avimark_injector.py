from vetscribe.avimark_injector import AvimarkInjector


def test_is_avimark_foreground_returns_true_when_title_contains_avimark(mocker):
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mock_win32gui.GetForegroundWindow.return_value = 12345
    mock_win32gui.GetWindowText.return_value = "AVImark - [Patient: Max (Golden Retriever)]"

    injector = AvimarkInjector()

    assert injector.is_avimark_foreground() is True
    mock_win32gui.GetWindowText.assert_called_once_with(12345)


def test_is_avimark_foreground_returns_false_for_other_windows(mocker):
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mock_win32gui.GetForegroundWindow.return_value = 999
    mock_win32gui.GetWindowText.return_value = "Notepad"

    injector = AvimarkInjector()

    assert injector.is_avimark_foreground() is False


def test_is_avimark_foreground_uses_configured_title_marker(mocker):
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mock_win32gui.GetForegroundWindow.return_value = 12345
    mock_win32gui.GetWindowText.return_value = "PracticeSoft - [Patient: Max]"

    injector = AvimarkInjector(title_marker="PracticeSoft")

    assert injector.is_avimark_foreground() is True

    default_injector = AvimarkInjector()
    assert default_injector.is_avimark_foreground() is False


def test_copy_to_clipboard_opens_empties_sets_and_closes_clipboard(mocker):
    mock_win32clipboard = mocker.patch("vetscribe.avimark_injector.win32clipboard")

    injector = AvimarkInjector()
    injector.copy_to_clipboard("SUBJECTIVE: patient is doing well.")

    mock_win32clipboard.OpenClipboard.assert_called_once_with()
    mock_win32clipboard.EmptyClipboard.assert_called_once_with()
    mock_win32clipboard.SetClipboardText.assert_called_once_with(
        "SUBJECTIVE: patient is doing well.", mock_win32clipboard.CF_UNICODETEXT
    )
    mock_win32clipboard.CloseClipboard.assert_called_once_with()


def test_inject_returns_false_and_does_not_copy_when_avimark_not_foreground(mocker):
    mocker.patch.object(AvimarkInjector, "is_avimark_foreground", return_value=False)
    mock_copy = mocker.patch.object(AvimarkInjector, "copy_to_clipboard")

    injector = AvimarkInjector()
    result = injector.inject("SOAP TEXT")

    assert result is False
    mock_copy.assert_not_called()


def test_inject_copies_and_sends_ctrl_v_when_avimark_foreground(mocker):
    mocker.patch.object(AvimarkInjector, "is_avimark_foreground", return_value=True)
    mock_copy = mocker.patch.object(AvimarkInjector, "copy_to_clipboard")
    mock_win32api = mocker.patch("vetscribe.avimark_injector.win32api")
    mocker.patch("vetscribe.avimark_injector.win32con")

    injector = AvimarkInjector()
    result = injector.inject("SOAP TEXT")

    assert result is True
    mock_copy.assert_called_once_with("SOAP TEXT")
    assert mock_win32api.keybd_event.call_count == 4


def _fake_enum_windows(windows):
    """side_effect for win32gui.EnumWindows that feeds it the given hwnds."""

    def enum(callback, results):
        for hwnd in windows:
            callback(hwnd, results)

    return enum


def test_find_avimark_window_returns_matching_visible_window(mocker):
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mock_win32gui.EnumWindows.side_effect = _fake_enum_windows([111, 222])
    mock_win32gui.IsWindowVisible.return_value = True
    mock_win32gui.GetWindowText.side_effect = (
        lambda hwnd: "AVImark - [Patient]" if hwnd == 111 else "Notepad"
    )

    injector = AvimarkInjector()

    assert injector.find_avimark_window() == 111


def test_find_avimark_window_ignores_invisible_windows(mocker):
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mock_win32gui.EnumWindows.side_effect = _fake_enum_windows([111])
    mock_win32gui.IsWindowVisible.return_value = False
    mock_win32gui.GetWindowText.return_value = "AVImark - [Patient]"

    injector = AvimarkInjector()

    assert injector.find_avimark_window() is None


def test_focus_and_inject_raises_avimark_then_copies_and_pastes(mocker):
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mock_win32api = mocker.patch("vetscribe.avimark_injector.win32api")
    mocker.patch("vetscribe.avimark_injector.win32con")
    mock_copy = mocker.patch.object(AvimarkInjector, "copy_to_clipboard")

    mock_win32gui.EnumWindows.side_effect = _fake_enum_windows([111])
    mock_win32gui.IsWindowVisible.return_value = True
    mock_win32gui.GetWindowText.return_value = "AVImark - [Patient: Max]"
    mock_win32gui.IsIconic.return_value = False
    # After SetForegroundWindow, AVImark is the foreground window.
    mock_win32gui.GetForegroundWindow.return_value = 111

    injector = AvimarkInjector()
    result = injector.focus_and_inject("SOAP TEXT")

    assert result is True
    mock_win32gui.SetForegroundWindow.assert_called_once_with(111)
    mock_copy.assert_called_once_with("SOAP TEXT")
    assert mock_win32api.keybd_event.call_count == 4


def test_focus_and_inject_restores_a_minimized_avimark_window(mocker):
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mocker.patch("vetscribe.avimark_injector.win32api")
    mock_win32con = mocker.patch("vetscribe.avimark_injector.win32con")
    mocker.patch.object(AvimarkInjector, "copy_to_clipboard")

    mock_win32gui.EnumWindows.side_effect = _fake_enum_windows([111])
    mock_win32gui.IsWindowVisible.return_value = True
    mock_win32gui.GetWindowText.return_value = "AVImark"
    mock_win32gui.IsIconic.return_value = True
    mock_win32gui.GetForegroundWindow.return_value = 111

    injector = AvimarkInjector()
    injector.focus_and_inject("SOAP TEXT")

    mock_win32gui.ShowWindow.assert_called_once_with(111, mock_win32con.SW_RESTORE)


def test_focus_and_inject_returns_false_when_no_avimark_window(mocker):
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mock_copy = mocker.patch.object(AvimarkInjector, "copy_to_clipboard")

    mock_win32gui.EnumWindows.side_effect = _fake_enum_windows([222])
    mock_win32gui.IsWindowVisible.return_value = True
    mock_win32gui.GetWindowText.return_value = "Notepad"

    injector = AvimarkInjector()
    result = injector.focus_and_inject("SOAP TEXT")

    assert result is False
    mock_copy.assert_not_called()
    mock_win32gui.SetForegroundWindow.assert_not_called()


def test_focus_and_inject_does_not_paste_if_focus_does_not_take(mocker):
    # SetForegroundWindow can be refused by Windows; never paste unless AVImark
    # genuinely ended up in the foreground, so the note can't hit another app.
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mocker.patch("vetscribe.avimark_injector.win32con")
    mock_copy = mocker.patch.object(AvimarkInjector, "copy_to_clipboard")

    mock_win32gui.EnumWindows.side_effect = _fake_enum_windows([111])
    mock_win32gui.IsWindowVisible.return_value = True
    mock_win32gui.GetWindowText.side_effect = (
        lambda hwnd: "AVImark" if hwnd == 111 else "Some Other App"
    )
    mock_win32gui.IsIconic.return_value = False
    # Focus didn't take: a different window is still foreground.
    mock_win32gui.GetForegroundWindow.return_value = 999

    injector = AvimarkInjector()
    result = injector.focus_and_inject("SOAP TEXT")

    assert result is False
    mock_copy.assert_not_called()


def test_remember_active_window_records_foreground_avimark(mocker):
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mock_win32gui.GetForegroundWindow.return_value = 111
    mock_win32gui.GetWindowText.return_value = "AVImark - [Patient: Max]"

    injector = AvimarkInjector()
    injector.remember_active_window()

    assert injector.target_hwnd == 111


def test_remember_active_window_clears_target_when_foreground_not_avimark(mocker):
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mock_win32gui.GetForegroundWindow.return_value = 999
    mock_win32gui.GetWindowText.return_value = "Notepad"

    injector = AvimarkInjector()
    injector.target_hwnd = 111  # a stale target from an earlier flyout
    injector.remember_active_window()

    assert injector.target_hwnd is None


def test_track_active_window_updates_target_to_foreground_avimark(mocker):
    # The vet switched to a different AVImark chart while the flyout was open;
    # tracking follows them to it.
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mock_win32gui.GetForegroundWindow.return_value = 222
    mock_win32gui.GetWindowText.return_value = "AVImark - [Patient: Bella]"

    injector = AvimarkInjector()
    injector.target_hwnd = 111
    injector.track_active_window()

    assert injector.target_hwnd == 222


def test_track_active_window_keeps_last_target_when_foreground_not_avimark(mocker):
    # Our own flyout (or any non-AVImark window) is in front: don't drop the
    # chart the vet was last in, so Copy & Inject still has a target.
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mock_win32gui.GetForegroundWindow.return_value = 999
    mock_win32gui.GetWindowText.return_value = "VetScribe note"

    injector = AvimarkInjector()
    injector.target_hwnd = 111
    injector.track_active_window()

    assert injector.target_hwnd == 111


def test_focus_and_inject_pastes_into_remembered_chart_among_many(mocker):
    # Two AVImark charts are open (111 and 222). The vet was in 222 when the
    # flyout appeared, so we must paste there -- not into whichever window
    # EnumWindows happens to list first.
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mocker.patch("vetscribe.avimark_injector.win32api")
    mocker.patch("vetscribe.avimark_injector.win32con")
    mock_copy = mocker.patch.object(AvimarkInjector, "copy_to_clipboard")

    mock_win32gui.IsWindow.return_value = True
    mock_win32gui.IsIconic.return_value = False
    mock_win32gui.GetWindowText.return_value = "AVImark - [Patient: Bella]"
    mock_win32gui.GetForegroundWindow.return_value = 222

    injector = AvimarkInjector()
    injector.target_hwnd = 222
    result = injector.focus_and_inject("SOAP TEXT")

    assert result is True
    mock_win32gui.SetForegroundWindow.assert_called_once_with(222)
    # The remembered chart is used directly; we don't fall back to enumeration.
    mock_win32gui.EnumWindows.assert_not_called()
    mock_copy.assert_called_once_with("SOAP TEXT")


def test_focus_and_inject_refuses_when_multiple_charts_and_none_remembered(mocker):
    # No remembered target and two AVImark charts open: we can't tell which
    # patient is meant, so refuse to paste and leave the note on the clipboard.
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mock_copy = mocker.patch.object(AvimarkInjector, "copy_to_clipboard")

    mock_win32gui.EnumWindows.side_effect = _fake_enum_windows([111, 222])
    mock_win32gui.IsWindowVisible.return_value = True
    mock_win32gui.GetWindowText.side_effect = (
        lambda hwnd: "AVImark - [Patient: Max]" if hwnd == 111 else "AVImark - [Patient: Bella]"
    )

    injector = AvimarkInjector()
    result = injector.focus_and_inject("SOAP TEXT")

    assert result is False
    mock_win32gui.SetForegroundWindow.assert_not_called()
    # Note is staged on the clipboard so the vet can focus the right chart and
    # paste it manually.
    mock_copy.assert_called_once_with("SOAP TEXT")


def test_focus_and_inject_falls_back_when_remembered_window_closed(mocker):
    # The remembered chart was closed before the vet clicked Copy & Inject.
    # With only one AVImark window now open, fall back to it.
    mock_win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    mocker.patch("vetscribe.avimark_injector.win32api")
    mocker.patch("vetscribe.avimark_injector.win32con")
    mocker.patch.object(AvimarkInjector, "copy_to_clipboard")

    mock_win32gui.IsWindow.return_value = False  # remembered hwnd is gone
    mock_win32gui.EnumWindows.side_effect = _fake_enum_windows([333])
    mock_win32gui.IsWindowVisible.return_value = True
    mock_win32gui.GetWindowText.return_value = "AVImark - [Patient: Rex]"
    mock_win32gui.IsIconic.return_value = False
    mock_win32gui.GetForegroundWindow.return_value = 333

    injector = AvimarkInjector()
    injector.target_hwnd = 222
    result = injector.focus_and_inject("SOAP TEXT")

    assert result is True
    mock_win32gui.SetForegroundWindow.assert_called_once_with(333)
