import logging
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from vet_soap_notetaker import ui_strings
from vet_soap_notetaker.api_client import ApiClientError, Exam, ExamDraft
from vet_soap_notetaker.appointment_merge import merge_regenerated
from vet_soap_notetaker.window_icon import apply_window_icon

logger = logging.getLogger("vet_soap_notetaker.history_ui")

DEFAULT_WIDTH = 940
DEFAULT_HEIGHT = 680
# How often an open window re-reads the store so recordings made (on this
# desktop or on the phone) while it's open appear without the vet reopening it.
# The read runs on a worker thread; see _poll.
DEFAULT_POLL_INTERVAL_MS = 1000

# The four structured SOAP fields, in display order, paired with their labels.
# Both apps edit these same fields so edits sync cleanly across devices.
_SOAP_FIELDS = (
    ("subjective", ui_strings.LABEL_SUBJECTIVE),
    ("objective", ui_strings.LABEL_OBJECTIVE),
    ("assessment", ui_strings.LABEL_ASSESSMENT),
    ("plan", ui_strings.LABEL_PLAN),
)

# Appointments with no transcript yet (phone uploads): a message, no tabs.
_NO_TRANSCRIPT_MESSAGES = {
    "processing": ui_strings.HISTORY_PROCESSING_MESSAGE,
    "no_speech": ui_strings.HISTORY_NO_SPEECH_MESSAGE,
    "failed": ui_strings.HISTORY_FAILED_MESSAGE,
}
_STATUS_SUFFIXES = {
    "processing": ui_strings.HISTORY_STATUS_PROCESSING,
    "failed": ui_strings.HISTORY_STATUS_FAILED,
    "no_speech": ui_strings.HISTORY_STATUS_NO_SPEECH,
    "note_pending": ui_strings.HISTORY_STATUS_NOTE_PENDING,
}


def format_created_at(value: str) -> str:
    """The appointment's time as the vet reads it, in local time."""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return value
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%Y-%m-%d %H:%M")


def display_name(patient_name, number) -> str:
    # An unnamed animal is numbered, as the backend and the phone do.
    return (patient_name or "").strip() or ui_strings.PATIENT_FALLBACK_NAME.format(number=number)


def row_label(appointment) -> str:
    """One History row: the animals' names, the time, how many animals, and a
    status for an appointment without finished notes. A single unnamed animal is
    shown by its time alone."""
    exams = appointment.exams
    date = format_created_at(appointment.created_at)
    named = any((exam.patient_name or "").strip() for exam in exams)
    parts = []
    if len(exams) > 1 or named:
        parts.append(", ".join(display_name(e.patient_name, i + 1) for i, e in enumerate(exams)))
    parts.append(date)
    if len(exams) > 1:
        parts.append(ui_strings.HISTORY_ANIMAL_COUNT.format(count=len(exams)))
    suffix = _STATUS_SUFFIXES.get(appointment.status)
    if suffix:
        parts.append(suffix)
    return "  ·  ".join(parts)


def _matches_search(appointment, query) -> bool:
    # By pet name only; an unnamed animal never matches.
    return any(
        query in (exam.patient_name or "").strip().lower() for exam in appointment.exams
    )


class _AnimalTab:
    """One animal's tab: its name, its four SOAP fields and its own actions."""

    def __init__(self, frame, exam_id, name_var):
        self.frame = frame
        self.exam_id = exam_id
        self.name_var = name_var
        self.field_texts = {}
        self.inject_button = None
        self.copy_button = None
        self.remove_button = None


class HistoryWindow(tk.Toplevel):
    """Every recording (appointment), newest first; the selected one shows its
    shared transcript and a tab per animal, like the phone's appointment screen.
    Recordings without finished notes show their status instead, with Retry or
    Generate Notes Now where those apply."""

    def __init__(
        self,
        master,
        load_appointments,
        on_copy_and_inject,
        on_copy_to_clipboard,
        on_save=None,
        on_delete=None,
        on_regenerate=None,
        on_retry=None,
        on_complete_notes=None,
        confirm_delete=None,
        confirm_remove=None,
        poll_interval_ms=DEFAULT_POLL_INTERVAL_MS,
        initial_appointments=None,
        select=None,
    ):
        super().__init__(master)
        self.title(ui_strings.HISTORY_WINDOW_TITLE)
        apply_window_icon(self)
        self.geometry(f"{DEFAULT_WIDTH}x{DEFAULT_HEIGHT}")
        self._load_appointments = load_appointments
        self.on_copy_and_inject = on_copy_and_inject
        self.on_copy_to_clipboard = on_copy_to_clipboard
        # Blocking backend call: (appointment_id, transcript, exams) -> the saved
        # Appointment, None when the backend is unreachable; raises
        # ApiClientError when it refuses.
        self.on_save = on_save or (lambda appointment_id, transcript, exams: None)
        self.on_delete = on_delete or (lambda appointment_id: True)
        # Slow backend calls (provider-bound or not), run off the Tk thread so
        # the window stays responsive: transcript -> one PatientNote per animal,
        # and appointment id -> the updated Appointment.
        self.on_regenerate = on_regenerate
        self.on_retry = on_retry
        self.on_complete_notes = on_complete_notes
        self._confirm_delete = confirm_delete or self._default_confirm_delete
        self._confirm_remove = confirm_remove or self._default_confirm_remove
        self._regenerating = False
        # main.py prefetches behind the splash, off the Tk thread.
        self.appointments = list(
            load_appointments() if initial_appointments is None else initial_appointments
        )
        self.visible = []
        self._shown = None  # the appointment the detail pane was drawn from
        self._dirty = False  # names, a removed animal or a regenerate unsaved
        self._pending_select = None
        self._clear_detail_refs()

        # Left: search box and one row per appointment, newest first.
        list_frame = tk.Frame(self)
        list_frame.pack(side="left", fill="y")
        tk.Label(list_frame, text=ui_strings.LABEL_HISTORY_SEARCH).pack(anchor="w")
        self.search_var = tk.StringVar(self)
        tk.Entry(list_frame, textvariable=self.search_var).pack(fill="x")
        self.search_var.trace_add("write", lambda *_: self._populate_listbox())
        rows = tk.Frame(list_frame)
        rows.pack(fill="both", expand=True)
        # exportselection off: selecting text in a note mustn't drop the row.
        self.listbox = tk.Listbox(rows, width=44, exportselection=False)
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar = tk.Scrollbar(rows, command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=scrollbar.set)
        self.listbox.bind("<<ListboxSelect>>", self._on_listbox_select)

        # Right: the selected appointment, redrawn for each one.
        self.detail = tk.Frame(self)
        self.detail.pack(side="right", fill="both", expand=True)

        self._populate_listbox()
        if select is not None:
            self.select_appointment(*select)
        elif self.visible:
            self.show_appointment(0)

        # Auto-refresh so recordings made while the window is open show up live.
        self._poll_interval_ms = poll_interval_ms
        self._poll_job = None
        self.bind("<Destroy>", self._on_destroy)
        if poll_interval_ms:
            self._schedule_poll()

    # --- the list ---------------------------------------------------------

    def _populate_listbox(self):
        query = self.search_var.get().strip().lower()
        self.visible = [
            a for a in self.appointments if not query or _matches_search(a, query)
        ]
        self.listbox.delete(0, "end")
        for appointment in self.visible:
            self.listbox.insert("end", row_label(appointment))
        self._highlight_selected()

    def _highlight_selected(self):
        self.listbox.selection_clear(0, "end")
        index = self._visible_index(self._selected_id())
        if index is not None:
            self.listbox.selection_set(index)
            self.listbox.see(index)

    def _visible_index(self, appointment_id):
        for index, appointment in enumerate(self.visible):
            if appointment.id == appointment_id:
                return index
        return None

    def _selected_id(self):
        return self._shown.id if self._shown is not None else None

    def _on_listbox_select(self, _event):
        selection = self.listbox.curselection()
        if selection:
            self.show_appointment(selection[0])

    def show_appointment(self, index):
        self._render(self.visible[index])
        self._highlight_selected()

    def select_appointment(self, appointment_id, exam_id=None):
        """Show an appointment (and one animal's tab). One that hasn't been read
        yet -- just recorded -- is shown once a refresh brings it in."""
        if self._visible_index(appointment_id) is None and self.search_var.get():
            self.search_var.set("")
        index = self._visible_index(appointment_id)
        if index is None:
            self._pending_select = (appointment_id, exam_id)
            return
        self._pending_select = None
        self.show_appointment(index)
        for tab_index, tab in enumerate(self.tabs):
            if exam_id is not None and tab.exam_id == exam_id:
                self.notebook.select(tab_index)

    # --- the detail pane ----------------------------------------------------

    def _clear_detail_refs(self):
        self.tabs = []
        self.notebook = None
        self.transcript_text = None
        self.status_label = None
        self.save_status_label = None
        self.save_button = None
        self.regenerate_button = None
        self.delete_button = None
        self.retry_button = None
        self.generate_button = None

    def _clear_detail(self):
        for child in self.detail.winfo_children():
            child.destroy()
        self._clear_detail_refs()
        self._shown = None
        self._dirty = False

    def _render(self, appointment, transcript=None, drafts=None, tab_index=0, dirty=False):
        """Draw an appointment. ``transcript``/``drafts`` redraw it with unsaved
        changes (a regenerate, a removed animal) instead of what's stored."""
        self._clear_detail()
        self._shown = appointment
        if appointment.status in _NO_TRANSCRIPT_MESSAGES:
            self._render_without_transcript(appointment)
        elif appointment.status == "note_pending":
            self._render_pending(appointment)
        else:
            self._render_complete(appointment, transcript, drafts, tab_index)
        self._mark_clean()
        self._dirty = dirty

    def _render_without_transcript(self, appointment):
        self.status_label = tk.Label(
            self.detail,
            text=_NO_TRANSCRIPT_MESSAGES[appointment.status],
            wraplength=480,
            justify="left",
        )
        self.status_label.pack(anchor="w", pady=8)
        buttons = tk.Frame(self.detail)
        buttons.pack(fill="x")
        if appointment.status == "failed" and self.on_retry is not None:
            self.retry_button = tk.Button(
                buttons,
                text=ui_strings.BUTTON_RETRY,
                command=lambda: self._run_action(
                    self.retry_button, ui_strings.BUTTON_RETRY, self.on_retry
                ),
            )
            self.retry_button.pack(side="left")
        self._add_delete_button(buttons)

    def _render_pending(self, appointment):
        self.status_label = tk.Label(
            self.detail, text=ui_strings.HISTORY_NOTE_PENDING_MESSAGE, wraplength=480,
            justify="left",
        )
        self.status_label.pack(anchor="w", pady=8)
        buttons = tk.Frame(self.detail)
        buttons.pack(side="bottom", fill="x")
        if self.on_complete_notes is not None:
            self.generate_button = tk.Button(
                buttons,
                text=ui_strings.BUTTON_GENERATE_NOTES_NOW,
                command=lambda: self._run_action(
                    self.generate_button,
                    ui_strings.BUTTON_GENERATE_NOTES_NOW,
                    self.on_complete_notes,
                ),
            )
            self.generate_button.pack(side="left")
        self._add_delete_button(buttons)
        tk.Label(self.detail, text=ui_strings.LABEL_SHARED_TRANSCRIPT).pack(anchor="w")
        self.transcript_text = tk.Text(self.detail, height=10, wrap="word")
        self.transcript_text.insert("1.0", appointment.transcript)
        # Read-only until there are notes to save it with.
        self.transcript_text.config(state="disabled")
        self.transcript_text.pack(fill="both", expand=True)

    def _render_complete(self, appointment, transcript, drafts, tab_index):
        if drafts is None:
            drafts = [
                ExamDraft(e.id, e.patient_name, e.subjective, e.objective, e.assessment, e.plan)
                for e in appointment.exams
            ]
        # Pack the buttons first so they always keep their space at the bottom.
        buttons = tk.Frame(self.detail)
        buttons.pack(side="bottom", fill="x")
        self.save_button = tk.Button(
            buttons, text=ui_strings.BUTTON_SAVE_CHANGES, command=self._on_save_clicked
        )
        self.save_button.pack(side="left")
        if self.on_regenerate is not None:
            self.regenerate_button = tk.Button(
                buttons, text=ui_strings.BUTTON_REGENERATE, command=self._on_regenerate_clicked
            )
            self.regenerate_button.pack(side="left")
            self._set_regenerating(self._regenerating)
        self._add_delete_button(buttons)
        self.save_status_label = tk.Label(buttons, text="", fg="#a33")
        self.save_status_label.pack(side="left")

        self.notebook = ttk.Notebook(self.detail)
        self.notebook.pack(side="top", fill="both", expand=True)
        for index, draft in enumerate(drafts):
            self._add_tab(draft, index, len(drafts))
        if self.tabs:
            self.notebook.select(min(tab_index, len(self.tabs) - 1))

        tk.Label(self.detail, text=ui_strings.LABEL_SHARED_TRANSCRIPT).pack(anchor="w")
        self.transcript_text = tk.Text(self.detail, height=6, wrap="word")
        self.transcript_text.insert(
            "1.0", appointment.transcript if transcript is None else transcript
        )
        self.transcript_text.pack(fill="both", expand=True)

    def _add_tab(self, draft, index, count):
        frame = tk.Frame(self.notebook)
        name_var = tk.StringVar(self, value=draft.patient_name or "")
        tab = _AnimalTab(frame, draft.id, name_var)

        name_row = tk.Frame(frame)
        name_row.pack(fill="x")
        tk.Label(name_row, text=ui_strings.LABEL_PATIENT_NAME).pack(side="left")
        tk.Entry(name_row, textvariable=name_var).pack(side="left", fill="x", expand=True)

        for key, label in _SOAP_FIELDS:
            tk.Label(frame, text=label).pack(anchor="w")
            widget = tk.Text(frame, height=3, wrap="word")
            widget.insert("1.0", getattr(draft, key))
            widget.pack(fill="both", expand=True)
            tab.field_texts[key] = widget

        actions = tk.Frame(frame)
        actions.pack(fill="x")
        tab.inject_button = tk.Button(
            actions, text=ui_strings.BUTTON_COPY_AND_INJECT, command=lambda: self._on_inject(tab)
        )
        tab.inject_button.pack(side="left")
        tab.copy_button = tk.Button(
            actions, text=ui_strings.BUTTON_COPY_SOAP_NOTE, command=lambda: self._on_copy(tab)
        )
        tab.copy_button.pack(side="left")
        # Only with several animals: an appointment keeps at least one (delete
        # the appointment instead).
        if count > 1:
            tab.remove_button = tk.Button(
                actions, text=ui_strings.BUTTON_REMOVE_ANIMAL, command=lambda: self._on_remove(tab)
            )
            tab.remove_button.pack(side="right")

        self.notebook.add(frame, text=display_name(draft.patient_name, index + 1))
        self.tabs.append(tab)
        name_var.trace_add("write", lambda *_: self._on_name_changed(tab))

    def _on_name_changed(self, tab):
        self._dirty = True
        try:
            number = self.tabs.index(tab) + 1
            self.notebook.tab(tab.frame, text=display_name(tab.name_var.get(), number))
        except (ValueError, tk.TclError):
            pass

    def _add_delete_button(self, parent):
        self.delete_button = tk.Button(
            parent, text=ui_strings.BUTTON_DELETE_APPOINTMENT, command=self._on_delete_clicked
        )
        self.delete_button.pack(side="right")

    def _text_widgets(self):
        widgets = [w for tab in self.tabs for w in tab.field_texts.values()]
        if self.transcript_text is not None:
            widgets.append(self.transcript_text)
        return widgets

    def _mark_clean(self):
        # Programmatic population mustn't read as a vet edit.
        for widget in self._text_widgets():
            widget.edit_modified(False)
        self._dirty = False

    def _has_unsaved_edits(self) -> bool:
        if self._shown is None or self._shown.status != "complete":
            return False
        return self._dirty or any(w.edit_modified() for w in self._text_widgets())

    def _current_tab_index(self):
        if self.notebook is None or not self.tabs:
            return 0
        return self.notebook.index("current")

    def _screen_transcript(self):
        return self.transcript_text.get("1.0", "end-1c")

    @staticmethod
    def _tab_draft(tab):
        return ExamDraft(
            id=tab.exam_id,
            patient_name=tab.name_var.get().strip() or None,
            **{key: widget.get("1.0", "end-1c") for key, widget in tab.field_texts.items()},
        )

    def _screen_drafts(self):
        return [self._tab_draft(tab) for tab in self.tabs]

    def _tab_exam(self, tab):
        # The animal's note as it is on screen, for Copy and an offline inject.
        draft = self._tab_draft(tab)
        return Exam(
            id=draft.id,
            created_at=self._shown.created_at,
            subjective=draft.subjective,
            objective=draft.objective,
            assessment=draft.assessment,
            plan=draft.plan,
            transcript=self._screen_transcript(),
            patient_name=draft.patient_name,
            appointment_id=self._shown.id,
        )

    # --- save, inject, copy, remove ---------------------------------------

    def _on_save_clicked(self):
        self._save()

    def _save(self):
        """Save the whole appointment as it is on screen. Returns the saved
        Appointment, or None when it wasn't saved (the edits stay on screen)."""
        appointment = self._shown
        try:
            saved = self.on_save(appointment.id, self._screen_transcript(), self._screen_drafts())
        except ApiClientError as exc:
            messagebox.showerror(
                ui_strings.SAVE_ERROR_TITLE,
                ui_strings.SAVE_ERROR_MESSAGE.format(error=exc),
                parent=self,
            )
            return None
        if saved is None:
            # Backend unreachable: keep the edits (and their unsaved state, so a
            # refresh can't paint over them) and say so without a modal dialog.
            self.save_status_label.config(text=ui_strings.SAVE_OFFLINE_TITLE)
            return None
        tab_index = self._current_tab_index()
        self.appointments = [saved if a.id == saved.id else a for a in self.appointments]
        self._render(saved, tab_index=tab_index)
        self._populate_listbox()
        return saved

    def _on_inject(self, tab):
        # Save first so what lands in AVImark is also what's stored -- the vet
        # shouldn't have to click Save Changes before injecting.
        index = self.tabs.index(tab)
        exam = self._tab_exam(tab)
        if self._has_unsaved_edits():
            saved = self._save()
            if saved is not None and index < len(saved.exams):
                exam = saved.exams[index]
        self.on_copy_and_inject(exam)

    def _on_copy(self, tab):
        self.on_copy_to_clipboard(self._tab_exam(tab).soap_text)

    def _on_remove(self, tab):
        index = self.tabs.index(tab)
        if not self._confirm_remove(display_name(tab.name_var.get(), index + 1)):
            return
        drafts = self._screen_drafts()
        del drafts[index]
        self._render(
            self._shown,
            transcript=self._screen_transcript(),
            drafts=drafts,
            tab_index=min(index, len(drafts) - 1),
            dirty=True,
        )

    def _default_confirm_remove(self, name):
        return messagebox.askyesno(
            ui_strings.REMOVE_ANIMAL_CONFIRM_TITLE,
            ui_strings.REMOVE_ANIMAL_CONFIRM_MESSAGE.format(name=name),
            parent=self,
        )

    # --- delete ----------------------------------------------------------------

    def _default_confirm_delete(self, appointment):
        return messagebox.askyesno(
            ui_strings.DELETE_CONFIRM_TITLE, ui_strings.DELETE_CONFIRM_MESSAGE, parent=self
        )

    def _on_delete_clicked(self):
        appointment = self._shown
        if appointment is None or not self._confirm_delete(appointment):
            return
        if self.on_delete(appointment.id) is False:
            messagebox.showerror(
                ui_strings.HISTORY_ACTION_ERROR_TITLE,
                ui_strings.HISTORY_ACTION_ERROR_MESSAGE.format(error="delete failed"),
                parent=self,
            )
            return
        # Re-read the store rather than mutating locally, so what's shown always
        # matches what's stored; land on the row that slid into its place.
        deleted_index = self._visible_index(appointment.id) or 0
        self.appointments = list(self._load_appointments())
        self._clear_detail()
        self._populate_listbox()
        if self.visible:
            self.show_appointment(min(deleted_index, len(self.visible) - 1))

    # --- regenerate --------------------------------------------------------------

    def _on_regenerate_clicked(self):
        if self.on_regenerate is None or self._regenerating or self._shown is None:
            return
        transcript = self._screen_transcript()
        if not transcript.strip():
            messagebox.showinfo(
                ui_strings.REGENERATE_EMPTY_TITLE,
                ui_strings.REGENERATE_EMPTY_MESSAGE,
                parent=self,
            )
            return
        # Remember which appointment this is for: a late result is dropped if
        # the vet has opened another one meanwhile.
        appointment_id = self._shown.id
        self._set_regenerating(True)

        def work():
            try:
                notes = self.on_regenerate(transcript, appointment_id=appointment_id)
            except Exception as exc:  # noqa: BLE001 -- surfaced to the vet below
                # Bind exc as a default arg: Python clears the `except ... as`
                # name when the block exits, before this after() callback runs.
                self.after(0, lambda err=exc: self._on_regenerate_failed(err))
                return
            self.after(0, lambda: self._on_regenerate_done(appointment_id, notes))

        threading.Thread(target=work, daemon=True).start()

    def _on_regenerate_done(self, appointment_id, notes):
        self._set_regenerating(False)
        if self._selected_id() != appointment_id or self._shown.status != "complete":
            return
        # Fold every animal's fresh note in the way the phone does, as unsaved
        # changes: regeneration is never destructive until the vet clicks Save.
        self._render(
            self._shown,
            transcript=self._screen_transcript(),
            drafts=merge_regenerated(self._screen_drafts(), notes),
            tab_index=self._current_tab_index(),
            dirty=True,
        )

    def _on_regenerate_failed(self, exc):
        self._set_regenerating(False)
        logger.warning("failed to regenerate SOAP notes: %s", type(exc).__name__)
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
                text=ui_strings.BUTTON_REGENERATE_BUSY if busy else ui_strings.BUTTON_REGENERATE,
            )
        except tk.TclError:
            # Window may have been destroyed between scheduling and running.
            pass

    # --- retry / generate notes now ---------------------------------------------

    def _run_action(self, button, label, action):
        """Run a slow backend call for the shown appointment on a worker thread,
        then redraw it from the appointment the call returns."""
        appointment_id = self._shown.id
        button.config(state="disabled", text=ui_strings.BUTTON_BUSY)

        def work():
            try:
                updated = action(appointment_id)
            except Exception as exc:  # noqa: BLE001 -- surfaced to the vet below
                self.after(0, lambda err=exc: self._on_action_failed(button, label, err))
                return
            self.after(0, lambda: self._on_action_done(updated))

        threading.Thread(target=work, daemon=True).start()

    def _on_action_done(self, updated):
        self.appointments = [updated if a.id == updated.id else a for a in self.appointments]
        self._populate_listbox()
        if self._selected_id() == updated.id:
            self._render(updated)
            self._highlight_selected()

    def _on_action_failed(self, button, label, exc):
        logger.warning("history action failed: %s", type(exc).__name__)
        try:
            button.config(state="normal", text=label)
        except tk.TclError:
            pass
        messagebox.showerror(
            ui_strings.HISTORY_ACTION_ERROR_TITLE,
            ui_strings.HISTORY_ACTION_ERROR_MESSAGE.format(error=exc),
            parent=self,
        )

    # --- live refresh ----------------------------------------------------------

    def refresh(self):
        """Re-read the store and reflect any changes, on the calling thread. The
        timer-driven poll reads on a worker thread instead (see ``_poll``)."""
        self._apply_appointments(list(self._load_appointments()))

    def _apply_appointments(self, new_appointments):
        """Reflect a freshly read list. Must run on the Tk main thread.

        Viewing the newest recording (or nothing) follows a just-made one;
        a deliberately opened older one stays put. Unsaved edits are never
        overwritten -- the list still updates around them."""
        if new_appointments == self.appointments and self._pending_select is None:
            return
        viewing_newest = self._shown is None or (
            bool(self.visible) and self.visible[0].id == self._shown.id
        )
        self.appointments = new_appointments
        self._populate_listbox()

        if self._pending_select is not None:
            appointment_id, exam_id = self._pending_select
            if self._visible_index(appointment_id) is not None and not self._has_unsaved_edits():
                self.select_appointment(appointment_id, exam_id)
                return

        if self._has_unsaved_edits():
            return
        if not self.visible:
            self._clear_detail()
            return
        index = 0 if viewing_newest else self._visible_index(self._selected_id())
        target = self.visible[index or 0]
        if target == self._shown:
            return
        same = self._shown is not None and target.id == self._shown.id
        self._render(target, tab_index=self._current_tab_index() if same else 0)
        self._highlight_selected()

    def _schedule_poll(self):
        self._poll_job = self.after(self._poll_interval_ms, self._poll)

    def _poll(self):
        self._poll_job = None
        if not self.winfo_exists():
            return

        # Read the store on a worker thread: this fires every second and the
        # read is a blocking backend GET, so doing it on the Tk loop made typing
        # and clicking stutter. The widget update is marshalled back via
        # after(), and the next poll is armed only once this one has applied,
        # so slow reads can't pile up.
        def work():
            try:
                fetched = list(self._load_appointments())
            except Exception:
                # A history read must never crash or kill the live-refresh loop.
                logger.exception("failed to refresh history window")
                fetched = None
            try:
                self.after(0, lambda: self._on_poll_fetched(fetched))
            except tk.TclError:
                # Window destroyed between the fetch and the marshal back.
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_poll_fetched(self, fetched):
        if not self.winfo_exists():
            return
        if fetched is not None:
            try:
                self._apply_appointments(fetched)
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
