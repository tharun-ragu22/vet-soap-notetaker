import logging
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path

import pyperclip

from vet_soap_notetaker import autostart
from vet_soap_notetaker.api_client import ApiClient, SoapNote
from vet_soap_notetaker.audio_recorder import AudioRecorder
from vet_soap_notetaker.avimark_calibration import SOAP_SECTIONS, BoxCalibration
from vet_soap_notetaker.avimark_injector import AvimarkInjector
from vet_soap_notetaker.calibration_ui import CalibrationController, prompt_window_position
from vet_soap_notetaker.config import Config
from vet_soap_notetaker.flyout_ui import FlyoutWindow
from vet_soap_notetaker.backend_history_store import BackendHistoryStore
from vet_soap_notetaker.history_ui import HistoryWindow
from vet_soap_notetaker.hotkey_listener import HotkeyListener
from vet_soap_notetaker.backend_supervisor import (
    BackendSupervisor,
    default_backend_launch,
    find_bundled_backend,
)
from vet_soap_notetaker.injection_poller import InjectionPoller
from vet_soap_notetaker.logger import build_logger
from vet_soap_notetaker.offline_queue import OfflineQueue
from vet_soap_notetaker.paths import get_appdata_base_dir
from vet_soap_notetaker.pipeline import Pipeline, format_soap_text
from vet_soap_notetaker.settings_ui import SettingsWindow
from vet_soap_notetaker.single_instance import SingleInstance
from vet_soap_notetaker import ui_strings
from vet_soap_notetaker.tray_app import TrayApp
from vet_soap_notetaker.window_icon import apply_window_icon

# Win32 is only present on Windows (stubbed in tests); the app only runs for real
# there. Used to hit-test calibration clicks against our own window in physical
# pixels -- the same coordinate space pynput and WindowFromPoint use.
import win32gui

# GetAncestor(..., GA_ROOT=2) walks a window handle up to its top-level window.
_GA_ROOT = 2

logger = logging.getLogger("vet_soap_notetaker.main")

CONFIG_PATH = Path.home() / ".vetscribe" / "config.json"


def _load_calibration(config):
    """Rehydrate the saved AVImark box calibration, or None if not calibrated."""
    if not config.avimark_calibration:
        return None
    return BoxCalibration.from_dict(config.avimark_calibration)


def _section_fields(note):
    """The SOAP note as ordered (section, text) pairs for per-box injection."""
    return [(section, getattr(note, section)) for section in SOAP_SECTIONS]


def inject_note(injector, calibration, note, on_fallback=None):
    """Inject a note into AVImark: per-box when calibrated, else single-block.

    Shared by the mobile Inject path, the History window's Inject, and the
    hotkey flyout so they place the note the same way. ``note`` is anything with
    ``subjective``/``objective``/``assessment``/``plan`` attributes (a SoapNote
    or an Exam). Per-box degrades to a single-block paste when the calibration
    can't be resolved; if no AVImark chart is safely targetable the inject
    refuses and ``on_fallback`` (the Safety Flyout) is offered the note instead.
    Returns whether the note landed in AVImark.
    """
    soap_text = format_soap_text(note)
    if calibration is not None:
        # Per-box: paste each section straight into its calibrated AVImark box.
        # Degrades gracefully -- if the boxes can't be resolved it still lands
        # the whole note as one block (soap_text) into the focused box, and only
        # returns False when no AVImark chart is safely targetable.
        injected = injector.focus_and_inject_fields_calibrated(
            _section_fields(note), calibration, soap_text
        )
    else:
        injected = injector.focus_and_inject(soap_text)
    if not injected and on_fallback is not None:
        on_fallback(soap_text)
    return injected


def _point_in_window(window, x, y):
    """Whether screen point (x, y) falls inside a Tk window's current bounds.

    Used during calibration to ignore clicks on our own instruction window.
    Best-effort: if the geometry can't be read, treat the point as outside.
    """
    try:
        left = window.winfo_rootx()
        top = window.winfo_rooty()
        right = left + window.winfo_width()
        bottom = top + window.winfo_height()
    except Exception:
        return False
    return left <= x <= right and top <= y <= bottom


def _click_is_on_window(window, x, y):
    """Whether a global click at screen point (x, y) landed on our Tk ``window``.

    Used during calibration to ignore clicks on our own instruction window so
    they aren't mistaken for an AVImark box. Hit-tests with ``WindowFromPoint``,
    which works in physical pixels -- the same space pynput reports and
    ``capture_calibration_box`` uses -- so it stays correct under Windows display
    scaling (where Tk's logical geometry wouldn't line up) and also covers the
    window's title bar and borders. Falls back to a geometric bounds check where
    Win32 isn't available.
    """
    try:
        clicked_root = win32gui.GetAncestor(win32gui.WindowFromPoint((x, y)), _GA_ROOT)
        our_root = win32gui.GetAncestor(window.winfo_id(), _GA_ROOT)
        return clicked_root == our_root
    except Exception:
        return _point_in_window(window, x, y)


def run_on_main_thread(tk_root, fn):
    # Tkinter widgets may only be created on the thread running the mainloop.
    # Pipeline/offline-queue callbacks fire from background threads, so
    # marshal the work over via the thread-safe Tk event queue instead of
    # calling into Tk directly (which can hang indefinitely on some platforms).
    if threading.current_thread() is threading.main_thread():
        fn()
    else:
        tk_root.after(0, fn)


FOLLOW_ACTIVE_INTERVAL_MS = 250


def follow_active_avimark(tk_root, injector, window, interval_ms=FOLLOW_ACTIVE_INTERVAL_MS):
    # While a flyout / history window is open, keep re-capturing whichever
    # AVImark chart the vet is in, so "Copy & Inject" follows their latest
    # navigation and pastes into the chart they most recently switched to --
    # even with several AVImark windows open. Re-arms itself on the Tk event
    # loop and stops on its own once the window is gone.
    def track():
        if not window.winfo_exists():
            return
        injector.track_active_window()
        tk_root.after(interval_ms, track)

    tk_root.after(interval_ms, track)


CALIBRATION_FOREGROUND_INTERVAL_MS = 300


def keep_window_foreground(
    tk_root, window, interval_ms=CALIBRATION_FOREGROUND_INTERVAL_MS
):
    # Keep a Tk window on top of everything until it closes. AVImark becomes the
    # foreground window each time the vet clicks one of its boxes, which on Windows
    # can let it cover a plain topmost Toplevel; re-assert topmost and lift the
    # window on a timer so the calibration prompt stays visible through all four
    # clicks. Re-arms on the Tk event loop and stops on its own once the window is
    # gone (closed after the fourth box is captured).
    def tick():
        if not window.winfo_exists():
            return
        try:
            window.attributes("-topmost", True)
            window.lift()
        except tk.TclError:
            return
        tk_root.after(interval_ms, tick)

    tk_root.after(interval_ms, tick)


def show_flyout(tk_root, injector, soap_text, on_open_history=None):
    # Seed the target with the chart in front right now (before the flyout takes
    # focus); follow_active_avimark then keeps it current as the vet navigates.
    injector.remember_active_window()

    def on_copy_and_inject(text):
        # The flyout is a clicked window, so AVImark isn't foreground; actively
        # raise it and paste rather than using the strict inject() guard (which
        # is for the automatic post-hotkey path where AVImark is still focused).
        # ``text`` is the note as currently shown, so an edit made here isn't lost.
        injector.focus_and_inject(text)
        flyout.destroy()

    def on_copy_to_clipboard(text):
        pyperclip.copy(text)
        flyout.destroy()

    open_history = None
    if on_open_history is not None:
        # Close the transient popup as we hand the vet over to the full history
        # window (where they can read the transcript and older notes).
        def open_history():
            flyout.destroy()
            on_open_history()

    flyout = FlyoutWindow(
        master=tk_root,
        soap_text=soap_text,
        on_copy_and_inject=on_copy_and_inject,
        on_copy_to_clipboard=on_copy_to_clipboard,
        on_open_history=open_history,
    )
    follow_active_avimark(tk_root, injector, flyout)
    return flyout


def show_history(tk_root, injector, history_store, on_regenerate=None, on_inject=None):
    injector.remember_active_window()
    # Inject the (already-persisted) current note; the window hands over the
    # structured entry so build_app's callback can place it per-box via the
    # calibration. A single-block default keeps direct callers working.
    on_inject = on_inject or (lambda note: injector.focus_and_inject(note.soap_text))
    window = HistoryWindow(
        master=tk_root,
        load_entries=history_store.list_entries,
        on_copy_and_inject=on_inject,
        on_copy_to_clipboard=lambda soap_text: pyperclip.copy(soap_text),
        on_save_edit=lambda entry_id, **fields: history_store.update(entry_id, **fields),
        on_delete=lambda entry_id: history_store.delete(entry_id),
        on_regenerate=on_regenerate,
    )
    follow_active_avimark(tk_root, injector, window)
    return window


def build_app(config=None, tk_root=None):
    config = config or Config.load(CONFIG_PATH)
    tk_root = tk_root or tk.Tk()
    tk_root.withdraw()
    apply_window_icon(tk_root)

    recorder = AudioRecorder()
    api_client = ApiClient(config.api_endpoint, config.api_timeout_seconds, config.api_key)
    injector = AvimarkInjector(title_marker=config.target_window_matcher)
    # The live AVImark box calibration (None until the vet calibrates). Held in a
    # mutable cell so Settings / the calibration flow can swap it in without
    # rebuilding the app, same pattern as current_config below.
    current_calibration = {"value": _load_calibration(config)}
    # The shared exam history lives on the backend (the same records the mobile
    # app reads); a local cache keeps History usable through a brief outage.
    history_store = BackendHistoryStore(api_client)

    def regenerate_from_transcript(transcript):
        # Blocking backend call; HistoryWindow runs this on a worker thread and
        # marshals the result back to the Tk loop itself. Returns the structured
        # note so the window can repopulate its four SOAP fields.
        return api_client.regenerate_soap_note(transcript)

    def open_history():
        show_history(
            tk_root,
            injector,
            history_store,
            on_regenerate=regenerate_from_transcript,
            # Inject the note currently selected/edited in History the same way
            # the mobile Inject does: per-box when calibrated, with the Safety
            # Flyout as the fallback when no chart is safely targetable.
            on_inject=lambda note: inject_note(
                injector,
                current_calibration["value"],
                note,
                on_fallback=show_note_flyout,
            ),
        )

    # A note flyout offers an "Open History" button; an error flyout doesn't
    # (there's no note to browse), so it goes through show_flyout directly.
    def show_note_flyout(soap_text):
        show_flyout(
            tk_root,
            injector,
            soap_text,
            on_open_history=open_history,
        )

    offline_queue = OfflineQueue(
        api_client=api_client,
        on_note_ready=lambda soap_text: run_on_main_thread(
            tk_root, lambda: show_note_flyout(soap_text)
        ),
    )

    def handle_remote_injection(request):
        # A mobile "Inject into AVImark" tap: build the note text from the exam
        # the backend attached to the request, then reuse the exact same safety
        # path as the flyout's Copy & Inject -- actively raise AVImark and paste
        # only into a genuinely-targetable chart. If we can't safely target one
        # (no AVImark window, or several open with no remembered chart),
        # focus_and_inject refuses; fall back to the Safety Flyout with the note
        # ready rather than risk the wrong patient's chart. Runs on the main
        # thread (marshalled below) because it touches Win32 and Tk.
        exam = request.get("exam") or {}
        note = SoapNote(
            subjective=exam.get("subjective", ""),
            objective=exam.get("objective", ""),
            assessment=exam.get("assessment", ""),
            plan=exam.get("plan", ""),
            transcript=exam.get("transcript", ""),
        )
        inject_note(
            injector,
            current_calibration["value"],
            note,
            on_fallback=show_note_flyout,
        )

    injection_poller = InjectionPoller(
        api_client=api_client,
        on_injection=lambda request: run_on_main_thread(
            tk_root, lambda: handle_remote_injection(request)
        ),
    )

    pipeline = Pipeline(
        recorder=recorder,
        api_client=api_client,
        injector=injector,
        on_flyout_needed=lambda soap_text: run_on_main_thread(
            tk_root, lambda: show_note_flyout(soap_text)
        ),
        on_error=lambda message: run_on_main_thread(
            tk_root, lambda: show_flyout(tk_root, injector, message)
        ),
        offline_queue=offline_queue,
    )

    tray_app = TrayApp(
        pipeline=pipeline,
        on_show_note=lambda soap_text: run_on_main_thread(
            tk_root, lambda: show_note_flyout(soap_text)
        ),
        on_show_history=lambda: run_on_main_thread(tk_root, open_history),
    )
    pipeline.on_state_change = lambda state: tray_app.update_icon_for_state()
    tray_app.attach_offline_queue(offline_queue)
    tray_app.attach_injection_poller(injection_poller)

    # On the packaged clinic appliance the desktop app also owns the backend's
    # lifecycle: it launches the bundled backend exe and relaunches it if it
    # dies, so one autostart entry (this app) brings the whole stack up after a
    # reboot. In a dev checkout there's no bundled exe, so the supervisor stays
    # off and the separately-run backend (setup.ps1 / uv run) is left alone.
    backend_exe = find_bundled_backend()
    backend_supervisor = BackendSupervisor(
        launch=default_backend_launch(backend_exe) if backend_exe else None
    )
    tray_app.attach_backend_supervisor(backend_supervisor)
    tray_app.attach_tk_root(tk_root)

    def dispatch_hotkey_trigger():
        # tray_app.on_hotkey_triggered() runs the full pipeline synchronously,
        # including the blocking backend call. HotkeyListener invokes this
        # callback directly on the OS-level global keyboard hook thread, and a
        # slow low-level keyboard hook stalls key delivery system-wide until
        # it returns -- any real keypresses during that stall get queued by
        # Windows and replayed once we return, which can re-fire the hotkey
        # without the user actually holding it down at that moment. Hand the
        # work off to a worker thread so the hook callback returns instantly.
        threading.Thread(target=tray_app.on_hotkey_triggered, daemon=True).start()

    hotkey_listener = HotkeyListener(
        on_trigger=dispatch_hotkey_trigger, hotkey=config.hotkey
    )
    tray_app.attach_hotkey_listener(hotkey_listener)

    current_config = {"value": config}

    def apply_settings(new_config):
        new_config.save(CONFIG_PATH)
        api_client.endpoint = new_config.api_endpoint
        api_client.timeout_seconds = new_config.api_timeout_seconds
        api_client.api_key = new_config.api_key
        injector.title_marker = new_config.target_window_matcher
        hotkey_listener.update_hotkey(new_config.hotkey)
        current_calibration["value"] = _load_calibration(new_config)
        if new_config.launch_on_startup:
            autostart.enable(autostart.default_launch_command())
        else:
            autostart.disable()
        current_config["value"] = new_config

    def open_settings():
        SettingsWindow(master=tk_root, config=current_config["value"], on_save=apply_settings)

    def apply_calibration(calibration):
        # Persist the finished calibration and make it live for the next inject,
        # without rebuilding the app. Runs on the main thread (the calibration
        # controller's clicks are marshalled there).
        new_config = replace(
            current_config["value"], avimark_calibration=calibration.to_dict()
        )
        new_config.save(CONFIG_PATH)
        current_config["value"] = new_config
        current_calibration["value"] = calibration
        logger.info("AVImark calibration saved")

    def start_calibration():
        # One-time setup: a small always-on-top window prompts the vet to click in
        # each SOAP box; a global mouse hook feeds each click to the controller,
        # which captures the control under the cursor. Both the window and the hook
        # are torn down by close() once all four boxes are captured. Must run on
        # the main thread (Tk + Win32).
        from pynput import mouse

        window = tk.Toplevel(tk_root)
        window.title(ui_strings.CALIBRATION_TITLE)
        window.attributes("-topmost", True)
        label = tk.Label(window, text="", justify="left", padx=20, pady=20, wraplength=360)
        label.pack()
        # Park the prompt in the bottom-right corner, away from the top-left where
        # AVImark's note window sits -- otherwise, on a small screen, this window
        # lands on top of a box and the click-filter below silently swallows every
        # click there (calibration looks frozen). It stays draggable if it still
        # overlaps (e.g. a maximized AVImark). Size must be realised first.
        window.update_idletasks()
        x, y = prompt_window_position(
            window.winfo_screenwidth(),
            window.winfo_screenheight(),
            window.winfo_width(),
            window.winfo_height(),
        )
        window.geometry(f"+{x}+{y}")
        # Keep the prompt on top through all four clicks: each click into AVImark
        # makes it the foreground window, which can otherwise cover this Toplevel.
        keep_window_foreground(tk_root, window)

        listener = {"value": None}

        def prompt(section, done, total):
            label.config(
                text=ui_strings.calibration_prompt(section, done, total)
            )

        def warn_prompt_covered():
            label.config(text=ui_strings.CALIBRATION_PROMPT_COVERED)

        def close():
            if listener["value"] is not None:
                listener["value"].stop()
            window.destroy()

        controller = CalibrationController(
            capture=injector.capture_calibration_box,
            save=apply_calibration,
            prompt=prompt,
            close=close,
            warn=warn_prompt_covered,
        )

        def on_click(x, y, button, pressed):
            # Capture the box on a left-button *press*. A click that lands on our
            # own instruction window isn't a box -- but rather than drop it
            # silently (which made calibration look frozen when the window covered
            # a box), tell the vet to drag the window aside. The click still falls
            # through to whatever is underneath either way.
            if not pressed or button != mouse.Button.left:
                return
            if _click_is_on_window(window, x, y):
                run_on_main_thread(tk_root, controller.on_click_on_prompt)
                return
            run_on_main_thread(tk_root, lambda: controller.on_click(x, y))

        listener["value"] = mouse.Listener(on_click=on_click)
        listener["value"].start()
        controller.start()

    tray_app.on_calibrate = lambda: run_on_main_thread(tk_root, start_calibration)

    # The tray menu fires on the pystray icon thread, so -- like on_show_note /
    # on_show_history above -- constructing the Tk window must be marshalled onto
    # the main thread; a direct Tk construction from the tray thread deadlocks
    # (hard-to-kill hang, no traceback), especially while another window's
    # follow_active_avimark after-loop is keeping the Tcl interpreter busy.
    tray_app.on_open_settings = lambda: run_on_main_thread(tk_root, open_settings)

    return tray_app, hotkey_listener, tk_root


def run():
    build_logger()
    # Single-instance guard: if another copy is already running (autostart put one
    # up at login and the vet then double-clicked the icon), bow out rather than
    # start a second backend supervisor that would crash-loop fighting for the
    # backend port. The lock is released by the OS when this process exits.
    instance_lock = SingleInstance(get_appdata_base_dir() / "vet_soap_notetaker.lock")
    if not instance_lock.acquire():
        logger.info("another instance is already running; exiting this one")
        return
    logger.info("Vet Soap Notetaker starting up")
    tray_app, hotkey_listener, tk_root = build_app()
    # Bring the backend up first (no-op in dev) so it's listening before the
    # pollers below start reaching for it.
    tray_app.backend_supervisor.start()
    hotkey_listener.start()
    tray_app.offline_queue.start()
    tray_app.injection_poller.start()
    logger.info("offline retry queue and remote-injection poller started, ready for hotkey")
    # Run the tray icon on its own thread so the main thread is free to run
    # the Tk mainloop, which is required for flyout/settings windows to be
    # created safely (Tk calls from other threads must go through the
    # mainloop, see run_on_main_thread above).
    tray_app.icon.run_detached()
    tk_root.mainloop()


if __name__ == "__main__":
    run()
