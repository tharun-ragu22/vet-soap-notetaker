import dataclasses
import logging
import threading
import tkinter as tk
from tkinter import messagebox

from vet_soap_notetaker import ui_strings
from vet_soap_notetaker.window_icon import apply_window_icon

logger = logging.getLogger("vet_soap_notetaker.history_ui")

DEFAULT_WIDTH = 760
DEFAULT_HEIGHT = 640
# How often an open window re-reads the store so notes recorded (on this desktop
# or on the phone) while it's open appear without the vet reopening it. The read
# goes through the backend-backed store on the Tk event loop.
DEFAULT_POLL_INTERVAL_MS = 1000

# The four structured SOAP fields, in display order, paired with their labels.
# Both apps edit these same fields so edits sync cleanly across devices.
_SOAP_FIELDS = (
    ("subjective", ui_strings.LABEL_SUBJECTIVE),
    ("objective", ui_strings.LABEL_OBJECTIVE),
    ("assessment", ui_strings.LABEL_ASSESSMENT),
    ("plan", ui_strings.LABEL_PLAN),
)


class HistoryWindow(tk.Toplevel):
    def __init__(
        self,
        master,
        load_entries,
        on_copy_and_inject,
        on_copy_to_clipboard,
        on_save_edit=None,
        on_delete=None,
        on_regenerate=None,
        confirm_delete=None,
        poll_interval_ms=DEFAULT_POLL_INTERVAL_MS,
    ):
        super().__init__(master)
        self.title(ui_strings.HISTORY_WINDOW_TITLE)
        apply_window_icon(self)
        self.geometry(f"{DEFAULT_WIDTH}x{DEFAULT_HEIGHT}")
        self._load_entries = load_entries
        self.on_copy_and_inject = on_copy_and_inject
        self.on_copy_to_clipboard = on_copy_to_clipboard
        self.on_save_edit = on_save_edit or (
            lambda entry_id, **fields: None
        )
        self.on_delete = on_delete or (lambda entry_id: None)
        # Blocking call (transcript in -> SoapNote out) that hits the backend;
        # run off the Tk thread so the window stays responsive.
        self.on_regenerate = on_regenerate
        self._regenerating = False
        self._confirm_delete = confirm_delete or self._default_confirm_delete
        self.entries = list(load_entries())
        self._selected_index = None

        # Left: scrollable list of past notes, newest first.
        list_frame = tk.Frame(self)
        list_frame.pack(side="left", fill="y")
        self.listbox = tk.Listbox(list_frame, width=32)
        self.listbox.pack(side="left", fill="y", expand=True)
        scrollbar = tk.Scrollbar(list_frame, command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=scrollbar.set)
        self.listbox.bind("<<ListboxSelect>>", self._on_listbox_select)

        # Right: the selected note's four SOAP fields and its transcript, each
        # separately editable (matching the phone's editor so edits sync).
        detail_frame = tk.Frame(self)
        detail_frame.pack(side="right", fill="both", expand=True)

        self.field_texts = {}
        for key, label in _SOAP_FIELDS:
            tk.Label(detail_frame, text=label).pack(anchor="w")
            widget = tk.Text(detail_frame, height=3, wrap="word")
            widget.pack(fill="both", expand=True)
            self.field_texts[key] = widget

        tk.Label(detail_frame, text=ui_strings.LABEL_TRANSCRIPT).pack(anchor="w")
        self.transcript_text = tk.Text(detail_frame, height=6, wrap="word")
        self.transcript_text.pack(fill="both", expand=True)

        button_frame = tk.Frame(detail_frame)
        button_frame.pack(fill="x")
        self.save_button = tk.Button(
            button_frame,
            text=ui_strings.BUTTON_SAVE_CHANGES,
            command=self._on_save_clicked,
        )
        self.save_button.pack(side="left")
        # Only offered when the app wires up a regenerate callback.
        self.regenerate_button = None
        if self.on_regenerate is not None:
            self.regenerate_button = tk.Button(
                button_frame,
                text=ui_strings.BUTTON_REGENERATE,
                command=self._on_regenerate_clicked,
            )
            self.regenerate_button.pack(side="left")
        self.copy_and_inject_button = tk.Button(
            button_frame,
            text=ui_strings.BUTTON_COPY_AND_INJECT,
            command=self._on_copy_and_inject_clicked,
        )
        self.copy_and_inject_button.pack(side="left")
        self.copy_to_clipboard_button = tk.Button(
            button_frame,
            text=ui_strings.BUTTON_COPY_SOAP_NOTE,
            command=self._on_copy_to_clipboard_clicked,
        )
        self.copy_to_clipboard_button.pack(side="left")
        self.delete_button = tk.Button(
            button_frame,
            text=ui_strings.BUTTON_DELETE_NOTE,
            command=self._on_delete_clicked,
        )
        self.delete_button.pack(side="right")

        self._populate_listbox()
        # Show the newest note by default so the window is useful on open.
        if self.entries:
            self._select(0)

        # Auto-refresh so notes recorded while the window is open show up live.
        self._poll_interval_ms = poll_interval_ms
        self._poll_job = None
        self.bind("<Destroy>", self._on_destroy)
        if poll_interval_ms:
            self._schedule_poll()

    @staticmethod
    def _row_label(entry) -> str:
        # Prefer the patient's name when the backend has one (phone-captured
        # exams do); otherwise fall back to a snippet of the subjective.
        preview = (entry.patient_name or entry.subjective or "").replace("\n", " ")
        if len(preview) > 40:
            preview = preview[:39] + "…"
        return f"{entry.created_at}  {preview}"

    def _all_text_widgets(self):
        return list(self.field_texts.values()) + [self.transcript_text]

    def _populate_listbox(self):
        self.listbox.delete(0, "end")
        for entry in self.entries:
            self.listbox.insert("end", self._row_label(entry))

    def refresh(self):
        """Re-read the store and reflect any notes added since the last read.

        Synchronous (fetch + apply, on the calling thread); used by direct
        callers like the delete path. The timer-driven poll instead reads the
        store on a worker thread (see ``_poll``) and marshals the result into
        ``_apply_entries``, so the backend round-trip never stalls the Tk loop.
        """
        self._apply_entries(list(self._load_entries()))

    def _apply_entries(self, new_entries):
        """Reflect a freshly-read entry list into the widgets. Must run on the Tk
        main thread -- either directly from ``refresh`` or marshalled off the
        poll worker via ``after``.

        If the vet is viewing the newest note (or nothing yet), advance to the
        just-recorded note; if they've deliberately opened an older note, keep
        their selection so they aren't yanked away mid-read. An in-progress
        unsaved edit is never overwritten -- the list still updates around it.
        """
        if new_entries == self.entries:
            return

        dirty = self._has_unsaved_edits()
        viewing_newest = self._selected_index in (None, 0)
        previously_selected = self._selected_entry()

        self.entries = new_entries
        self._populate_listbox()

        if not self.entries:
            self._selected_index = None
            if not dirty:
                self._clear_fields()
                self._mark_clean()
            return

        if dirty and previously_selected is not None:
            # Keep the vet's half-typed edit on screen; just keep the list
            # selection pointed at the same note without repainting the panes.
            target = self._index_of(previously_selected)
            if target is None:
                target = min(self._selected_index or 0, len(self.entries) - 1)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(target)
            self._selected_index = target
            return

        if viewing_newest:
            target = 0
        else:
            target = self._index_of(previously_selected)
            if target is None:
                target = 0
        self._select(target)

    def _index_of(self, entry):
        # Match on the stable id so an edit (which changes the note's content)
        # doesn't lose the vet's place.
        if entry is None:
            return None
        for index, candidate in enumerate(self.entries):
            if candidate.id == entry.id:
                return index
        return None

    def _select(self, index):
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.show_entry(index)

    def show_entry(self, index):
        entry = self.entries[index]
        self._selected_index = index
        for key, widget in self.field_texts.items():
            self._replace_text(widget, getattr(entry, key))
        self._replace_text(self.transcript_text, entry.transcript)
        self._mark_clean()

    def _clear_fields(self):
        for widget in self._all_text_widgets():
            self._replace_text(widget, "")

    def _mark_clean(self):
        # Reset the widgets' modified flags so programmatic population isn't
        # mistaken for a vet edit.
        for widget in self._all_text_widgets():
            widget.edit_modified(False)

    def _has_unsaved_edits(self) -> bool:
        return any(widget.edit_modified() for widget in self._all_text_widgets())

    def _on_save_clicked(self):
        if self._selected_entry() is None:
            return
        self._persist_current_edits()

    def _persist_current_edits(self):
        """Save the on-screen fields and return the entry reflecting them.

        Returns the persisted entry when the backend accepts the write (so the
        next auto-refresh sees no change and doesn't repaint), or an entry built
        locally from the current fields if the backend is unreachable -- so
        callers (Save, and Inject) always get the vet's *current* content, never
        the last-saved content. The caller guarantees a note is selected.
        """
        entry = self._selected_entry()
        fields = {
            key: widget.get("1.0", "end-1c") for key, widget in self.field_texts.items()
        }
        transcript = self.transcript_text.get("1.0", "end-1c")
        updated = self.on_save_edit(entry.id, transcript=transcript, **fields)
        self._mark_clean()
        if updated is not None and self._selected_index is not None:
            self.entries[self._selected_index] = updated
            return updated
        # Backend unreachable (update returned None): reflect the edits locally
        # so inject still carries them even though the save didn't land.
        return dataclasses.replace(entry, transcript=transcript, **fields)

    def _on_regenerate_clicked(self):
        if self.on_regenerate is None or self._regenerating:
            return
        entry = self._selected_entry()
        if entry is None:
            return
        transcript = self.transcript_text.get("1.0", "end-1c")
        if not transcript.strip():
            messagebox.showinfo(
                ui_strings.REGENERATE_EMPTY_TITLE,
                ui_strings.REGENERATE_EMPTY_MESSAGE,
                parent=self,
            )
            return

        # Remember which note we're regenerating so a late result is dropped if
        # the vet has since selected a different note.
        entry_id = entry.id
        self._set_regenerating(True)

        def work():
            try:
                note = self.on_regenerate(transcript)
            except Exception as exc:  # noqa: BLE001 -- surfaced to the vet below
                # Bind exc as a default arg: Python clears the `except ... as`
                # name when the block exits, before this after() callback runs.
                self.after(0, lambda err=exc: self._on_regenerate_failed(err))
                return
            self.after(0, lambda: self._on_regenerate_done(entry_id, note))

        threading.Thread(target=work, daemon=True).start()

    def _on_regenerate_done(self, entry_id, note):
        self._set_regenerating(False)
        current = self._selected_entry()
        if current is None or current.id != entry_id:
            # The vet moved to another note while the backend was working; the
            # regenerated note belongs to a note that's no longer on screen.
            return
        # Show the fresh note as an unsaved edit -- the vet reviews it and hits
        # Save Changes to persist, so regeneration is never destructive on its
        # own. Mark modified so the auto-refresh keeps the panes instead of
        # repainting them from the store.
        for key, widget in self.field_texts.items():
            self._replace_text(widget, getattr(note, key))
            widget.edit_modified(True)

    def _on_regenerate_failed(self, exc):
        self._set_regenerating(False)
        logger.warning("failed to regenerate SOAP note: %s", exc)
        messagebox.showerror(
            ui_strings.REGENERATE_ERROR_TITLE,
            ui_strings.REGENERATE_ERROR_MESSAGE.format(error=exc),
            parent=self,
        )

    def _set_regenerating(self, busy):
        self._regenerating = busy
        if self.regenerate_button is None:
            return
        try:
            self.regenerate_button.config(
                state="disabled" if busy else "normal",
                text=ui_strings.BUTTON_REGENERATE_BUSY
                if busy
                else ui_strings.BUTTON_REGENERATE,
            )
        except tk.TclError:
            # Window may have been destroyed between scheduling and running.
            pass

    def _default_confirm_delete(self, entry):
        from tkinter import messagebox

        return messagebox.askyesno(
            ui_strings.DELETE_CONFIRM_TITLE,
            ui_strings.DELETE_CONFIRM_MESSAGE,
            parent=self,
        )

    def _on_delete_clicked(self):
        entry = self._selected_entry()
        if entry is None:
            return
        if not self._confirm_delete(entry):
            return
        self.on_delete(entry.id)
        # Re-read the store rather than mutating locally, so what's shown always
        # matches what's persisted. Keep the vet near where they were: select the
        # note that slid into the deleted one's slot (or the new last note).
        deleted_index = self._selected_index or 0
        self.entries = list(self._load_entries())
        self._populate_listbox()
        if not self.entries:
            self._selected_index = None
            self._clear_fields()
            self._mark_clean()
            return
        self._select(min(deleted_index, len(self.entries) - 1))

    @staticmethod
    def _replace_text(widget, value):
        widget.delete("1.0", "end")
        widget.insert("1.0", value)

    def _on_listbox_select(self, _event):
        selection = self.listbox.curselection()
        if selection:
            self.show_entry(selection[0])

    def _selected_entry(self):
        if self._selected_index is None:
            return None
        return self.entries[self._selected_index]

    def _on_copy_and_inject_clicked(self):
        entry = self._selected_entry()
        if entry is None:
            return
        # Persist any in-progress edit first so what lands in AVImark is also
        # what's saved -- the vet shouldn't have to click Save Changes before
        # injecting. Hand the (current) structured note to the callback so it can
        # place each SOAP section into its own calibrated AVImark box.
        if self._has_unsaved_edits():
            entry = self._persist_current_edits()
        self.on_copy_and_inject(entry)

    def _on_copy_to_clipboard_clicked(self):
        entry = self._selected_entry()
        if entry is not None:
            self.on_copy_to_clipboard(entry.soap_text)

    def _schedule_poll(self):
        self._poll_job = self.after(self._poll_interval_ms, self._poll)

    def _poll(self):
        self._poll_job = None
        if not self.winfo_exists():
            return

        # Read the store on a worker thread: this fires on a 1s timer and the
        # read is a blocking backend GET, so doing it here on the Tk loop made
        # typing and clicking in the window stutter every second. The widget
        # update is marshalled back onto the main thread via after(). The next
        # poll is re-armed only once this one has applied, so slow reads can't
        # pile up overlapping requests.
        def work():
            try:
                new_entries = list(self._load_entries())
            except Exception:
                # A history read must never crash or kill the live-refresh loop.
                logger.exception("failed to refresh history window")
                new_entries = None
            try:
                self.after(0, lambda: self._on_poll_fetched(new_entries))
            except tk.TclError:
                # Window destroyed between the fetch and the marshal back.
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_poll_fetched(self, new_entries):
        if not self.winfo_exists():
            return
        if new_entries is not None:
            try:
                self._apply_entries(new_entries)
            except Exception:
                logger.exception("failed to apply refreshed history")
        if self._poll_interval_ms:
            self._schedule_poll()

    def _on_destroy(self, event):
        # Stop the poll loop when the window goes away so a pending `after`
        # callback never fires against a destroyed widget.
        if event.widget is self and self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None
