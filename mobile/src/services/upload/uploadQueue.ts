import type { Exam } from '../api/types';
import type { AudioEntry, FileStore, NoteEntry, QueueEntry, QueueStore, QueueUploader } from './types';

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
  /** Fired whenever the queue contents change — the UI reflects the pending count. */
  onChange?: (entries: QueueEntry[]) => void;
  /** Fired with a fully-generated exam once it lands (not for partial transitions). */
  onExamReady?: (exam: Exam) => void;
}

type Outcome = 'completed' | 'advanced' | 'transient_failure' | 'parked';
type StepResult = { outcome: Outcome; exam?: Exam };

const DEFAULT_MAX_ATTEMPTS = 5;

/**
 * The durable, two-stage upload queue — the mobile analogue of the desktop
 * OfflineQueue. Recordings are persisted the moment they're captured (persist-
 * first), so nothing is lost if an upload fails or the app is killed. It drains
 * FIFO with no delay between successes; a failed pass stops early (the backend is
 * likely down) and is retried later with backoff by whoever drives `processOnce`.
 *
 * Pure and fully injectable: persistence, file storage, and the backend are all
 * interfaces, so the whole thing runs in Node against fakes.
 */
export class UploadQueue {
  private entries: QueueEntry[] = [];
  private running = false;
  private timer: ReturnType<typeof setInterval> | null = null;

  private readonly store: QueueStore;
  private readonly files: FileStore;
  private readonly uploader: QueueUploader;
  private readonly maxAttempts: number;
  private readonly idFactory: () => string;
  private readonly now: () => string;
  private readonly onChange?: (entries: QueueEntry[]) => void;
  private readonly onExamReady?: (exam: Exam) => void;

  constructor(options: UploadQueueOptions) {
    this.store = options.store;
    this.files = options.files;
    this.uploader = options.uploader;
    this.maxAttempts = options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
    this.idFactory = options.idFactory ?? (() => Math.random().toString(36).slice(2));
    this.now = options.now ?? (() => new Date().toISOString());
    this.onChange = options.onChange;
    this.onExamReady = options.onExamReady;
  }

  /** Restore the queue from persisted metadata (call once on app start). */
  async load(): Promise<void> {
    this.entries = await this.store.load();
    this.onChange?.(this.pending());
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

  /** Discard an entry (and its audio file, if any) — e.g. the vet gives up on it. */
  async remove(id: string): Promise<void> {
    const entry = this.entries.find((e) => e.id === id);
    if (!entry) return;
    if (entry.stage === 'audio') {
      await this.safeDeleteFile(entry.fileName);
    }
    this.entries = this.entries.filter((e) => e.id !== id);
    await this.persist();
  }

  /**
   * Drain the queue. Processes entries FIFO; keeps going as long as it makes
   * progress (so an audio→note transition completes in the same pass), and stops
   * the moment a non-parked attempt fails (the backend is probably down). A
   * run-lock prevents overlapping passes from double-uploading.
   */
  async processOnce(): Promise<void> {
    if (this.running) return;
    this.running = true;
    try {
      let progressed = true;
      while (progressed) {
        progressed = false;
        for (const entry of [...this.entries]) {
          if (entry.failed) continue;
          const { outcome } = await this.processEntry(entry);
          if (outcome === 'transient_failure') return;
          if (outcome === 'completed' || outcome === 'advanced') progressed = true;
        }
      }
    } finally {
      this.running = false;
    }
  }

  /**
   * Attempt a single entry once, right now, and return the completed exam if it
   * lands (following an audio→note transition through to completion). Returns null
   * if it isn't done yet — the entry stays queued for the background to retry. Used
   * for the snappy happy path: upload on stop and jump straight to the note.
   */
  async tryProcess(id: string): Promise<Exam | null> {
    if (this.running) return null;
    this.running = true;
    try {
      // At most two steps: audio upload, then (if it became a note entry) note-gen.
      for (let step = 0; step < 2; step += 1) {
        const entry = this.entries.find((e) => e.id === id);
        if (!entry || entry.failed) return null;
        const { outcome, exam } = await this.processEntry(entry);
        if (outcome === 'completed') return exam ?? null;
        if (outcome !== 'advanced') return null;
      }
      return null;
    } finally {
      this.running = false;
    }
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

  private async processEntry(entry: QueueEntry): Promise<StepResult> {
    try {
      return entry.stage === 'audio'
        ? await this.processAudio(entry)
        : await this.processNote(entry);
    } catch (error) {
      return this.recordFailure(entry, error);
    }
  }

  private async processAudio(entry: AudioEntry): Promise<StepResult> {
    const bytes = await this.files.read(entry.fileName);
    const exam = await this.uploader.generateNote(bytes, entry.mimeType);

    if (exam.notePending) {
      // Transcription succeeded but note-gen didn't: the transcript is safe on
      // the server now, so drop the audio and switch to the cheap note stage.
      await this.safeDeleteFile(entry.fileName);
      const note: NoteEntry = {
        id: entry.id,
        stage: 'note',
        examId: exam.id,
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
    this.onExamReady?.(exam);
    return { outcome: 'completed', exam };
  }

  private async processNote(entry: NoteEntry): Promise<StepResult> {
    const exam = await this.uploader.completeNote(entry.examId);
    this.drop(entry.id);
    await this.persist();
    this.onExamReady?.(exam);
    return { outcome: 'completed', exam };
  }

  private async recordFailure(entry: QueueEntry, error: unknown): Promise<StepResult> {
    const current = this.entries.find((e) => e.id === entry.id);
    if (!current) return { outcome: 'transient_failure' };
    current.attempts += 1;
    current.lastError = error instanceof Error ? error.message : String(error);
    const parked = current.attempts >= this.maxAttempts;
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
    this.onChange?.(this.pending());
  }
}
