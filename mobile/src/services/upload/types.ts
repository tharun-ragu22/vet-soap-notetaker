import type { AudioBody, Exam } from '../api/types';

/**
 * A queued unit of work. It starts life as an `audio` entry (a recording that
 * needs uploading) and, once the backend has transcribed it but not yet produced
 * a note (a 202 partial), becomes a `note` entry — the transcript is safe on the
 * server, so all that remains is a cheap note-generation retry with no re-upload.
 */
export type QueueEntry = AudioEntry | NoteEntry;

export interface AudioEntry {
  id: string;
  stage: 'audio';
  /** Name of the durably-stored audio file within the FileStore. */
  fileName: string;
  mimeType: string;
  createdAt: string;
  durationMillis: number;
  attempts: number;
  lastError?: string;
  /** Parked after too many failures so it can't wedge the queue; needs manual retry. */
  failed?: boolean;
}

export interface NoteEntry {
  id: string;
  stage: 'note';
  /** The partial exam on the backend whose note still needs generating. */
  examId: string;
  createdAt: string;
  attempts: number;
  lastError?: string;
  failed?: boolean;
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
  generateNote(audio: AudioBody, mimeType: string): Promise<Exam>;
  completeNote(examId: string): Promise<Exam>;
}
