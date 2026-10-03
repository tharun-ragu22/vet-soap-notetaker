import sys
import tkinter as tk
from pathlib import Path

WINDOW_TITLE = "AVImark - [Patient: Max (Golden Retriever)]"


class MockAvimarkWindow(tk.Tk):
    def __init__(self, dump_path=None):
        # Tk root creation retries transient Windows bootstrap failures
        # centrally (see tests/conftest.py), so this can just construct
        # normally.
        super().__init__()
        self.title(WINDOW_TITLE)
        self.dump_path = Path(dump_path) if dump_path else None
        self.text_widget = tk.Text(self)
        self.text_widget.pack(fill="both", expand=True)
        self.text_widget.focus_force()
        if self.dump_path is not None:
            self.text_widget.bind("<<Modified>>", self._on_text_modified)

    def _on_text_modified(self, event):
        self.text_widget.edit_modified(False)
        self.dump_path.write_text(self.text_widget.get("1.0", "end-1c"))


def main():
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    dump_path = positional[0] if positional else None
    app = MockAvimarkWindow(dump_path=dump_path)
    app.mainloop()


if __name__ == "__main__":
    main()
