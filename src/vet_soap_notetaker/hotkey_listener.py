import logging
import threading

from pynput import keyboard

logger = logging.getLogger("vet_soap_notetaker.hotkey_listener")

HOTKEY = "<ctrl>+<shift>+r"


class HotkeyListener:
    def __init__(self, on_trigger, hotkey=HOTKEY):
        self.on_trigger = on_trigger
        self.hotkey = hotkey
        self._lock = threading.Lock()
        self._listener = None
        self._required_keys = frozenset()
        self._pressed = set()
        self._active = False

    def start(self):
        self._required_keys = frozenset(keyboard.HotKey.parse(self.hotkey))
        self._pressed = set()
        self._active = False
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        logger.info("listening for hotkey %s", self.hotkey)

    def stop(self):
        if self._listener is not None:
            self._listener.stop()

    def update_hotkey(self, new_hotkey):
        was_running = self._listener is not None
        self.hotkey = new_hotkey
        if was_running:
            self.stop()
            self.start()

    def _on_press(self, key):
        canonical_key = self._listener.canonical(key)
        with self._lock:
            self._pressed.add(canonical_key)
            # Only fire on the edge where the combo newly becomes fully held.
            # OS key-repeat re-sends press events for keys already held down,
            # which would otherwise cause extra triggers (and extra
            # start/stop toggles) for a single physical press. Requiring a
            # full release of the combo (see _on_release) before allowing
            # another trigger makes this immune to repeat timing entirely.
            if self._active or not (self._required_keys <= self._pressed):
                return
            self._active = True
        self._handle_trigger()

    def _on_release(self, key):
        canonical_key = self._listener.canonical(key)
        with self._lock:
            self._pressed.discard(canonical_key)
            if not (self._required_keys <= self._pressed):
                self._active = False

    def _handle_trigger(self):
        with self._lock:
            logger.info("hotkey %s triggered", self.hotkey)
            self.on_trigger()
