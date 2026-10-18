import type {
  Appointment,
  AppointmentDraft,
  AppointmentExam,
  AudioBody,
  Exam,
  InjectionRequest,
  PatientNote,
  SoapNote,
} from './types';

export class ApiClientError extends Error {
  /**
   * The HTTP status when the backend answered (an error reply or a malformed body);
   * undefined when there was no answer at all (unreachable, or timed out). The
   * upload queue retries the latter indefinitely, like the desktop's
   * BackendUnreachableError.
   */
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
  }
}

/**
 * Default per-request timeout. It must outlast the backend's worst-case response
 * for a long recording: Files API transcription (up to 300s) + note generation
 * (up to 120s) + retry backoff. If the phone gave up first, it would show
 * "Upload failed" and drop a recording the backend was still successfully
 * processing. It does *not* make a dead backend fail fast: one that never answers
 * (e.g. a firewall silently dropping packets) hangs a request for this whole time.
 * That's what {@link ApiClient.checkReachable} is for.
 */
export const DEFAULT_TIMEOUT_MS = 480_000;

/**
 * How long {@link ApiClient.checkReachable} waits for any answer at all. Any reply
 * comes back in well under this when the backend is running, however slow it is
 * to transcribe.
 */
export const REACHABILITY_TIMEOUT_MS = 5000;

/** Minimal Response shape we depend on — decouples us from the DOM/undici lib. */
export interface HttpResponse {
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
  text(): Promise<string>;
}

export interface HttpRequestInit {
  method?: string;
  headers?: Record<string, string>;
  body?: unknown;
  signal?: unknown;
}

/** Per-call options for the upload calls the queue makes. */
export interface RequestOptions {
  /** Aborting it cancels the request (the vet discarded the recording mid-upload). */
  signal?: AbortSignal;
}

export type HttpFetch = (url: string, init?: HttpRequestInit) => Promise<HttpResponse>;

export interface ApiClientOptions {
  baseUrl: string;
  apiKey?: string;
  /** Injectable fetch for tests; defaults to the platform global fetch. */
  fetch?: HttpFetch;
  /** Per-request timeout in ms; 0 disables it. */
  timeoutMs?: number;
  /** Timeout for {@link ApiClient.checkReachable}; defaults to REACHABILITY_TIMEOUT_MS. */
  reachabilityTimeoutMs?: number;
}

interface RawExam {
  id: string;
  appointment_id: string;
  created_at: string;
  patient_name?: string | null;
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
  transcript: string;
  note_pending?: boolean;
}

type RawAppointmentExam = Omit<RawExam, 'transcript'>;

interface RawAppointment {
  id: string;
  created_at: string;
  transcript: string;
  note_pending: boolean;
  exams: RawAppointmentExam[];
}

interface RawPatientNote {
  patient_name?: string | null;
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
}

interface RawInjectionRequest {
  id: string;
  exam_id: string;
  created_at: string;
  status: string;
  outcome: string | null;
}

/**
 * REST + sync client for the Vet Soap Notetaker backend. Mirrors the desktop ApiClient's
 * contract (POST /api/soap with raw audio bytes, POST /api/soap/regenerate with a
 * transcript) and adds the cross-device sync surface: /api/history and /api/exams/:id.
 *
 * The backend is the authoritative source of truth for medical records; this client
 * only reads and writes through it — it keeps no local copy.
 */
export class ApiClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly fetch: HttpFetch;
  private readonly timeoutMs: number;
  private readonly reachabilityTimeoutMs: number;

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.apiKey = options.apiKey ?? '';
    this.fetch = options.fetch ?? ((globalThis as { fetch?: HttpFetch }).fetch as HttpFetch);
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.reachabilityTimeoutMs = options.reachabilityTimeoutMs ?? REACHABILITY_TIMEOUT_MS;
  }

  /**
   * Is anything answering at the backend's address? Asks `GET /api/health`, but any
   * HTTP reply counts, even a 404 (an older backend without that route) or a 401;
   * only no answer within the short reachability timeout throws (an
   * {@link ApiClientError} with no status). The upload queue calls this before each
   * upload so a dead backend fails in seconds, not after the long upload timeout.
   */
  async checkReachable(): Promise<void> {
    await this.send('/api/health', { method: 'GET' }, this.reachabilityTimeoutMs);
  }

  /**
   * Upload a recording and get back the persisted exam. If the backend returns a
   * 202 (transcription succeeded but note generation failed), the exam comes back
   * with `notePending: true` and empty note fields — finish it later with
   * {@link completeNote}, which needs no re-upload.
   */
  async generateNote(audio: AudioBody, mimeType: string): Promise<Exam> {
    const raw = await this.request('/api/soap', {
      method: 'POST',
      headers: { 'Content-Type': mimeType },
      body: audio,
    });
    return this.toExam(raw as RawExam);
  }

  /**
   * Finish a note-pending exam: re-run note generation from its already-saved
   * transcript on the backend (no audio re-upload, no re-transcription).
   */
  async completeNote(examId: string): Promise<Exam> {
    const raw = await this.request(`/api/exams/${encodeURIComponent(examId)}/note`, {
      method: 'POST',
    });
    return this.toExam(raw as RawExam);
  }

  /**
   * Upload a recording and get back the appointment: the shared transcript and one
   * exam per animal. On a 202 (transcribed, note generation failed) it comes back
   * with `notePending: true` and a single empty exam — finish it later with
   * {@link completeAppointment}, which needs no re-upload.
   */
  async createAppointment(
    audio: AudioBody,
    mimeType: string,
    options: RequestOptions = {},
  ): Promise<Appointment> {
    const raw = await this.request('/api/appointments', {
      method: 'POST',
      headers: { 'Content-Type': mimeType },
      body: audio,
      signal: options.signal,
    });
    return this.toAppointment(raw as RawAppointment);
  }

  /**
   * Generate a note-pending appointment's notes from its saved transcript (no
   * re-upload). Idempotent: a complete appointment comes back unchanged.
   */
  async completeAppointment(id: string, options: RequestOptions = {}): Promise<Appointment> {
    const raw = await this.request(`/api/appointments/${encodeURIComponent(id)}/notes`, {
      method: 'POST',
      signal: options.signal,
    });
    return this.toAppointment(raw as RawAppointment);
  }

  /** Fetch all appointments (newest first), synced across mobile and desktop sessions. */
  async fetchAppointments(): Promise<Appointment[]> {
    const raw = (await this.request('/api/appointments', { method: 'GET' })) as {
      appointments?: RawAppointment[];
    };
    return (raw.appointments ?? []).map((a) => this.toAppointment(a));
  }

  /** Fetch a single appointment by id. */
  async getAppointment(id: string): Promise<Appointment> {
    const raw = await this.request(`/api/appointments/${encodeURIComponent(id)}`, {
      method: 'GET',
    });
    return this.toAppointment(raw as RawAppointment);
  }

  /**
   * Save the whole appointment: the shared transcript and every animal. Exams with an
   * `id` are updated, ones without are added, and exams left out are deleted.
   */
  async updateAppointment(id: string, draft: AppointmentDraft): Promise<Appointment> {
    const body = {
      transcript: draft.transcript,
      exams: draft.exams.map((exam) => ({
        id: exam.id ?? null,
        patient_name: exam.patientName ?? null,
        subjective: exam.subjective,
        objective: exam.objective,
        assessment: exam.assessment,
        plan: exam.plan,
      })),
    };
    const raw = await this.request(`/api/appointments/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return this.toAppointment(raw as RawAppointment);
  }

  /** Delete an appointment and every animal's exam in it, on every device. */
  async deleteAppointment(id: string): Promise<void> {
    await this.request(`/api/appointments/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }

  /**
   * Re-run note generation from a hand-corrected transcript: one note per animal,
   * nothing saved — the vet reviews them and saves with {@link updateAppointment}.
   */
  async regenerateAppointment(
    transcript: string,
    appointmentId?: string,
  ): Promise<{ transcript: string; patients: PatientNote[] }> {
    const raw = (await this.request('/api/appointments/regenerate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript, appointment_id: appointmentId ?? null }),
    })) as { transcript?: string; patients?: RawPatientNote[] };
    return {
      transcript: raw.transcript ?? transcript,
      patients: (raw.patients ?? []).map((p) => ({
        patientName: p.patient_name ?? undefined,
        subjective: p.subjective,
        objective: p.objective,
        assessment: p.assessment,
        plan: p.plan,
      })),
    };
  }

  /** Fetch all exams (newest first), synced across mobile and desktop sessions. */
  async fetchHistory(): Promise<Exam[]> {
    const raw = (await this.request('/api/history', { method: 'GET' })) as { exams?: RawExam[] };
    return (raw.exams ?? []).map((e) => this.toExam(e));
  }

  /** Fetch a single exam by id. */
  async getExam(id: string): Promise<Exam> {
    const raw = await this.request(`/api/exams/${encodeURIComponent(id)}`, { method: 'GET' });
    return this.toExam(raw as RawExam);
  }

  /** Save the vet's inline edits back to the authoritative backend. */
  async updateExam(id: string, note: SoapNote): Promise<Exam> {
    const raw = await this.request(`/api/exams/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(note),
    });
    return this.toExam(raw as RawExam);
  }

  /** Delete an exam from the shared history so it's gone on every device. */
  async deleteExam(id: string): Promise<void> {
    await this.request(`/api/exams/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }

  /** Re-run note generation from a hand-corrected transcript (no re-transcription). */
  async regenerateNote(transcript: string): Promise<SoapNote> {
    const raw = (await this.request('/api/soap/regenerate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript }),
    })) as Partial<RawExam>;
    return {
      subjective: raw.subjective ?? '',
      objective: raw.objective ?? '',
      assessment: raw.assessment ?? '',
      plan: raw.plan ?? '',
      transcript: raw.transcript ?? transcript,
    };
  }

  /**
   * Ask the backend to have this exam's note pasted into AVImark on the desktop.
   * The phone and the exam-room PC never talk directly: the backend queues the
   * request and the desktop tray app polls for it, so this works regardless of
   * which network the phone is on. Returns immediately once queued (HTTP 202) —
   * the actual paste happens on the desktop moments later.
   */
  async requestInjection(examId: string): Promise<InjectionRequest> {
    const raw = (await this.request(`/api/exams/${encodeURIComponent(examId)}/inject`, {
      method: 'POST',
    })) as RawInjectionRequest;
    return {
      id: raw.id,
      examId: raw.exam_id,
      createdAt: raw.created_at,
      status: raw.status,
      outcome: raw.outcome,
    };
  }

  private authHeaders(extra: Record<string, string> = {}): Record<string, string> {
    const headers = { ...extra };
    if (this.apiKey) {
      headers.Authorization = `Bearer ${this.apiKey}`;
    }
    return headers;
  }

  /**
   * One fetch with a timeout; throws an ApiClientError with no status if nothing
   * answers, or if the caller's own `init.signal` aborts it first.
   */
  private async send(path: string, init: HttpRequestInit, timeoutMs: number): Promise<HttpResponse> {
    const outside = init.signal as AbortSignal | undefined;
    const controller = timeoutMs > 0 || outside ? new AbortController() : null;
    const timer = controller && timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : null;
    const cancel = () => controller?.abort();
    if (outside?.aborted) cancel();
    outside?.addEventListener('abort', cancel);
    try {
      return await this.fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: this.authHeaders(init.headers),
        signal: controller?.signal,
      });
    } catch (error) {
      throw new ApiClientError(`request to ${path} failed: ${(error as Error).message}`);
    } finally {
      if (timer) clearTimeout(timer);
      outside?.removeEventListener('abort', cancel);
    }
  }

  private async request(path: string, init: HttpRequestInit): Promise<unknown> {
    const response = await this.send(path, init, this.timeoutMs);

    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new ApiClientError(`backend returned ${response.status}: ${detail}`, response.status);
    }

    try {
      return await response.json();
    } catch (error) {
      throw new ApiClientError(
        `invalid JSON from ${path}: ${(error as Error).message}`,
        response.status,
      );
    }
  }

  private toAppointment(raw: RawAppointment): Appointment {
    return {
      id: raw.id,
      createdAt: raw.created_at,
      transcript: raw.transcript,
      notePending: raw.note_pending ?? false,
      exams: (raw.exams ?? []).map((e) => this.toAppointmentExam(e)),
    };
  }

  private toAppointmentExam(raw: RawAppointmentExam): AppointmentExam {
    return {
      id: raw.id,
      appointmentId: raw.appointment_id,
      createdAt: raw.created_at,
      patientName: raw.patient_name ?? undefined,
      subjective: raw.subjective,
      objective: raw.objective,
      assessment: raw.assessment,
      plan: raw.plan,
      notePending: raw.note_pending ?? false,
    };
  }

  private toExam(raw: RawExam): Exam {
    return {
      id: raw.id,
      appointmentId: raw.appointment_id,
      createdAt: raw.created_at,
      patientName: raw.patient_name ?? undefined,
      subjective: raw.subjective,
      objective: raw.objective,
      assessment: raw.assessment,
      plan: raw.plan,
      transcript: raw.transcript,
      notePending: raw.note_pending ?? false,
    };
  }
}
