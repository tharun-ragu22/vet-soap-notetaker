import tkinter
import uuid

import pytest

from vet_soap_notetaker import history_ui, ui_strings
from vet_soap_notetaker.api_client import Exam, SoapNote
from vet_soap_notetaker.history_ui import HistoryWindow


class _SyncThread:
    # Stand-in for threading.Thread that runs the worker inline, so the
    # regenerate path is deterministic in tests; self.after(0, ...) callbacks
    # it schedules are then flushed with window.update().
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


def make_entry(
    subjective="sub",
    transcript="the owner reports vomiting",
    entry_id=None,
    assessment="assess",
    patient_name=None,
):
    return Exam(
        # Each entry needs a stable, unique id: the window preserves the vet's
        # selection across auto-refresh by matching on it.
        id=entry_id or uuid.uuid4().hex,
        created_at="2026-09-17T10:30:00",
        subjective=subjective,
        objective="obj",
        assessment=assessment,
        plan="plan",
        transcript=transcript,
        patient_name=patient_name,
    )


def _note_pane(window):
    # The four structured fields joined the way the vet reads them; lets the
    # assertions below check content without caring which field it lands in.
    return "\n".join(
        f"{label.upper()}: {window.field_texts[key].get('1.0', 'end-1c')}"
        for key, label in history_ui._SOAP_FIELDS
    )


def make_window(tk_root, entries, **overrides):
    # Feed entries through a callable so the window can re-fetch them (that's how
    # auto-refresh works). Return a fresh copy each call so a test can mutate the
    # source list to simulate a note being saved while the window is open.
    kwargs = dict(
        master=tk_root,
        load_entries=lambda: list(entries),
        on_copy_and_inject=lambda soap_text: None,
        on_copy_to_clipboard=lambda soap_text: None,
        on_save_edit=lambda entry_id, **fields: None,
        on_delete=lambda entry_id: None,
        # Deletion is destructive, so the window guards it behind a confirmation.
        # Default to "yes" in tests so the delete path runs without a real dialog;
        # a test can override to simulate the vet cancelling.
        confirm_delete=lambda entry: True,
        # Disable the timer-driven poll in tests; drive refresh() explicitly so
        # assertions are deterministic and no stray `after` jobs outlive the test.
        poll_interval_ms=None,
    )
    kwargs.update(overrides)
    return HistoryWindow(**kwargs)


def test_history_window_lists_one_row_per_entry(tk_root):
    entries = [make_entry(subjective="first"), make_entry(subjective="second")]

    window = make_window(tk_root, entries)

    rows = window.listbox.get(0, "end")
    assert len(rows) == 2
    assert any("first" in row for row in rows)
    assert any("second" in row for row in rows)


def test_row_label_prefers_patient_name_when_present(tk_root):
    entries = [make_entry(subjective="ignored snippet", patient_name="Rex")]

    window = make_window(tk_root, entries)

    assert any("Rex" in row for row in window.listbox.get(0, "end"))


def test_selecting_an_entry_shows_its_note_and_transcript(tk_root):
    entries = [
        make_entry(subjective="Annual checkup", transcript="dog is well"),
        make_entry(subjective="Dental cleaning", transcript="tartar buildup noted"),
    ]
    window = make_window(tk_root, entries)

    window.show_entry(1)

    assert window.field_texts["subjective"].get("1.0", "end-1c") == "Dental cleaning"
    assert "tartar buildup noted" in window.transcript_text.get("1.0", "end-1c")


def test_window_shows_newest_entry_by_default(tk_root):
    # Entries arrive newest-first (as the store returns them), so the first
    # entry should be shown without the user clicking anything.
    entries = [
        make_entry(subjective="Newest", transcript="latest transcript"),
        make_entry(subjective="Older", transcript="older transcript"),
    ]
    window = make_window(tk_root, entries)

    assert window.field_texts["subjective"].get("1.0", "end-1c") == "Newest"


def test_copy_and_inject_button_sends_selected_entry_soap_text(tk_root):
    entries = [make_entry(subjective="Annual checkup")]
    injected = []
    window = make_window(
        tk_root, entries, on_copy_and_inject=injected.append
    )
    window.show_entry(0)

    assert window.copy_and_inject_button["text"] == ui_strings.BUTTON_COPY_AND_INJECT
    window.copy_and_inject_button.invoke()

    assert len(injected) == 1
    assert "SUBJECTIVE: Annual checkup" in injected[0]


def test_copy_to_clipboard_button_sends_selected_entry_soap_text(tk_root):
    entries = [make_entry(subjective="Annual checkup")]
    copied = []
    window = make_window(
        tk_root, entries, on_copy_to_clipboard=copied.append
    )
    window.show_entry(0)

    assert window.copy_to_clipboard_button["text"] == ui_strings.BUTTON_COPY_SOAP_NOTE
    window.copy_to_clipboard_button.invoke()

    assert len(copied) == 1
    assert "SUBJECTIVE: Annual checkup" in copied[0]


def test_history_window_handles_empty_history_without_crashing(tk_root):
    window = make_window(tk_root, entries=[])

    assert window.listbox.get(0, "end") == ()
    # Copy/inject with nothing selected must be a safe no-op, not a crash.
    window.copy_to_clipboard_button.invoke()


def test_refresh_adds_newly_saved_note_and_shows_it_when_viewing_newest(tk_root):
    entries = [make_entry(subjective="First note", transcript="first")]
    window = make_window(tk_root, entries)  # auto-selects the newest on open

    # A new note is saved while the window is open (prepended -- newest first).
    entries.insert(0, make_entry(subjective="Brand new note", transcript="brand new"))
    window.refresh()

    rows = window.listbox.get(0, "end")
    assert len(rows) == 2
    assert any("Brand new note" in row for row in rows)
    # The vet was on the newest entry, so the just-recorded note is shown for them.
    assert window.field_texts["subjective"].get("1.0", "end-1c") == "Brand new note"
    assert "brand new" in window.transcript_text.get("1.0", "end-1c")


def test_refresh_preserves_a_deliberately_selected_older_note(tk_root):
    entries = [
        make_entry(subjective="Newest", transcript="newest"),
        make_entry(subjective="Older", transcript="older"),
    ]
    window = make_window(tk_root, entries)
    window.show_entry(1)  # the vet deliberately opens an older note

    entries.insert(0, make_entry(subjective="Just recorded", transcript="just recorded"))
    window.refresh()

    # The list grows, but the note the vet is reading is not yanked away.
    assert len(window.listbox.get(0, "end")) == 3
    assert window.field_texts["subjective"].get("1.0", "end-1c") == "Older"
    assert "older" in window.transcript_text.get("1.0", "end-1c")


def test_refresh_populates_from_empty_when_first_note_arrives(tk_root):
    entries = []
    window = make_window(tk_root, entries)
    assert window.listbox.get(0, "end") == ()

    entries.append(make_entry(subjective="First ever", transcript="first ever"))
    window.refresh()

    assert len(window.listbox.get(0, "end")) == 1
    assert window.field_texts["subjective"].get("1.0", "end-1c") == "First ever"


def test_refresh_is_a_noop_when_nothing_changed(tk_root):
    entries = [
        make_entry(subjective="Newest", transcript="newest"),
        make_entry(subjective="Older", transcript="older"),
    ]
    window = make_window(tk_root, entries)
    window.show_entry(1)

    window.refresh()  # store unchanged

    # Selection is undisturbed and the list is unchanged.
    assert len(window.listbox.get(0, "end")) == 2
    assert window.field_texts["subjective"].get("1.0", "end-1c") == "Older"


def test_editing_and_saving_sends_the_structured_fields_to_the_save_callback(tk_root):
    saved = []
    entry = make_entry(subjective="Annual checkup", transcript="orig", entry_id="n1")
    window = make_window(
        tk_root,
        [entry],
        on_save_edit=lambda entry_id, **fields: saved.append((entry_id, fields)),
    )
    window.show_entry(0)

    # The vet edits a field and the transcript, then saves.
    window.field_texts["assessment"].delete("1.0", "end")
    window.field_texts["assessment"].insert("1.0", "corrected assessment")
    window.transcript_text.delete("1.0", "end")
    window.transcript_text.insert("1.0", "corrected transcript")
    window.save_button.invoke()

    assert len(saved) == 1
    entry_id, fields = saved[0]
    assert entry_id == "n1"
    assert fields["assessment"] == "corrected assessment"
    assert fields["subjective"] == "Annual checkup"
    assert fields["transcript"] == "corrected transcript"


def test_delete_button_removes_selected_note_and_shows_a_neighbor(tk_root):
    deleted = []
    entries = [
        make_entry(subjective="Newest", transcript="newest", entry_id="n1"),
        make_entry(subjective="Older", transcript="older", entry_id="n2"),
    ]

    def on_delete(entry_id):
        # The window re-reads the store after deleting, so mirror the removal in
        # the source list that load_entries() reads from.
        entries[:] = [e for e in entries if e.id != entry_id]
        deleted.append(entry_id)

    window = make_window(tk_root, entries, on_delete=on_delete)
    window.show_entry(0)  # the vet is on the newest note

    window.delete_button.invoke()

    assert deleted == ["n1"]
    rows = window.listbox.get(0, "end")
    assert len(rows) == 1
    assert any("Older" in row for row in rows)
    # A neighbor is selected so the detail pane isn't left showing a stale note.
    assert window.field_texts["subjective"].get("1.0", "end-1c") == "Older"
    assert "older" in window.transcript_text.get("1.0", "end-1c")


def test_delete_of_the_last_note_clears_the_detail_panes(tk_root):
    entries = [make_entry(subjective="Only note", transcript="only", entry_id="n1")]

    def on_delete(entry_id):
        entries[:] = [e for e in entries if e.id != entry_id]

    window = make_window(tk_root, entries, on_delete=on_delete)
    window.show_entry(0)

    window.delete_button.invoke()

    assert window.listbox.get(0, "end") == ()
    assert window.field_texts["subjective"].get("1.0", "end-1c") == ""
    assert window.transcript_text.get("1.0", "end-1c") == ""


def test_delete_does_nothing_when_the_vet_cancels_the_confirmation(tk_root):
    deleted = []
    entries = [make_entry(subjective="Only note", entry_id="n1")]
    window = make_window(
        tk_root,
        entries,
        on_delete=deleted.append,
        confirm_delete=lambda entry: False,  # the vet clicks "No"
    )
    window.show_entry(0)

    window.delete_button.invoke()

    assert deleted == []
    assert len(window.listbox.get(0, "end")) == 1
    assert window.field_texts["subjective"].get("1.0", "end-1c") == "Only note"


def test_delete_button_is_a_safe_noop_with_nothing_selected(tk_root):
    deleted = []
    window = make_window(tk_root, entries=[], on_delete=deleted.append)

    window.delete_button.invoke()

    assert deleted == []


def test_regenerate_button_absent_without_a_callback(tk_root):
    window = make_window(tk_root, [make_entry()])  # no on_regenerate wired

    assert window.regenerate_button is None
    labels = [
        child["text"]
        for child in window.winfo_children()
        if isinstance(child, tkinter.Button)
    ]
    assert ui_strings.BUTTON_REGENERATE not in labels


def test_regenerate_sends_edited_transcript_and_shows_note_as_unsaved_edit(
    tk_root, monkeypatch
):
    monkeypatch.setattr(history_ui.threading, "Thread", _SyncThread)
    received = []

    def fake_regenerate(transcript):
        received.append(transcript)
        return SoapNote(
            subjective="regenerated subjective",
            objective="regenerated objective",
            assessment="regenerated assessment",
            plan="regenerated plan",
        )

    entry = make_entry(subjective="Original", transcript="orig", entry_id="n1")
    window = make_window(tk_root, [entry], on_regenerate=fake_regenerate)
    window.show_entry(0)

    # The vet corrects the transcript, then regenerates.
    window.transcript_text.delete("1.0", "end")
    window.transcript_text.insert("1.0", "corrected transcript")
    window.regenerate_button.invoke()
    window.update()  # flush the after(0) that applies the result

    assert received == ["corrected transcript"]
    assert window.field_texts["assessment"].get("1.0", "end-1c") == "regenerated assessment"
    assert window.field_texts["subjective"].get("1.0", "end-1c") == "regenerated subjective"
    # Left as an unsaved edit so nothing is persisted until the vet hits Save.
    assert window._has_unsaved_edits()
    assert window.regenerate_button["text"] == ui_strings.BUTTON_REGENERATE


def test_regenerate_with_empty_transcript_warns_and_skips_backend(tk_root, monkeypatch):
    monkeypatch.setattr(history_ui.threading, "Thread", _SyncThread)
    called = []
    infos = []
    monkeypatch.setattr(
        history_ui.messagebox, "showinfo", lambda *a, **k: infos.append(a)
    )

    entry = make_entry(subjective="Original", transcript="   ", entry_id="n1")
    window = make_window(
        tk_root, [entry], on_regenerate=lambda t: called.append(t) or SoapNote("x", "x", "x", "x")
    )
    window.show_entry(0)

    window.regenerate_button.invoke()

    assert called == []
    assert len(infos) == 1


def test_regenerate_result_is_dropped_when_the_vet_selected_another_note(tk_root):
    entries = [
        make_entry(subjective="Newest", transcript="a", entry_id="n1"),
        make_entry(subjective="Older", transcript="b", entry_id="n2"),
    ]
    window = make_window(tk_root, entries, on_regenerate=lambda t: SoapNote("x", "x", "x", "x"))
    window.show_entry(1)  # currently on n2

    # A regenerate that was kicked off for n1 finishes late.
    window._on_regenerate_done(
        "n1", SoapNote("stale subjective", "s", "stale result", "p")
    )

    # The pane still shows n2; the stale note is not painted over it.
    assert window.field_texts["subjective"].get("1.0", "end-1c") == "Older"
    assert "stale result" not in _note_pane(window)


def test_regenerate_failure_surfaces_an_error_and_re_enables_the_button(
    tk_root, monkeypatch
):
    monkeypatch.setattr(history_ui.threading, "Thread", _SyncThread)
    errors = []
    monkeypatch.setattr(
        history_ui.messagebox, "showerror", lambda *a, **k: errors.append(a)
    )

    def boom(transcript):
        raise RuntimeError("backend is down")

    entry = make_entry(subjective="Original", transcript="orig", entry_id="n1")
    window = make_window(tk_root, [entry], on_regenerate=boom)
    window.show_entry(0)
    note_before = _note_pane(window)

    window.regenerate_button.invoke()
    window.update()  # flush the after(0) that surfaces the failure

    assert len(errors) == 1
    # The note is left untouched and the button is usable again.
    assert _note_pane(window) == note_before
    assert window._regenerating is False
    assert window.regenerate_button["text"] == ui_strings.BUTTON_REGENERATE


def test_auto_refresh_does_not_discard_an_in_progress_unsaved_edit(tk_root):
    entries = [make_entry(subjective="Only note", transcript="orig", entry_id="n1")]
    window = make_window(tk_root, entries)
    window.show_entry(0)

    # The vet starts editing but has not saved yet...
    window.field_texts["subjective"].delete("1.0", "end")
    window.field_texts["subjective"].insert("1.0", "half-typed edit")

    # ...and a new note is recorded, triggering an auto-refresh.
    entries.insert(0, make_entry(subjective="Just recorded", transcript="new", entry_id="n2"))
    window.refresh()

    # The new note shows up in the list, but the unsaved edit is NOT clobbered.
    assert len(window.listbox.get(0, "end")) == 2
    assert window.field_texts["subjective"].get("1.0", "end-1c") == "half-typed edit"


def test_auto_refresh_reads_the_backend_off_the_tk_main_thread(tk_root, monkeypatch):
    # The live-refresh poll must NOT do its blocking backend read inline on the
    # Tk main thread -- that call (GET /api/history) stalls typing and clicking
    # in the window every poll interval. It has to hand the read to a worker
    # thread and marshal the widget update back via after() (same rule as
    # regenerate). We capture the worker instead of starting it so the assertion
    # is deterministic and doesn't need a running mainloop.
    captured = []

    class _CapturingThread:
        def __init__(self, target, daemon=None):
            self._target = target
            captured.append(self)

        def start(self):
            pass  # don't run yet -- the test decides when

    monkeypatch.setattr(history_ui.threading, "Thread", _CapturingThread)

    fetched = []
    entries = [make_entry(subjective="first", entry_id="n1")]

    def load():
        fetched.append(True)
        return list(entries)

    window = make_window(tk_root, entries, load_entries=load)
    fetched.clear()  # ignore the one synchronous read done at construction

    # A note arrives while the window is open, so the poll has real work to apply.
    entries.insert(0, make_entry(subjective="second", entry_id="n2"))
    window._poll()

    # The poll must have deferred the read to a worker thread, NOT read inline on
    # the Tk loop. (The broken version calls refresh() synchronously here.)
    assert fetched == [], "history poll read the backend on the Tk main thread"
    assert captured, "history poll did not dispatch the read to a worker thread"

    # Running the worker and flushing its after() callback applies the new note.
    captured[0]._target()
    window.update()
    assert fetched, "worker never read the store"
    assert len(window.listbox.get(0, "end")) == 2  # the refresh actually applied
