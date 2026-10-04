import sys
import winreg

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "VetSoapNotetakerAssistant"


def default_launch_command() -> str:
    return f'"{sys.executable}" -m vet_soap_notetaker.main'


def enable(launch_command: str):
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command)


def disable():
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        pass


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ
        ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False
