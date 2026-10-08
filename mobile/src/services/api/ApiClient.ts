import type { AudioBody, Exam, InjectionRequest, SoapNote } from './types';

export class ApiClientError extends Error {}

/**
 * Default per-request timeout. It must outlast the backend's worst-case response
 * for a long recording: Files API transcription (up to 300s) + note generation
 * (up to 120s) + retry backoff. If the phone gave up first, it would show
 * "Upload failed" and drop a recording the backend was still successfully
 * processing. A dead/unreachable backend still fails fast (connection error),
 * so this long ceiling only ever applies while the backend is genuinely working.
 */
export const DEFAULT_TIMEOUT_MS = 480_000;

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

export type HttpFetch = (url: string, init?: HttpRequestInit) => Promise<HttpResponse>;

export interface ApiClientOptions {
  baseUrl: string;
  apiKey?: string;
  /** Injectable fetch for tests; defaults to the platform global fetch. */
  fetch?: HttpFetch;
  /** Per-request timeout in ms; 0 disables it. */
  timeoutMs?: number;
}

interface RawExam {
  id: string;
  created_at: string;
  patient_name?: string | null;
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
  transcript: string;
  note_pending?: boolean;
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

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.apiKey = options.apiKey ?? '';
    this.fetch = options.fetch ?? ((globalThis as { fetch?: HttpFetch }).fetch as HttpFetch);
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
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

  private async request(path: string, init: HttpRequestInit): Promise<unknown> {
    const url = `${this.baseUrl}${path}`;
    const controller = this.timeoutMs > 0 ? new AbortController() : null;
    const timer = controller
      ? setTimeout(() => controller.abort(), this.timeoutMs)
      : null;

    let response: HttpResponse;
    try {
      response = await this.fetch(url, {
        ...init,
        headers: this.authHeaders(init.headers),
        signal: controller?.signal,
      });
    } catch (error) {
      throw new ApiClientError(`request to ${path} failed: ${(error as Error).message}`);
    } finally {
      if (timer) clearTimeout(timer);
    }

    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new ApiClientError(`backend returned ${response.status}: ${detail}`);
    }

    try {
      return await response.json();
    } catch (error) {
      throw new ApiClientError(`invalid JSON from ${path}: ${(error as Error).message}`);
    }
  }

  private toExam(raw: RawExam): Exam {
    return {
      id: raw.id,
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
