import sys

from vet_soap_notetaker.autostart import (
    APP_NAME,
    RUN_KEY_PATH,
    AUTOSTART_FLAG,
    add_autostart_flag,
    default_launch_command,
    disable,
    enable,
    is_enabled,
    read_command,
)


def test_default_launch_command_uses_current_interpreter_and_module_entrypoint():
    command = default_launch_command()

    assert sys.executable in command
    assert "vet_soap_notetaker.main" in command


def test_default_launch_command_marks_the_launch_as_autostart():
    # A login launch must stay quiet; a manual launch opens History.
    assert default_launch_command().endswith(f" {AUTOSTART_FLAG}")


def test_enable_sets_registry_value_with_launch_command(mocker):
    mock_winreg = mocker.patch("vet_soap_notetaker.autostart.winreg")
    mock_key = mocker.MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key

    enable(r"C:\Program Files\Vet Soap Notetaker\VetSoapNotetaker.exe")

    mock_winreg.OpenKey.assert_called_once_with(
        mock_winreg.HKEY_CURRENT_USER,
        RUN_KEY_PATH,
        0,
        mock_winreg.KEY_SET_VALUE,
    )
    mock_winreg.SetValueEx.assert_called_once_with(
        mock_key,
        APP_NAME,
        0,
        mock_winreg.REG_SZ,
        r"C:\Program Files\Vet Soap Notetaker\VetSoapNotetaker.exe",
    )


def test_disable_deletes_registry_value(mocker):
    mock_winreg = mocker.patch("vet_soap_notetaker.autostart.winreg")
    mock_key = mocker.MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key

    disable()

    mock_winreg.DeleteValue.assert_called_once_with(mock_key, APP_NAME)


def test_disable_does_not_raise_when_value_does_not_exist(mocker):
    mock_winreg = mocker.patch("vet_soap_notetaker.autostart.winreg")
    mock_key = mocker.MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
    mock_winreg.DeleteValue.side_effect = FileNotFoundError()

    disable()


def test_disable_does_not_raise_when_key_does_not_exist(mocker):
    mock_winreg = mocker.patch("vet_soap_notetaker.autostart.winreg")
    mock_winreg.OpenKey.side_effect = FileNotFoundError()

    disable()


def test_is_enabled_returns_true_when_value_present(mocker):
    mock_winreg = mocker.patch("vet_soap_notetaker.autostart.winreg")
    mock_key = mocker.MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
    mock_winreg.QueryValueEx.return_value = (r"C:\path\VetSoapNotetaker.exe", 1)

    assert is_enabled() is True


def test_is_enabled_returns_false_when_value_missing(mocker):
    mock_winreg = mocker.patch("vet_soap_notetaker.autostart.winreg")
    mock_key = mocker.MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
    mock_winreg.QueryValueEx.side_effect = FileNotFoundError()

    assert is_enabled() is False


def test_is_enabled_returns_false_when_key_missing(mocker):
    mock_winreg = mocker.patch("vet_soap_notetaker.autostart.winreg")
    mock_winreg.OpenKey.side_effect = FileNotFoundError()

    assert is_enabled() is False


def _registry(mocker, command):
    mock_winreg = mocker.patch("vet_soap_notetaker.autostart.winreg")
    mock_key = mocker.MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
    if command is None:
        mock_winreg.QueryValueEx.side_effect = FileNotFoundError()
    else:
        mock_winreg.QueryValueEx.return_value = (command, 1)
    return mock_winreg, mock_key


def test_read_command_returns_the_registered_command_or_none(mocker):
    _registry(mocker, r'"C:\app\VetSoapNotetaker.exe"')
    assert read_command() == r'"C:\app\VetSoapNotetaker.exe"'
    _registry(mocker, None)
    assert read_command() is None


def test_add_autostart_flag_upgrades_an_entry_from_an_older_install(mocker):
    mock_winreg, mock_key = _registry(mocker, r'"C:\app\VetSoapNotetaker.exe"')

    add_autostart_flag()

    mock_winreg.SetValueEx.assert_called_once_with(
        mock_key, APP_NAME, 0, mock_winreg.REG_SZ,
        rf'"C:\app\VetSoapNotetaker.exe" {AUTOSTART_FLAG}',
    )


def test_add_autostart_flag_leaves_a_current_or_missing_entry_alone(mocker):
    mock_winreg, _ = _registry(mocker, rf'"C:\app\VetSoapNotetaker.exe" {AUTOSTART_FLAG}')
    add_autostart_flag()
    mock_winreg.SetValueEx.assert_not_called()

    mock_winreg, _ = _registry(mocker, None)
    add_autostart_flag()
    mock_winreg.SetValueEx.assert_not_called()
