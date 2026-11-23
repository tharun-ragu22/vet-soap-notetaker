import tkinter

import pytest

from vet_soap_notetaker import history_ui, ui_strings
from vet_soap_notetaker.api_client import Appointment, ApiClientError, Exam, ExamDraft, PatientNote
from vet_soap_notetaker.history_ui import HistoryWindow, row_label


class _SyncThread:
    # Stand-in for threading.Thread that runs the worker inline, so the
    # regenerate/retry paths are deterministic in tests; self.after(0, ...)
    # callbacks it schedules are then flushed with window.update().
    def __init__(self, target, daemon=None):
        self._target = target

    def start(self):
        self._target()


@pytest.fixture
def tk_root():
    root = tkinter.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def sync_threads(monkeypatch):
    monkeypatch.setattr(history_ui.threading, "Thread", _SyncThread)


def make_exam(exam_id, patient_name=None, plan="plan", appointment_id="appt-1", transcript="t"):
    return Exam(
        id=exam_id,
        created_at="2026-11-23T09:00:00",
        subjective="sub",
        objective="obj",
        assessment="assess",
        plan=plan,
        transcript=transcript,
        patient_name=patient_name,
        appointment_id=appointment_id,
    )


def make_appointment(
    appointment_id="appt-1",
    names=(None,),
    status="complete",
    transcript="the owner reports vomiting",
    created_at="2026-11-23T09:00:00",
):
    exams = [
        make_exam(f"{appointment_id}-e{i}", name, plan=f"plan {i}",
                  appointment_id=appointment_id, transcript=transcript)
        for i, name in enumerate(names)
    ]
    return Appointment(
        id=appointment_id,
        created_at=created_at,
        transcript=transcript,
        status=status,
        exams=exams,
    )


def make_window(tk_root, appointments, **overrides):
    # Feed appointments through a callable so the window can re-fetch them
    # (that's how auto-refresh works). A fresh copy each call lets a test mutate
    # the source list to simulate a recording arriving while the window is open.
    kwargs = dict(
        master=tk_root,
        load_appointments=lambda: list(appointments),
        on_copy_and_inject=lambda exam: None,
        on_copy_to_clipboard=lambda text: None,
        on_save=lambda appointment_id, transcript, exams: None,
        on_delete=lambda appointment_id: True,
        # Destructive actions are confirmed; default to "yes" so their paths
        # run without a real dialog.
        confirm_delete=lambda appointment: True,
        confirm_remove=lambda name: True,
        # No timer-driven poll in tests: drive refresh() explicitly.
        poll_interval_ms=None,
    )
    kwargs.update(overrides)
    return HistoryWindow(**kwargs)


def _text(widget):
    return widget.get("1.0", "end-1c")


def _type(widget, value):
    widget.delete("1.0", "end")
    widget.insert("1.0", value)


def _saved_after(appointment_id, transcript, exams):
    # What the backend sends back for a save: new animals get ids.
    return Appointment(
        id=appointment_id,
        created_at="2026-11-23T09:00:00",
        transcript=transcript,
        status="complete",
        exams=[
            Exam(e.id or f"new-{i}", "2026-11-23T09:00:00", e.subjective, e.objective,
                 e.assessment, e.plan, transcript, e.patient_name, appointment_id)
            for i, e in enumerate(exams)
        ],
    )


# --- The list -----------------------------------------------------------------


def test_one_row_per_appointment_not_per_animal(tk_root):
    window = make_window(
        tk_root,
        [make_appointment("a2", names=("Bella", "Max")), make_appointment("a1", names=("Rex",))],
    )

    assert window.listbox.size() == 2


def test_a_row_names_every_animal_and_counts_them():
    label = row_label(make_appointment(names=("Bella", "Max")))

    assert label.startswith("Bella, Max")
    assert "2026-11-23 09:00" in label
    assert ui_strings.HISTORY_ANIMAL_COUNT.format(count=2) in label


def test_unnamed_animals_among_several_are_numbered():
    assert row_label(make_appointment(names=("Bella", " "))).startswith(
        "Bella, " + ui_strings.PATIENT_FALLBACK_NAME.format(number=2)
    )


def test_a_single_unnamed_animal_is_shown_by_its_date():
    label = row_label(make_appointment(names=(None,)))

    assert label.startswith("2026-11-23 09:00")
    assert ui_strings.PATIENT_FALLBACK_NAME.format(number=1) not in label


@pytest.mark.parametrize(
    "status, text",
    [
        ("processing", ui_strings.HISTORY_STATUS_PROCESSING),
        ("failed", ui_strings.HISTORY_STATUS_FAILED),
        ("no_speech", ui_strings.HISTORY_STATUS_NO_SPEECH),
        ("note_pending", ui_strings.HISTORY_STATUS_NOTE_PENDING),
    ],
)
def test_a_row_says_when_an_appointment_has_no_finished_notes(status, text):
    names = () if status in ("processing", "failed", "no_speech") else (None,)

    assert text in row_label(make_appointment(names=names, status=status))


def test_prefetched_appointments_are_shown_without_reading_again(tk_root):
    def load():
        raise AssertionError("read the backend again at construction")

    window = make_window(
        tk_root, [], load_appointments=load, initial_appointments=[make_appointment()]
    )

    assert window.listbox.size() == 1


def test_the_newest_appointment_is_shown_on_open(tk_root):
    window = make_window(
        tk_root, [make_appointment("a2", names=("Bella",)), make_appointment("a1", names=("Rex",))]
    )

    assert window.tabs[0].name_var.get() == "Bella"


def test_an_empty_history_opens_without_crashing(tk_root):
    window = make_window(tk_root, [])

    assert window.listbox.size() == 0
    assert window.tabs == []


def test_search_filters_appointments_by_pet_name(tk_root):
    window = make_window(
        tk_root,
        [
            make_appointment("a3", names=("Bella", "Max")),
            make_appointment("a2", names=("Rex",)),
            make_appointment("a1", names=(None,)),
        ],
    )

    window.search_var.set("max")

    assert window.listbox.size() == 1
    assert window.listbox.get(0).startswith("Bella, Max")
    # Unnamed animals never match a search.
    window.search_var.set("patient")
    assert window.listbox.size() == 0
    window.search_var.set("")
    assert window.listbox.size() == 3


# --- A complete appointment: one tab per animal ---------------------------------


def test_each_animal_gets_a_tab_with_its_name_and_note(tk_root):
    window = make_window(tk_root, [make_appointment(names=("Bella", "Max"))])

    assert [tab.name_var.get() for tab in window.tabs] == ["Bella", "Max"]
    assert _text(window.tabs[1].field_texts["plan"]) == "plan 1"
    assert window.notebook.tab(1, "text") == "Max"


def test_an_unnamed_tab_is_numbered(tk_root):
    window = make_window(tk_root, [make_appointment(names=("Bella", None))])

    assert window.notebook.tab(1, "text") == ui_strings.PATIENT_FALLBACK_NAME.format(number=2)


def test_the_transcript_is_shown_once_for_the_whole_appointment(tk_root):
    window = make_window(tk_root, [make_appointment(names=("Bella", "Max"), transcript="shared")])

    assert _text(window.transcript_text) == "shared"


def test_save_sends_the_whole_appointment_with_renamed_and_edited_animals(tk_root):
    saves = []

    def on_save(appointment_id, transcript, exams):
        saves.append((appointment_id, transcript, exams))
        return _saved_after(appointment_id, transcript, exams)

    window = make_window(tk_root, [make_appointment(names=("Bella", "Max"))], on_save=on_save)
    window.tabs[1].name_var.set("Maxwell")
    _type(window.tabs[0].field_texts["plan"], "bella edited")
    _type(window.transcript_text, "corrected")
    assert window._has_unsaved_edits()

    window.save_button.invoke()

    [(appointment_id, transcript, exams)] = saves
    assert appointment_id == "appt-1"
    assert transcript == "corrected"
    assert exams == [
        ExamDraft("appt-1-e0", "Bella", "sub", "obj", "assess", "bella edited"),
        ExamDraft("appt-1-e1", "Maxwell", "sub", "obj", "assess", "plan 1"),
    ]
    assert not window._has_unsaved_edits()


def test_a_blank_name_is_saved_as_no_name(tk_root):
    saves = []
    window = make_window(
        tk_root,
        [make_appointment(names=("Bella",))],
        on_save=lambda a, t, exams: saves.append(exams),
    )
    window.tabs[0].name_var.set("   ")

    window.save_button.invoke()

    assert saves[0][0].patient_name is None


def test_a_refused_save_keeps_the_edits_and_tells_the_vet(tk_root, monkeypatch):
    errors = []
    monkeypatch.setattr(history_ui.messagebox, "showerror", lambda *a, **k: errors.append(a))

    def refuse(appointment_id, transcript, exams):
        raise ApiClientError("backend returned 409")

    window = make_window(tk_root, [make_appointment(names=("Bella",))], on_save=refuse)
    _type(window.tabs[0].field_texts["plan"], "keep me")

    window.save_button.invoke()

    assert len(errors) == 1
    assert _text(window.tabs[0].field_texts["plan"]) == "keep me"
    assert window._has_unsaved_edits()


def test_remove_animal_is_offered_only_when_there_are_several(tk_root):
    one = make_window(tk_root, [make_appointment(names=("Bella",))])
    two = make_window(tk_root, [make_appointment(names=("Bella", "Max"))])

    assert one.tabs[0].remove_button is None
    assert all(tab.remove_button is not None for tab in two.tabs)


def test_removing_an_animal_drops_it_from_the_next_save(tk_root):
    saves = []
    window = make_window(
        tk_root,
        [make_appointment(names=("Bella", "Max"))],
        on_save=lambda a, t, exams: saves.append(exams) or _saved_after(a, t, exams),
    )

    window.tabs[0].remove_button.invoke()

    assert [tab.name_var.get() for tab in window.tabs] == ["Max"]
    assert window._has_unsaved_edits()
    window.save_button.invoke()
    assert [e.id for e in saves[0]] == ["appt-1-e1"]


def test_removing_an_animal_needs_confirmation(tk_root):
    window = make_window(
        tk_root, [make_appointment(names=("Bella", "Max"))], confirm_remove=lambda name: False
    )

    window.tabs[0].remove_button.invoke()

    assert len(window.tabs) == 2
    assert not window._has_unsaved_edits()


def test_copy_and_inject_sends_that_animals_note(tk_root):
    injected = []
    window = make_window(
        tk_root, [make_appointment(names=("Bella", "Max"))], on_copy_and_inject=injected.append
    )

    window.tabs[1].inject_button.invoke()

    [exam] = injected
    assert exam.id == "appt-1-e1"
    assert exam.patient_name == "Max"
    assert exam.plan == "plan 1"


def test_inject_saves_unsaved_edits_first_and_injects_what_was_saved(tk_root):
    order = []

    def on_save(appointment_id, transcript, exams):
        order.append("save")
        return _saved_after(appointment_id, transcript, exams)

    window = make_window(
        tk_root,
        [make_appointment(names=("Bella", "Max"))],
        on_save=on_save,
        on_copy_and_inject=lambda exam: order.append(("inject", exam.plan)),
    )
    _type(window.tabs[1].field_texts["plan"], "max edited")

    window.tabs[1].inject_button.invoke()

    assert order == ["save", ("inject", "max edited")]


def test_inject_still_uses_the_edits_when_the_backend_is_unreachable(tk_root):
    injected = []
    window = make_window(
        tk_root,
        [make_appointment(names=("Bella",))],
        on_save=lambda a, t, exams: None,  # backend unreachable
        on_copy_and_inject=injected.append,
    )
    _type(window.tabs[0].field_texts["plan"], "offline edit")

    window.tabs[0].inject_button.invoke()

    assert injected[0].plan == "offline edit"


def test_inject_of_a_new_animal_uses_the_id_the_save_gave_it(tk_root, sync_threads):
    injected = []
    window = make_window(
        tk_root,
        [make_appointment(names=("Bella",))],
        on_regenerate=lambda t, appointment_id=None: [
            PatientNote("Bella", "s", "o", "a", "bella new"),
            PatientNote("Luna", "s", "o", "a", "luna new"),
        ],
        on_save=_saved_after,
        on_copy_and_inject=injected.append,
    )
    window.regenerate_button.invoke()
    window.update()

    window.tabs[1].inject_button.invoke()

    assert injected[0].id == "new-1"
    assert injected[0].plan == "luna new"


def test_copy_sends_that_animals_note_text(tk_root):
    copied = []
    window = make_window(
        tk_root, [make_appointment(names=("Bella", "Max"))], on_copy_to_clipboard=copied.append
    )

    window.tabs[1].copy_button.invoke()

    assert copied == ["SUBJECTIVE: sub\nOBJECTIVE: obj\nASSESSMENT: assess\nPLAN: plan 1"]
    # The pet's name labels the tab; it's never part of the copied note.
    assert "Max" not in copied[0]


# --- Regenerate -------------------------------------------------------------------


def test_regenerate_folds_every_animal_in_as_unsaved_edits(tk_root, sync_threads):
    received = []

    def regenerate(transcript, appointment_id=None):
        received.append((transcript, appointment_id))
        return [
            PatientNote("Max", "s", "o", "a", "max new"),
            PatientNote("Bella", "s", "o", "a", "bella new"),
            PatientNote("Luna", "s", "o", "a", "luna new"),
        ]

    window = make_window(
        tk_root, [make_appointment(names=("Bella", "Max"))], on_regenerate=regenerate
    )
    _type(window.transcript_text, "corrected")

    window.regenerate_button.invoke()
    window.update()

    assert received == [("corrected", "appt-1")]
    assert [(tab.exam_id, tab.name_var.get(), _text(tab.field_texts["plan"])) for tab in window.tabs] == [
        ("appt-1-e1", "Max", "max new"),
        ("appt-1-e0", "Bella", "bella new"),
        (None, "Luna", "luna new"),
    ]
    # The transcript it was regenerated from stays on screen, and nothing is
    # saved until the vet clicks Save.
    assert _text(window.transcript_text) == "corrected"
    assert window._has_unsaved_edits()
    assert window.regenerate_button["text"] == ui_strings.BUTTON_REGENERATE


def test_regenerate_keeps_a_name_the_vet_typed(tk_root, sync_threads):
    window = make_window(
        tk_root,
        [make_appointment(names=("Bella",))],
        on_regenerate=lambda t, appointment_id=None: [PatientNote("Patient 1", "s", "o", "a", "new")],
    )
    window.tabs[0].name_var.set("Luna")

    window.regenerate_button.invoke()
    window.update()

    assert window.tabs[0].name_var.get() == "Luna"
    assert _text(window.tabs[0].field_texts["plan"]) == "new"


def test_regenerate_with_an_empty_transcript_warns_and_skips_the_backend(
    tk_root, sync_threads, monkeypatch
):
    infos = []
    monkeypatch.setattr(history_ui.messagebox, "showinfo", lambda *a, **k: infos.append(a))
    called = []
    window = make_window(
        tk_root,
        [make_appointment(transcript="   ")],
        on_regenerate=lambda t, appointment_id=None: called.append(t) or [],
    )

    window.regenerate_button.invoke()

    assert called == []
    assert len(infos) == 1


def test_a_late_regenerate_is_dropped_when_the_vet_opened_another_appointment(tk_root):
    window = make_window(
        tk_root,
        [make_appointment("a2", names=("Bella",)), make_appointment("a1", names=("Rex",))],
        on_regenerate=lambda t, appointment_id=None: [],
    )
    window.show_appointment(1)

    window._on_regenerate_done("a2", [PatientNote("Bella", "s", "o", "a", "stale")])

    assert window.tabs[0].name_var.get() == "Rex"
    assert _text(window.tabs[0].field_texts["plan"]) == "plan 0"


def test_regenerate_failure_surfaces_an_error_and_re_enables_the_button(
    tk_root, sync_threads, monkeypatch
):
    errors = []
    monkeypatch.setattr(history_ui.messagebox, "showerror", lambda *a, **k: errors.append(a))

    def boom(transcript, appointment_id=None):
        raise RuntimeError("backend is down")

    window = make_window(tk_root, [make_appointment(names=("Bella",))], on_regenerate=boom)

    window.regenerate_button.invoke()
    window.update()

    assert len(errors) == 1
    assert _text(window.tabs[0].field_texts["plan"]) == "plan 0"
    assert window.regenerate_button["text"] == ui_strings.BUTTON_REGENERATE


def test_regenerate_button_absent_without_a_callback(tk_root):
    window = make_window(tk_root, [make_appointment()])

    assert window.regenerate_button is None


# --- Delete -----------------------------------------------------------------------


def test_delete_removes_the_whole_appointment_and_shows_a_neighbor(tk_root):
    appointments = [make_appointment("a2", names=("Bella",)), make_appointment("a1", names=("Rex",))]
    deleted = []

    def on_delete(appointment_id):
        deleted.append(appointment_id)
        appointments[:] = [a for a in appointments if a.id != appointment_id]
        return True

    window = make_window(tk_root, appointments, on_delete=on_delete)

    window.delete_button.invoke()

    assert deleted == ["a2"]
    assert window.listbox.size() == 1
    assert window.tabs[0].name_var.get() == "Rex"


def test_delete_does_nothing_when_the_vet_cancels(tk_root):
    deleted = []
    window = make_window(
        tk_root,
        [make_appointment()],
        on_delete=deleted.append,
        confirm_delete=lambda appointment: False,
    )

    window.delete_button.invoke()

    assert deleted == []


def test_deleting_the_last_appointment_clears_the_detail(tk_root):
    appointments = [make_appointment()]

    def on_delete(appointment_id):
        appointments.clear()
        return True

    window = make_window(tk_root, appointments, on_delete=on_delete)

    window.delete_button.invoke()

    assert window.listbox.size() == 0
    assert window.tabs == []


# --- Appointments without finished notes ------------------------------------------


@pytest.mark.parametrize(
    "status, message",
    [
        ("processing", ui_strings.HISTORY_PROCESSING_MESSAGE),
        ("no_speech", ui_strings.HISTORY_NO_SPEECH_MESSAGE),
        ("failed", ui_strings.HISTORY_FAILED_MESSAGE),
    ],
)
def test_an_appointment_without_a_transcript_shows_a_message_only(tk_root, status, message):
    window = make_window(
        tk_root, [make_appointment(names=(), status=status)], on_retry=lambda a: None
    )

    assert window.status_label["text"] == message
    assert window.tabs == []
    assert window.save_button is None
    assert window.delete_button is not None
    assert (window.retry_button is not None) == (status == "failed")


def test_retry_reprocesses_a_failed_recording(tk_root, sync_threads):
    retried = []

    def on_retry(appointment_id):
        retried.append(appointment_id)
        return make_appointment(names=(), status="processing")

    window = make_window(
        tk_root, [make_appointment(names=(), status="failed")], on_retry=on_retry
    )

    window.retry_button.invoke()
    window.update()

    assert retried == ["appt-1"]
    assert window.status_label["text"] == ui_strings.HISTORY_PROCESSING_MESSAGE


def test_a_pending_appointment_offers_generate_notes_now(tk_root, sync_threads):
    generated = []

    def on_complete_notes(appointment_id):
        generated.append(appointment_id)
        return make_appointment(names=("Bella", "Max"))

    window = make_window(
        tk_root,
        [make_appointment(names=(None,), status="note_pending", transcript="saved transcript")],
        on_complete_notes=on_complete_notes,
    )
    assert window.status_label["text"] == ui_strings.HISTORY_NOTE_PENDING_MESSAGE
    assert _text(window.transcript_text) == "saved transcript"
    assert str(window.transcript_text["state"]) == "disabled"

    window.generate_button.invoke()
    window.update()

    assert generated == ["appt-1"]
    assert [tab.name_var.get() for tab in window.tabs] == ["Bella", "Max"]


def test_a_failed_generate_says_why_and_stays_pending(tk_root, sync_threads, monkeypatch):
    errors = []
    monkeypatch.setattr(history_ui.messagebox, "showerror", lambda *a, **k: errors.append(a))

    def fail(appointment_id):
        raise ApiClientError("backend returned 502")

    window = make_window(
        tk_root,
        [make_appointment(names=(None,), status="note_pending")],
        on_complete_notes=fail,
    )

    window.generate_button.invoke()
    window.update()

    assert len(errors) == 1
    assert str(window.generate_button["state"]) == "normal"


# --- Opening at an appointment -----------------------------------------------------


def test_the_window_can_open_on_a_given_appointment_and_animal(tk_root):
    window = make_window(
        tk_root,
        [make_appointment("a2", names=("Rex",)), make_appointment("a1", names=("Bella", "Max"))],
        select=("a1", "a1-e1"),
    )

    assert [tab.name_var.get() for tab in window.tabs] == ["Bella", "Max"]
    assert window.notebook.index("current") == 1


def test_select_appointment_switches_an_open_window(tk_root):
    window = make_window(
        tk_root, [make_appointment("a2", names=("Rex",)), make_appointment("a1", names=("Bella",))]
    )

    window.select_appointment("a1")

    assert window.tabs[0].name_var.get() == "Bella"
    assert window.listbox.curselection() == (1,)


# --- Live refresh ----------------------------------------------------------------


def test_refresh_shows_a_new_recording_when_viewing_the_newest(tk_root):
    appointments = [make_appointment("a1", names=("Rex",))]
    window = make_window(tk_root, appointments)

    appointments.insert(0, make_appointment("a2", names=("Bella",)))
    window.refresh()

    assert window.listbox.size() == 2
    assert window.tabs[0].name_var.get() == "Bella"


def test_refresh_keeps_a_deliberately_opened_older_appointment(tk_root):
    appointments = [make_appointment("a2", names=("Bella",)), make_appointment("a1", names=("Rex",))]
    window = make_window(tk_root, appointments)
    window.show_appointment(1)

    appointments.insert(0, make_appointment("a3", names=("Luna",)))
    window.refresh()

    assert window.tabs[0].name_var.get() == "Rex"


def test_refresh_never_discards_unsaved_edits(tk_root):
    appointments = [make_appointment("a1", names=("Bella",))]
    window = make_window(tk_root, appointments)
    _type(window.tabs[0].field_texts["plan"], "half-typed")
    window.tabs[0].name_var.set("Belle")

    appointments.insert(0, make_appointment("a2", names=("Max",)))
    window.refresh()

    assert window.listbox.size() == 2
    assert _text(window.tabs[0].field_texts["plan"]) == "half-typed"
    assert window.tabs[0].name_var.get() == "Belle"


def test_refresh_keeps_the_open_tab(tk_root):
    appointments = [make_appointment("a1", names=("Bella", "Max"))]
    window = make_window(tk_root, appointments)
    window.notebook.select(1)

    appointments[0] = make_appointment("a1", names=("Bella", "Max"), transcript="edited on the phone")
    window.refresh()

    assert _text(window.transcript_text) == "edited on the phone"
    assert window.notebook.index("current") == 1


def test_refresh_is_a_noop_when_nothing_changed(tk_root):
    appointments = [make_appointment()]
    window = make_window(tk_root, appointments)
    tab = window.tabs[0]

    window.refresh()

    assert window.tabs[0] is tab


def test_auto_refresh_reads_the_backend_off_the_tk_main_thread(tk_root, monkeypatch):
    # The poll's backend read must run on a worker thread, with the widget update
    # marshalled back via after(): reading inline stalled typing every second.
    captured = []

    class _CapturingThread:
        def __init__(self, target, daemon=None):
            self._target = target
            captured.append(self)

        def start(self):
            pass

    monkeypatch.setattr(history_ui.threading, "Thread", _CapturingThread)
    fetched = []
    appointments = [make_appointment("a1")]

    def load():
        fetched.append(True)
        return list(appointments)

    window = make_window(tk_root, appointments, load_appointments=load)
    fetched.clear()
    appointments.insert(0, make_appointment("a2"))

    window._poll()

    assert fetched == [], "history poll read the backend on the Tk main thread"
    captured[0]._target()
    window.update()
    assert window.listbox.size() == 2
