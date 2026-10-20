import { ApiClientError } from '../api/ApiClient';
import type { Appointment, AppointmentStatus } from '../api/types';
import type { SseEvent } from './sse';

/** Persists the ids of uploaded recordings still being processed. A subset of AsyncStorage. */
export interface WaitingStore {
  load(): Promise<string[]>;
  save(ids: string[]): Promise<void>;
}

/** A recording that finished processing, however it ended — what the toast shows. */
export interface ReadyNote {
  appointmentId: string;
  status: AppointmentStatus;
  /** The animals named in the notes (unnamed ones left out); empty unless complete. */
  patientNames: string[];
}

export interface AppointmentWatcherOptions {
  store: WaitingStore;
  getAppointment: (id: string) => Promise<Appointment>;
  /** Open the backend's event stream; resolves when it ends, rejects when it fails. */
  openStream: (signal: AbortSignal, onEvent: (event: SseEvent) => void) => Promise<void>;
  onReady: (note: ReadyNote) => void;
  /** Injectable for tests: run `fn` after `ms`, returning a cancel function. */
  schedule?: (fn: () => void, ms: number) => () => void;
}

const MIN_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30_000;

function defaultSchedule(fn: () => void, ms: number): () => void {
  const timer = setTimeout(fn, ms);
  return () => clearTimeout(timer);
}

function isFinished(status: AppointmentStatus): boolean {
  return status !== 'processing';
}

/** What to announce for an appointment that has finished processing. */
export function readyNoteOf(appointment: Appointment): ReadyNote {
  return {
    appointmentId: appointment.id,
    status: appointment.status,
    patientNames:
      appointment.status === 'complete'
        ? appointment.exams.map((e) => e.patientName).filter((n): n is string => Boolean(n))
        : [],
  };
}

/**
 * Hears when the recordings this phone uploaded finish processing on the backend,
 * so the app can say so. Uploads go async (the backend replies 202 as soon as it has
 * the audio), and the backend announces each outcome on its `/api/events` stream.
 *
 * The stream is open only while the app is in the foreground *and* something is
 * waiting; it reconnects with backoff (1 s doubling to 30 s) if it drops. Events
 * aren't replayed, so each time the stream says `ready` the watcher re-reads every
 * appointment it's waiting on once — a note that finished while the app was in the
 * background, or between streams, is still announced. Nothing polls.
 *
 * Pure and injectable like UploadQueue: storage, the backend and timers are all
 * passed in, so it runs in Node against fakes.
 */
export class AppointmentWatcher {
  private ids: string[] = [];
  private active = false;
  private stopped = false;
  private connection: AbortController | null = null;
  private cancelRetry: (() => void) | null = null;
  private backoffMs = MIN_BACKOFF_MS;
  private readonly schedule: (fn: () => void, ms: number) => () => void;

  constructor(private readonly options: AppointmentWatcherOptions) {
    this.schedule = options.schedule ?? defaultSchedule;
  }

  /** Restore what was being waited on (call once on app start). */
  async load(): Promise<void> {
    const loaded = await this.options.store.load();
    this.ids = [...new Set([...loaded, ...this.ids])];
    this.sync();
  }

  /** Wait on an uploaded recording until the backend has finished with it. */
  async wait(appointmentId: string): Promise<void> {
    if (this.ids.includes(appointmentId)) return;
    this.ids = [...this.ids, appointmentId];
    await this.options.store.save(this.ids);
    this.sync();
  }

  /** Whether the app is in the foreground (AppState 'active'). */
  setActive(active: boolean): void {
    this.active = active;
    this.sync();
  }

  stop(): void {
    this.stopped = true;
    this.sync();
  }

  private shouldListen(): boolean {
    return !this.stopped && this.active && this.ids.length > 0;
  }

  private sync(): void {
    if (this.shouldListen()) {
      if (!this.connection && !this.cancelRetry) this.connect();
      return;
    }
    this.cancelRetry?.();
    this.cancelRetry = null;
    this.connection?.abort();
    this.connection = null;
  }

  private connect(): void {
    const connection = new AbortController();
    this.connection = connection;
    const onEvent = (event: SseEvent) => {
      if (connection.signal.aborted) return;
      if (event.event === 'ready') {
        this.backoffMs = MIN_BACKOFF_MS;
        void this.catchUp();
      } else if (event.event === 'appointment') {
        this.onAppointmentEvent(event.data);
      }
    };
    const ended = () => {
      if (this.connection !== connection) return; // closed on purpose
      this.connection = null;
      if (!this.shouldListen()) return;
      const delay = this.backoffMs;
      this.backoffMs = Math.min(this.backoffMs * 2, MAX_BACKOFF_MS);
      this.cancelRetry = this.schedule(() => {
        this.cancelRetry = null;
        if (this.shouldListen()) this.connect();
      }, delay);
    };
    this.options.openStream(connection.signal, onEvent).then(ended, ended);
  }

  private onAppointmentEvent(data: string): void {
    let parsed: { id?: unknown; status?: unknown; patient_names?: unknown };
    try {
      parsed = JSON.parse(data);
    } catch {
      return;
    }
    if (typeof parsed.id !== 'string' || typeof parsed.status !== 'string') return;
    if (!this.ids.includes(parsed.id)) return;
    const status = parsed.status as AppointmentStatus;
    if (!isFinished(status)) return;
    const names = Array.isArray(parsed.patient_names)
      ? parsed.patient_names.filter((n): n is string => typeof n === 'string' && n.length > 0)
      : [];
    void this.finish({ appointmentId: parsed.id, status, patientNames: names });
  }

  /** Re-read everything being waited on: catches outcomes no event was heard for. */
  private async catchUp(): Promise<void> {
    await Promise.all(
      [...this.ids].map(async (id) => {
        let appointment: Appointment;
        try {
          appointment = await this.options.getAppointment(id);
        } catch (error) {
          // Deleted (by the vet, on any device): nothing left to wait for.
          if (error instanceof ApiClientError && error.status === 404) await this.forget(id);
          return;
        }
        if (!isFinished(appointment.status)) return;
        await this.finish(readyNoteOf(appointment));
      }),
    );
  }

  private async finish(note: ReadyNote): Promise<void> {
    if (!this.ids.includes(note.appointmentId)) return; // already announced
    await this.forget(note.appointmentId);
    this.options.onReady(note);
  }

  private async forget(id: string): Promise<void> {
    if (!this.ids.includes(id)) return;
    this.ids = this.ids.filter((i) => i !== id);
    await this.options.store.save(this.ids);
    this.sync();
  }
}
