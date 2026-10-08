/** The four SOAP sections plus the raw transcript — the editable body of a note. */
export interface SoapNote {
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
  transcript: string;
}

/** A persisted exam as the backend stores and syncs it across devices. */
export interface Exam extends SoapNote {
  id: string;
  createdAt: string;
  patientName?: string;
  /**
   * True when transcription succeeded but note generation is still pending (the
   * backend returned a 202 partial). The note fields are empty until a retry via
   * completeNote() fills them in.
   */
  notePending?: boolean;
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
