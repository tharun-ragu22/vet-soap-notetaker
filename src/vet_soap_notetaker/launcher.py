"""The app's entrypoint (the exe's script): get a window up before the slow part.

Importing ``main`` pulls in numpy/scipy, sounddevice, pystray, httpx and the
rest, which takes seconds on a clinic PC. So this module imports only Tk and a
few small helpers, takes the single-instance lock, and puts the splash up
first; a second launch exits from here without ever loading ``main``. Keep the
imports light -- ``test_importing_the_launcher_skips_the_heavy_modules`` guards it.
"""

import logging
import sys
import tkinter as tk

from vet_soap_notetaker import autostart
from vet_soap_notetaker.activation import ACTIVATION_FILE_NAME, request_activation
from vet_soap_notetaker.loading_ui import LoadingWindow
from vet_soap_notetaker.logger import build_logger
from vet_soap_notetaker.paths import get_appdata_base_dir
from vet_soap_notetaker.single_instance import SingleInstance

logger = logging.getLogger("vet_soap_notetaker.launcher")


def _load_main():
    from vet_soap_notetaker import main

    return main


def run(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Login autostart passes the flag and stays quiet in the tray; a launch from
    # the desktop icon or Start menu opens History.
    autostarted = autostart.AUTOSTART_FLAG in argv
    build_logger()
    # Single-instance guard: if another copy is already running (autostart put one
    # up at login and the vet then double-clicked the icon), bow out rather than
    # start a second backend supervisor that would crash-loop fighting for the
    # backend port. The lock is released by the OS when this process exits.
    instance_lock = SingleInstance(get_appdata_base_dir() / "vet_soap_notetaker.lock")
    if not instance_lock.acquire():
        logger.info("another instance is already running; exiting this one")
        if not autostarted:
            # The vet clicked the icon to get at the app: the running one opens History.
            request_activation(get_appdata_base_dir() / ACTIVATION_FILE_NAME)
        return
    tk_root = tk.Tk()
    tk_root.withdraw()
    splash = None
    if not autostarted:
        splash = LoadingWindow(tk_root)
        splash.show()
    try:
        main = _load_main()
    except BaseException:
        if splash is not None:
            splash.close()
        raise
    if splash is not None:
        # An X click made during the imports has been waiting in the Tk queue.
        splash.update()
        if splash.cancelled:
            logger.info("splash closed while loading; exiting before startup")
            return
    main.start(tk_root, autostarted=autostarted, splash=splash, instance_lock=instance_lock)


if __name__ == "__main__":
    run()
