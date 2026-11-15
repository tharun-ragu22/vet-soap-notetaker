"""The launcher is the exe's entrypoint: it takes the single-instance lock and
puts the splash up *before* importing ``main`` (numpy/scipy, sounddevice,
pystray, httpx...), which is the slow part of a cold launch."""

import subprocess
import sys
from unittest.mock import MagicMock

import pytest

from vet_soap_notetaker import launcher


@pytest.fixture
def parts(mocker):
    mocker.patch("vet_soap_notetaker.launcher.build_logger")
    guard = MagicMock()
    guard.acquire.return_value = True
    mocker.patch("vet_soap_notetaker.launcher.SingleInstance", return_value=guard)
    request = mocker.patch("vet_soap_notetaker.launcher.request_activation")
    tk_cls = mocker.patch("vet_soap_notetaker.launcher.tk.Tk")
    splash_cls = mocker.patch("vet_soap_notetaker.launcher.LoadingWindow")
    splash_cls.return_value.cancelled = False
    main_module = MagicMock()
    load_main = mocker.patch("vet_soap_notetaker.launcher._load_main", return_value=main_module)
    # One recorder for call order across the pieces.
    order = MagicMock()
    order.attach_mock(splash_cls.return_value.show, "splash_show")
    order.attach_mock(load_main, "load_main")
    order.attach_mock(main_module.start, "start")
    return MagicMock(
        guard=guard,
        request=request,
        tk_root=tk_cls.return_value,
        splash_cls=splash_cls,
        splash=splash_cls.return_value,
        load_main=load_main,
        main=main_module,
        order=order,
    )


def test_a_second_manual_launch_asks_the_running_app_for_history_and_exits(parts):
    parts.guard.acquire.return_value = False

    launcher.run(argv=[])

    parts.request.assert_called_once()
    parts.load_main.assert_not_called()  # exits without the heavy imports
    parts.splash_cls.assert_not_called()


def test_a_second_autostart_launch_exits_quietly(parts):
    parts.guard.acquire.return_value = False

    launcher.run(argv=["--autostart"])

    parts.request.assert_not_called()
    parts.load_main.assert_not_called()


def test_a_manual_launch_shows_the_splash_before_loading_the_app(parts):
    launcher.run(argv=[])

    names = [c[0] for c in parts.order.mock_calls]
    assert names == ["splash_show", "load_main", "start"]
    parts.main.start.assert_called_once_with(
        parts.tk_root, autostarted=False, splash=parts.splash, instance_lock=parts.guard
    )


def test_an_autostart_launch_shows_no_splash(parts):
    launcher.run(argv=["--autostart"])

    parts.splash_cls.assert_not_called()
    parts.main.start.assert_called_once_with(
        parts.tk_root, autostarted=True, splash=None, instance_lock=parts.guard
    )


def test_the_splash_closes_if_the_app_fails_to_load(parts):
    parts.load_main.side_effect = ImportError("boom")

    with pytest.raises(ImportError):
        launcher.run(argv=[])

    parts.splash.close.assert_called_once()


def test_a_splash_closed_while_the_app_loads_exits_without_starting_it(parts):
    # The vet's X click waits in the Tk queue during the imports; the launcher
    # pumps it straight after, before anything (the backend) is started.
    parts.splash.update.side_effect = lambda: setattr(parts.splash, "cancelled", True)

    launcher.run(argv=[])

    parts.main.start.assert_not_called()


def test_importing_the_launcher_skips_the_heavy_modules():
    # The whole point of the launcher: a second launch, and the splash, must not
    # wait on these.
    heavy = ["numpy", "scipy", "sounddevice", "pystray", "httpx", "pynput", "vet_soap_notetaker.main"]
    code = (
        "import sys, types\n"
        "sys.modules.setdefault('winreg', types.ModuleType('winreg'))\n"
        "import vet_soap_notetaker.launcher\n"
        f"print([m for m in {heavy!r} if m in sys.modules])\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
