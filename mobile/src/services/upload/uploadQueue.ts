import { ApiClientError } from '../api/ApiClient';
import type { Appointment } from '../api/types';
import type {
  AudioEntry,
  FileStore,
  NoteEntry,
  QueueEntry,
  QueueStore,
  QueueUploader,
  UploadErrorKind,
} from './types';

export interface EnqueueInput {
  uri: string;
  mimeType: string;
  durationMillis: number;
}

export interface UploadQueueOptions {
  store: QueueStore;
  files: FileStore;
  uploader: QueueUploader;
  /** Park an entry after this many failed attempts so a poison item can't wedge the queue. */
  maxAttempts?: number;
  idFactory?: () => string;
  now?: () => string;
  /**
   * Fired whenever the queue contents change, with the id of the entry uploading
   * right now (or null) — the banner and the Uploads screen reflect both.
   */
  onChange?: (entries: QueueEntry[], activeId: string | null) => void;
  /** Fired with a fully-generated appointment once it lands (not for partial transitions). */
  onAppointmentReady?: (appointment: Appointment) => void;
}

type Outcome = 'completed' | 'advanced' | 'transient_failure' | 'parked' | 'discarded';
type StepResult = { outcome: Outcome; appointment?: Appointment };

const DEFAULT_MAX_ATTEMPTS = 5;

/**
 * The durable, two-stage upload queue — the mobile analogue of the desktop
 * OfflineQueue. Recordings are persisted the moment they're captured (persist-
 * first), so nothing is lost if an upload fails or the app is killed. It drains
 * FIFO with no delay between successes; a failed pass stops early (the backend is
 * likely down) and is retried later by whoever drives `processOnce`.
 *
 * Nothing is ever deleted automatically: audio goes only after a successful upload
 * or a manual `remove`. Failing to reach the backend at all never counts toward
 * `maxAttempts`, so an outage just keeps retrying; only backend error replies (and
 * local errors) can mark an entry `failed`, which stops the automatic retries until
 * a manual `retry`. Only one entry is ever in flight; a pass asked for while one is
 * running runs right after it instead of being dropped.
 *
 * Pure and fully injectable: persistence, file storage, and the backend are all
 * interfaces, so the whole thing runs in Node against fakes.
 */
export class UploadQueue {
  private entries: QueueEntry[] = [];
  private running = false;
  private rerunRequested = false;
  private activeId: string | null = null;
  /** Cancels the request in flight, and resolves once that attempt has settled. */
  private inFlight: { abort: () => void; settled: Promise<void> } | null = null;
  /** The entry the vet is discarding: not to be started again meanwhile. */
  private discarding: string | null = null;
  private current: Promise<unknown> | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;

  private readonly store: QueueStore;
  private readonly files: FileStore;
  private readonly uploader: QueueUploader;
  private readonly maxAttempts: number;
  private readonly idFactory: () => string;
  private readonly now: () => string;
  private readonly onChange?: (entries: QueueEntry[], activeId: string | null) => void;
  private readonly onAppointmentReady?: (appointment: Appointment) => void;

  constructor(options: UploadQueueOptions) {
    this.store = options.store;
    this.files = options.files;
    this.uploader = options.uploader;
    this.maxAttempts = options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
    this.idFactory = options.idFactory ?? (() => Math.random().toString(36).slice(2));
    this.now = options.now ?? (() => new Date().toISOString());
    this.onChange = options.onChange;
    this.onAppointmentReady = options.onAppointmentReady;
  }

  /** Restore the queue from persisted metadata (call once on app start). */
  async load(): Promise<void> {
    const loaded = await this.store.load();
    // A note entry saved before appointments existed names an exam, not an
    // appointment. Its transcript is safe on the backend (the pending appointment
    // shows in History, to regenerate there), so it's dropped, not retried.
    this.entries = loaded.filter((e) => e.stage === 'audio' || Boolean(e.appointmentId));
    if (this.entries.length !== loaded.length) {
      await this.persist();
    } else {
      this.notify();
    }
  }

  /** A snapshot of the current queue. */
  pending(): QueueEntry[] {
    return [...this.entries];
  }

  /**
   * Persist a freshly-captured recording and queue it for upload — *before* any
   * network attempt, so it survives a failed upload or an app kill.
   */
  async enqueue(input: EnqueueInput): Promise<AudioEntry> {
    const fileName = await this.files.save(input.uri);
    const entry: AudioEntry = {
      id: this.idFactory(),
      stage: 'audio',
      fileName,
      mimeType: input.mimeType,
      createdAt: this.now(),
      durationMillis: input.durationMillis,
      attempts: 0,
    };
    this.entries.push(entry);
    await this.persist();
    return entry;
  }

  /** The entry being uploaded right now, if any. */
  uploading(): string | null {
    return this.activeId;
  }

  /** Resolves once no pass is running (including a follow-up pass it started). */
  async idle(): Promise<void> {
    while (this.current) await this.current;
  }

  /**
   * Discard an entry (and its audio file, if any) — only ever at the vet's request.
   * If it's uploading right now, that request is cancelled first. An upload that
   * lands before the cancel does is kept: its appointment is already in History.
   */
  async remove(id: string): Promise<void> {
    // Held until it's gone, so no pass starts uploading it again in the meantime.
    this.discarding = id;
    try {
      while (id === this.activeId && this.inFlight) {
        this.inFlight.abort();
        await this.inFlight.settled;
      }
      const entry = this.entries.find((e) => e.id === id);
      if (!entry) return;
      if (entry.stage === 'audio') {
        await this.safeDeleteFile(entry.fileName);
      }
      this.entries = this.entries.filter((e) => e.id !== id);
      await this.persist();
    } finally {
      this.discarding = null;
    }
  }

  /**
   * Drain the queue. Processes entries FIFO; keeps going as long as it makes
   * progress (so an audio→note transition completes in the same pass), and stops
   * the moment a non-parked attempt fails (the backend is probably down). Only one
   * pass runs at a time: asked for while one is running, it runs right after it.
   */
  async processOnce(): Promise<void> {
    await this.exclusive(() => this.drain());
  }

  /**
   * Attempt a single entry once, right now, and return the completed appointment if
   * it lands (following an audio→note transition through to completion). Returns null
   * if it isn't done yet — the entry stays queued, and if another upload is running
   * it goes right after that one. Used for the snappy happy path: upload on stop and
   * jump straight to the notes.
   */
  async tryProcess(id: string): Promise<Appointment | null> {
    return (await this.exclusive(() => this.attempt(id))) ?? null;
  }

  /**
   * The vet's manual Retry: clear a failed entry's give-up state and attempt it now
   * (or right after the upload in flight). Returns the appointment if it landed.
   */
  async retry(id: string): Promise<Appointment | null> {
    const entry = this.entries.find((e) => e.id === id);
    if (!entry) return null;
    entry.failed = false;
    entry.attempts = 0;
    await this.persist();
    return this.tryProcess(id);
  }

  /** Begin periodic draining. */
  start(intervalMs: number): void {
    if (this.timer) return;
    this.timer = setInterval(() => void this.processOnce(), intervalMs);
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  /**
   * Run `work` as the only thing touching the network. When busy, note that another
   * pass is wanted and return undefined; once the current work ends, that pass
   * starts in the background, so a caller awaiting its own upload (Stop) isn't held
   * up by the others.
   */
  private async exclusive<T>(work: () => Promise<T>): Promise<T | undefined> {
    if (this.running) {
      this.rerunRequested = true;
      return undefined;
    }
    this.running = true;
    const run = work();
    this.current = run;
    try {
      return await run;
    } finally {
      this.running = false;
      this.current = null;
      if (this.rerunRequested) {
        this.rerunRequested = false;
        void this.processOnce();
      }
    }
  }

  private async drain(): Promise<void> {
    do {
      this.rerunRequested = false;
      let progressed = true;
      while (progressed) {
        progressed = false;
        for (const snapshot of [...this.entries]) {
          // Re-read: the vet may have discarded or retried it since the snapshot.
          const entry = this.entries.find((e) => e.id === snapshot.id);
          if (!entry || entry.failed) continue;
          const { outcome } = await this.processEntry(entry);
          if (outcome === 'transient_failure') {
            progressed = false;
            break;
          }
          if (outcome === 'completed' || outcome === 'advanced') progressed = true;
          // 'parked' and 'discarded' just move on to the next entry.
        }
      }
    } while (this.rerunRequested);
  }

  private async attempt(id: string): Promise<Appointment | null> {
    // At most two steps: audio upload, then (if it became a note entry) note-gen.
    for (let step = 0; step < 2; step += 1) {
      const entry = this.entries.find((e) => e.id === id);
      if (!entry || entry.failed) return null;
      const { outcome, appointment } = await this.processEntry(entry);
      if (outcome === 'completed') return appointment ?? null;
      if (outcome !== 'advanced') return null;
    }
    return null;
  }

  private async processEntry(entry: QueueEntry): Promise<StepResult> {
    if (entry.id === this.discarding) return { outcome: 'discarded' };
    const controller = new AbortController();
    let settle!: () => void;
    this.inFlight = { abort: () => controller.abort(), settled: new Promise((r) => { settle = r; }) };
    this.activeId = entry.id;
    this.notify();
    try {
      await this.uploader.checkReachable?.();
      return entry.stage === 'audio'
        ? await this.processAudio(entry, controller.signal)
        : await this.processNote(entry, controller.signal);
    } catch (error) {
      // Cancelled because the vet is discarding it: not a failure of any kind.
      if (entry.id === this.discarding) return { outcome: 'discarded' };
      return this.recordFailure(entry, error);
    } finally {
      this.activeId = null;
      this.inFlight = null;
      settle();
      this.notify();
    }
  }

  private async processAudio(entry: AudioEntry, signal: AbortSignal): Promise<StepResult> {
    const bytes = await this.files.read(entry.fileName);
    const appointment = await this.uploader.createAppointment(bytes, entry.mimeType, { signal });

    if (appointment.notePending) {
      // Transcription succeeded but note-gen didn't: the transcript is safe on
      // the server now, so drop the audio and switch to the cheap note stage.
      await this.safeDeleteFile(entry.fileName);
      const note: NoteEntry = {
        id: entry.id,
        stage: 'note',
        appointmentId: appointment.id,
        createdAt: entry.createdAt,
        attempts: 0,
      };
      this.replace(entry.id, note);
      await this.persist();
      return { outcome: 'advanced' };
    }

    await this.safeDeleteFile(entry.fileName);
    this.drop(entry.id);
    await this.persist();
    this.onAppointmentReady?.(appointment);
    return { outcome: 'completed', appointment };
  }

  private async processNote(entry: NoteEntry, signal: AbortSignal): Promise<StepResult> {
    const appointment = await this.uploader.completeAppointment(entry.appointmentId, { signal });
    this.drop(entry.id);
    await this.persist();
    this.onAppointmentReady?.(appointment);
    return { outcome: 'completed', appointment };
  }

  private async recordFailure(entry: QueueEntry, error: unknown): Promise<StepResult> {
    const current = this.entries.find((e) => e.id === entry.id);
    if (!current) return { outcome: 'transient_failure' };
    const kind = errorKind(error);
    current.lastError = error instanceof Error ? error.message : String(error);
    current.lastErrorKind = kind;
    current.lastAttemptAt = this.now();
    if (kind === 'backend') {
      current.lastStatus = (error as ApiClientError).status;
    } else {
      delete current.lastStatus;
    }
    if (kind === 'unreachable') {
      // No answer at all: the backend is down or out of reach, which says nothing
      // about this recording. Keep retrying it for as long as that lasts.
      await this.persist();
      return { outcome: 'transient_failure' };
    }
    current.attempts += 1;
    // The backend heard no speech: the same audio would fail the same way (and pay
    // for transcription each time), so stop at once and leave it to the vet.
    const parked =
      current.attempts >= this.maxAttempts ||
      (current.lastStatus !== undefined && NON_RETRYABLE_STATUSES.has(current.lastStatus));
    if (parked) current.failed = true;
    await this.persist();
    return { outcome: parked ? 'parked' : 'transient_failure' };
  }

  private replace(id: string, next: QueueEntry): void {
    this.entries = this.entries.map((e) => (e.id === id ? next : e));
  }

  private drop(id: string): void {
    this.entries = this.entries.filter((e) => e.id !== id);
  }

  private async safeDeleteFile(fileName: string): Promise<void> {
    try {
      await this.files.delete(fileName);
    } catch {
      // Best-effort: a leftover file is harmless next to a correct queue.
    }
  }

  private async persist(): Promise<void> {
    await this.store.save(this.entries);
    this.notify();
  }

  private notify(): void {
    this.onChange?.(this.pending(), this.activeId);
  }
}

/** Backend replies that retrying the same recording can't fix (422: no speech). */
const NON_RETRYABLE_STATUSES = new Set([422]);

function errorKind(error: unknown): UploadErrorKind {
  if (!(error instanceof ApiClientError)) return 'other';
  return error.status === undefined ? 'unreachable' : 'backend';
}
