import json
import sys
import tkinter as tk
from pathlib import Path

WINDOW_TITLE = "AVImark - [Patient: Max (Golden Retriever)]"
# Separate title for the multi-box SOAP window so both mocks can match the
# injector's "AVImark" title marker while the tests target the right one.
SOAP_WINDOW_TITLE = "AVImark - [SOAP: Max (Golden Retriever)]"

# The boxes the real AVImark SOAP entry screen exposes, in top-to-bottom order.
SOAP_FIELD_LABELS = ("Subjective", "Objective", "Assessment", "Plan")


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


class MockAvimarkSoapWindow(tk.Tk):
    """A stand-in for AVImark's SOAP entry screen with one box per section.

    Mirrors how a real multi-field form behaves for the keyboard-navigation
    injection path: four stacked text boxes with Tab moving focus from one to
    the next (a Text widget normally inserts a literal tab, so we rebind it).
    On every edit it dumps all four boxes' contents to ``dump_path`` as a JSON
    list, so the acceptance test can assert each SOAP section landed in its own
    box.
    """

    def __init__(self, dump_path=None):
        super().__init__()
        self.title(SOAP_WINDOW_TITLE)
        self.dump_path = Path(dump_path) if dump_path else None
        self.boxes = []
        for index, label in enumerate(SOAP_FIELD_LABELS):
            tk.Label(self, text=label, anchor="w").pack(fill="x")
            box = tk.Text(self, height=3, width=60)
            box.pack(fill="both", expand=True)
            # Tab/Shift-Tab move between boxes instead of inserting a tab char.
            box.bind("<Tab>", self._make_focus_handler(index, step=1))
            box.bind("<Shift-Tab>", self._make_focus_handler(index, step=-1))
            if self.dump_path is not None:
                box.bind("<<Modified>>", self._on_box_modified)
            self.boxes.append(box)
        self.boxes[0].focus_force()

    def _make_focus_handler(self, index, step):
        def handler(event):
            target = index + step
            if 0 <= target < len(self.boxes):
                self.boxes[target].focus_set()
            return "break"  # prevent the default tab-character insert

        return handler

    def _on_box_modified(self, event):
        event.widget.edit_modified(False)
        self._dump()

    def _dump(self):
        contents = [box.get("1.0", "end-1c") for box in self.boxes]
        self.dump_path.write_text(json.dumps(contents))


def main():
    args = sys.argv[1:]
    soap = "--soap" in args
    positional = [a for a in args if not a.startswith("--")]
    dump_path = positional[0] if positional else None
    app = MockAvimarkSoapWindow(dump_path=dump_path) if soap else MockAvimarkWindow(dump_path=dump_path)
    app.mainloop()


if __name__ == "__main__":
    main()
