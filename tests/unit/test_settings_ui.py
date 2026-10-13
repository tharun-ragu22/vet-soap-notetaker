import tkinter

import pytest

from vet_soap_notetaker.config import Config
from vet_soap_notetaker.settings_ui import SettingsWindow


@pytest.fixture
def tk_root():
    root = tkinter.Tk()
    root.withdraw()
    yield root
    root.destroy()


def make_config(**overrides):
    defaults = dict(
        api_endpoint="https://vet_soap_notetaker.example.com/api/soap",
        api_timeout_seconds=30,
        hotkey="<ctrl>+<shift>+r",
        api_key="",
        target_window_matcher="AVImark",
        launch_on_startup=False,
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_settings_window_prefills_fields_from_config(tk_root):
    config = make_config(
        api_endpoint="https://vet_soap_notetaker.example.com/api/soap",
        api_key="secret",
        hotkey="<ctrl>+<alt>+v",
        target_window_matcher="PracticeSoft",
        launch_on_startup=True,
    )

    window = SettingsWindow(master=tk_root, config=config, on_save=lambda c: None)

    assert window.endpoint_var.get() == "https://vet_soap_notetaker.example.com/api/soap"
    assert window.api_key_var.get() == "secret"
    assert window.hotkey_var.get() == "<ctrl>+<alt>+v"
    assert window.target_window_var.get() == "PracticeSoft"
    assert window.launch_on_startup_var.get() is True


def test_save_button_builds_config_from_edited_form_and_calls_on_save(tk_root):
    config = make_config()
    saved = []
    window = SettingsWindow(master=tk_root, config=config, on_save=saved.append)

    window.endpoint_var.set("https://new-endpoint.example.com/soap")
    window.api_key_var.set("new-secret")
    window.hotkey_var.set("<ctrl>+<alt>+r")
    window.target_window_var.set("PracticeSoft")
    window.launch_on_startup_var.set(True)

    window.save_button.invoke()

    assert len(saved) == 1
    new_config = saved[0]
    assert new_config.api_endpoint == "https://new-endpoint.example.com/soap"
    assert new_config.api_key == "new-secret"
    assert new_config.hotkey == "<ctrl>+<alt>+r"
    assert new_config.target_window_matcher == "PracticeSoft"
    assert new_config.launch_on_startup is True
    assert new_config.api_timeout_seconds == config.api_timeout_seconds


def test_save_button_destroys_window(tk_root):
    config = make_config()
    window = SettingsWindow(master=tk_root, config=config, on_save=lambda c: None)

    window.save_button.invoke()

    assert not window.winfo_exists()


def test_settings_window_edits_the_analytics_fields(tk_root):
    config = make_config(
        analytics_key="phc_old", analytics_user_id="test-tharun", analytics_environment="test"
    )
    saved = []
    window = SettingsWindow(master=tk_root, config=config, on_save=saved.append)

    assert window.analytics_key_var.get() == "phc_old"
    assert window.analytics_user_id_var.get() == "test-tharun"
    assert window.analytics_environment_var.get() == "test"

    window.analytics_key_var.set(" phc_new ")
    window.analytics_user_id_var.set(" demo-vet-1 ")
    window.analytics_environment_var.set("demo")
    window.save_button.invoke()

    # Surrounding whitespace from a paste is trimmed.
    assert saved[0].analytics_key == "phc_new"
    assert saved[0].analytics_user_id == "demo-vet-1"
    assert saved[0].analytics_environment == "demo"
