import tkinter as tk
from dataclasses import replace

from vet_soap_notetaker import ui_strings
from vet_soap_notetaker.window_icon import apply_window_icon


class SettingsWindow(tk.Toplevel):
    def __init__(self, master, config, on_save):
        super().__init__(master)
        self.title(ui_strings.SETTINGS_WINDOW_TITLE)
        apply_window_icon(self)
        self.config = config
        self.on_save = on_save

        self.endpoint_var = tk.StringVar(value=config.api_endpoint)
        self.api_key_var = tk.StringVar(value=config.api_key)
        self.hotkey_var = tk.StringVar(value=config.hotkey)
        self.target_window_var = tk.StringVar(value=config.target_window_matcher)
        self.launch_on_startup_var = tk.BooleanVar(value=config.launch_on_startup)

        tk.Label(self, text=ui_strings.LABEL_API_ENDPOINT).pack()
        self.endpoint_entry = tk.Entry(self, textvariable=self.endpoint_var)
        self.endpoint_entry.pack()

        tk.Label(self, text=ui_strings.LABEL_API_KEY).pack()
        self.api_key_entry = tk.Entry(self, textvariable=self.api_key_var, show="*")
        self.api_key_entry.pack()

        tk.Label(self, text=ui_strings.LABEL_HOTKEY).pack()
        self.hotkey_entry = tk.Entry(self, textvariable=self.hotkey_var)
        self.hotkey_entry.pack()

        tk.Label(self, text=ui_strings.LABEL_TARGET_WINDOW).pack()
        self.target_window_entry = tk.Entry(self, textvariable=self.target_window_var)
        self.target_window_entry.pack()

        self.launch_on_startup_checkbox = tk.Checkbutton(
            self,
            text=ui_strings.LABEL_LAUNCH_ON_STARTUP,
            variable=self.launch_on_startup_var,
        )
        self.launch_on_startup_checkbox.pack()

        self.save_button = tk.Button(
            self, text=ui_strings.BUTTON_SAVE, command=self._on_save_clicked
        )
        self.save_button.pack()

    def _on_save_clicked(self):
        new_config = replace(
            self.config,
            api_endpoint=self.endpoint_var.get(),
            api_key=self.api_key_var.get(),
            hotkey=self.hotkey_var.get(),
            target_window_matcher=self.target_window_var.get(),
            launch_on_startup=self.launch_on_startup_var.get(),
        )
        self.on_save(new_config)
        self.destroy()
