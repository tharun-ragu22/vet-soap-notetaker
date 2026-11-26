from abc import ABC, abstractmethod


class IAppointmentStore(ABC):
    """Where the History window reads and writes appointments: one recording,
    its shared transcript and one SOAP note per animal."""

    @abstractmethod
    def list_appointments(self) -> list:
        """Every appointment, newest first. Never raises: when the backend can't
        be read it serves the last copy it had (or nothing)."""

    @abstractmethod
    def save_appointment(self, appointment_id, *, transcript, exams):
        """Save the whole appointment (``exams`` are ``ExamDraft``s: with an id
        = updated, without = added, left out = deleted). Returns the saved
        ``Appointment``, or None when the backend can't be reached. Raises
        ``ApiClientError`` when the backend refuses the save."""

    @abstractmethod
    def delete_appointment(self, appointment_id) -> bool:
        """Delete the appointment and every animal's note; False if it failed."""

    @abstractmethod
    def retry(self, appointment_id):
        """Re-process a recording whose transcription failed. Returns the
        updated ``Appointment``; raises ``ApiClientError``."""

    @abstractmethod
    def complete_notes(self, appointment_id):
        """Generate the notes of a note-pending appointment (slow: a provider
        call). Returns the updated ``Appointment``; raises ``ApiClientError``."""
