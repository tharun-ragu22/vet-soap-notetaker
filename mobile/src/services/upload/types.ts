import type { Appointment, AudioBody } from '../api/types';

/**
 * A queued unit of work. It starts life as an `audio` entry (a recording that
 * needs uploading) and, once the backend has transcribed it but not yet produced
 * a note (a 202 partial), becomes a `note` entry — the transcript is safe on the
 * server, so all that remains is a cheap note-generation retry with no re-upload.
 */
export type QueueEntry = AudioEntry | NoteEntry;

/**
 * Why the last attempt failed: `unreachable` (no answer at all — never counts
 * toward giving up), `backend` (the backend replied with an error), or `other`.
 */
export type UploadErrorKind = 'unreachable' | 'backend' | 'other';

/** Bookkeeping shared by both stages: attempts and the last failure. */
interface AttemptFields {
  /** Failed attempts that count toward parking (backend errors, not unreachable). */
  attempts: number;
  lastError?: string;
  lastErrorKind?: UploadErrorKind;
  /** The backend's HTTP status for a `backend` failure. */
  lastStatus?: number;
  lastAttemptAt?: string;
  /** Automatic retries stopped after too many backend errors; needs a manual Retry. */
  failed?: boolean;
}

export interface AudioEntry extends AttemptFields {
  id: string;
  stage: 'audio';
  /** Name of the durably-stored audio file within the FileStore. */
  fileName: string;
  mimeType: string;
  createdAt: string;
  durationMillis: number;
}

export interface NoteEntry extends AttemptFields {
  id: string;
  stage: 'note';
  /** The appointment on the backend whose notes still need generating. */
  appointmentId: string;
  createdAt: string;
}

/** Persists the queue *metadata* (never the audio bytes). A subset of AsyncStorage. */
export interface QueueStore {
  load(): Promise<QueueEntry[]>;
  save(entries: QueueEntry[]): Promise<void>;
}

/** Persists audio *bytes* durably (the document directory), keyed by file name. */
export interface FileStore {
  /** Copy a recording from its (cache) uri into durable storage; returns the stored name. */
  save(uri: string): Promise<string>;
  read(fileName: string): Promise<AudioBody>;
  delete(fileName: string): Promise<void>;
}

/** The backend operations the queue drives — the subset of ApiClient it needs. */
export interface QueueUploader {
  /**
   * Throws an ApiClientError with no status if nothing answers within a few seconds.
   * Run before each step so a dead backend fails fast instead of hanging an upload
   * for the whole (long) upload timeout.
   */
  checkReachable?(): Promise<void>;
  /** `signal` aborts when the vet discards this recording mid-upload. */
  createAppointment(
    audio: AudioBody,
    mimeType: string,
    options?: { signal?: AbortSignal },
  ): Promise<Appointment>;
  completeAppointment(appointmentId: string, options?: { signal?: AbortSignal }): Promise<Appointment>;
}
