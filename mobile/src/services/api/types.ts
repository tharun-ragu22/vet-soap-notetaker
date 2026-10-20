/** The four SOAP sections of one animal's note. */
export interface SoapFields {
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
}

/** The four SOAP sections plus the raw transcript — the editable body of a note. */
export interface SoapNote extends SoapFields {
  transcript: string;
}

/**
 * A persisted exam (one animal's note) as the backend's single-exam endpoints
 * return it: with its appointment's shared transcript.
 */
export interface Exam extends SoapNote {
  id: string;
  /** The appointment (recording) this animal was seen in. */
  appointmentId: string;
  createdAt: string;
  patientName?: string;
  /**
   * True when transcription succeeded but note generation is still pending (the
   * backend returned a 202 partial). The note fields are empty until a retry via
   * completeNote() fills them in.
   */
  notePending?: boolean;
}

/** One animal's exam inside an {@link Appointment} (the transcript lives on the appointment). */
export interface AppointmentExam extends SoapFields {
  id: string;
  appointmentId: string;
  createdAt: string;
  patientName?: string;
  notePending: boolean;
}

/**
 * Where a recording is up to on the backend. An async upload starts `processing`;
 * `failed` (transcription failed: Retry re-runs it from the saved audio) and
 * `no_speech` are terminal; `note_pending` has a transcript but no notes yet
 * (finish with completeAppointment); `complete` has its notes.
 */
export type AppointmentStatus = 'processing' | 'note_pending' | 'failed' | 'no_speech' | 'complete';

/**
 * One recording: the transcript, shared by every animal seen, and one exam per
 * animal. While note generation is pending (a 202) it holds a single empty,
 * note-pending exam; finish it with ApiClient.completeAppointment().
 */
export interface Appointment {
  id: string;
  createdAt: string;
  transcript: string;
  notePending: boolean;
  status: AppointmentStatus;
  exams: AppointmentExam[];
}

/** One animal in an appointment save: an existing exam (with its `id`) or a new one. */
export interface ExamDraft extends SoapFields {
  id?: string;
  patientName?: string;
}

/** The whole editable appointment, as saved by ApiClient.updateAppointment(). */
export interface AppointmentDraft {
  transcript: string;
  exams: ExamDraft[];
}

/** One animal's freshly generated note (from a regenerate; nothing saved yet). */
export interface PatientNote extends SoapFields {
  patientName?: string;
}

/** Raw audio payload accepted by generateNote (sent as the request body). */
export type AudioBody = ArrayBuffer | Uint8Array | Blob;

/**
 * A remote request to paste an exam's note into AVImark on the desktop. Created
 * when the vet taps "Inject into AVImark"; the desktop tray app polls for these,
 * does the paste (or shows its Safety Flyout), and acks.
 */
export interface InjectionRequest {
  id: string;
  examId: string;
  createdAt: string;
  status: string;
  outcome: string | null;
}
