import threading
import time
from types import SimpleNamespace

from pynput import keyboard

from vet_soap_notetaker.hotkey_listener import HotkeyListener


def test_start_parses_ctrl_shift_r_hotkey_and_starts_listener(mocker):
    mock_listener_cls = mocker.patch("vet_soap_notetaker.hotkey_listener.keyboard.Listener")
    mock_listener = mock_listener_cls.return_value

    listener = HotkeyListener(on_trigger=lambda: None)
    listener.start()

    assert listener._required_keys == frozenset(keyboard.HotKey.parse("<ctrl>+<shift>+r"))
    _, kwargs = mock_listener_cls.call_args
    assert kwargs["on_press"] == listener._on_press
    assert kwargs["on_release"] == listener._on_release
    mock_listener.start.assert_called_once()


def test_start_uses_custom_hotkey_passed_at_construction(mocker):
    mocker.patch("vet_soap_notetaker.hotkey_listener.keyboard.Listener")

    listener = HotkeyListener(on_trigger=lambda: None, hotkey="<ctrl>+<alt>+v")
    listener.start()

    assert listener._required_keys == frozenset(keyboard.HotKey.parse("<ctrl>+<alt>+v"))


def test_update_hotkey_while_running_stops_old_listener_and_starts_new_binding(mocker):
    mock_listener_cls = mocker.patch("vet_soap_notetaker.hotkey_listener.keyboard.Listener")
    first_listener = mock_listener_cls.return_value

    listener = HotkeyListener(on_trigger=lambda: None)
    listener.start()

    second_listener = mocker.Mock()
    mock_listener_cls.return_value = second_listener

    listener.update_hotkey("<ctrl>+<alt>+v")

    first_listener.stop.assert_called_once()
    second_listener.start.assert_called_once()
    assert listener.hotkey == "<ctrl>+<alt>+v"
    assert listener._required_keys == frozenset(keyboard.HotKey.parse("<ctrl>+<alt>+v"))


def test_update_hotkey_when_not_started_only_updates_pending_hotkey(mocker):
    mock_listener_cls = mocker.patch("vet_soap_notetaker.hotkey_listener.keyboard.Listener")

    listener = HotkeyListener(on_trigger=lambda: None)
    listener.update_hotkey("<ctrl>+<alt>+v")

    mock_listener_cls.assert_not_called()
    assert listener.hotkey == "<ctrl>+<alt>+v"

    listener.start()

    assert listener._required_keys == frozenset(keyboard.HotKey.parse("<ctrl>+<alt>+v"))


def _make_listener(on_trigger, hotkey="<ctrl>+<shift>+r"):
    listener = HotkeyListener(on_trigger=on_trigger, hotkey=hotkey)
    listener._required_keys = frozenset(keyboard.HotKey.parse(hotkey))
    listener._pressed = set()
    listener._active = False
    # Identity canonicalization is enough here: the guard logic being tested
    # only cares about set membership, not pynput's real key normalization.
    listener._listener = SimpleNamespace(canonical=lambda key: key)
    return listener


def _press_combo(listener):
    for key in keyboard.HotKey.parse(listener.hotkey):
        listener._on_press(key)


def test_pressing_full_combo_triggers_once():
    calls = []
    listener = _make_listener(on_trigger=lambda: calls.append("triggered"))

    _press_combo(listener)

    assert calls == ["triggered"]


def test_os_key_repeat_while_held_does_not_retrigger():
    calls = []
    listener = _make_listener(on_trigger=lambda: calls.append("triggered"))
    keys = list(keyboard.HotKey.parse(listener.hotkey))

    _press_combo(listener)
    # Simulate the OS re-sending press events for the still-held keys, as
    # happens with key-repeat when a combo is held for more than an instant.
    for _ in range(5):
        for key in keys:
            listener._on_press(key)

    assert calls == ["triggered"]


def test_releasing_and_repressing_combo_triggers_again():
    calls = []
    listener = _make_listener(on_trigger=lambda: calls.append("triggered"))
    keys = list(keyboard.HotKey.parse(listener.hotkey))

    _press_combo(listener)
    for key in keys:
        listener._on_release(key)
    _press_combo(listener)

    assert calls == ["triggered", "triggered"]


def test_partial_combo_does_not_trigger():
    calls = []
    listener = _make_listener(on_trigger=lambda: calls.append("triggered"))
    keys = list(keyboard.HotKey.parse(listener.hotkey))

    for key in keys[:-1]:
        listener._on_press(key)

    assert calls == []


def test_handle_trigger_invokes_on_trigger_callback():
    calls = []
    listener = HotkeyListener(on_trigger=lambda: calls.append("triggered"))

    listener._handle_trigger()

    assert calls == ["triggered"]


def test_handle_trigger_serializes_concurrent_calls_across_threads():
    max_concurrent = 0
    current_concurrent = 0
    guard = threading.Lock()

    def slow_on_trigger():
        nonlocal max_concurrent, current_concurrent
        with guard:
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
        time.sleep(0.05)
        with guard:
            current_concurrent -= 1

    listener = HotkeyListener(on_trigger=slow_on_trigger)
    threads = [
        threading.Thread(target=listener._handle_trigger) for _ in range(5)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_concurrent == 1
