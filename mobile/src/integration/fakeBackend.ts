import type { HttpFetch, HttpResponse, HttpRequestInit } from '../services/api/ApiClient';

/**
 * An in-memory stand-in for the real Vet Soap Notetaker backend, faithful to the contract in
 * backend/src/vet_soap_notetaker_backend/app.py: the same routes, the same snake_case JSON
 * shapes, the same status codes (202 on inject, 404 on unknown, 401 on bad auth) and
 * the same "resolve the note fresh at poll time" behaviour for pending injections.
 *
 * It's wired in as the ApiClient's injectable `fetch`, so integration tests exercise
 * the real ApiClient (and screens) end to end without a network or the Python server.
 */

interface RawExam {
  id: string;
  created_at: string;
  patient_name: string | null;
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
  transcript: string;
  note_pending: boolean;
}

interface RawInjection {
  id: string;
  exam_id: string;
  created_at: string;
  status: string;
  outcome: string | null;
}

const NOTE_FIELDS = ['subjective', 'objective', 'assessment', 'plan', 'transcript'] as const;

export interface FakeBackendOptions {
  /** If set, requests must carry `Authorization: Bearer <apiKey>` or get a 401. */
  apiKey?: string;
  /**
   * How POST /api/soap turns uploaded audio into a note (mirrors the real
   * transcribe+generate pipeline). Defaults to a canned note.
   */
  noteForAudio?: (audio: unknown) => Omit<RawExam, 'id' | 'created_at' | 'patient_name' | 'note_pending'>;
  /**
   * When true, transcription still succeeds but note generation fails — POST
   * /api/soap persists a partial exam and returns 202, and POST /api/exams/:id/note
   * returns 502. Toggle it off to simulate the provider coming back.
   */
  failNoteGeneration?: boolean;
}

function response(body: unknown, status = 200): HttpResponse {
  const text = JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => JSON.parse(text),
    text: async () => text,
  };
}

export class FakeBackend {
  private readonly exams: RawExam[] = [];
  private readonly injections: RawInjection[] = [];
  private examSeq = 0;
  private injectionSeq = 0;
  private clockSeq = 0;
  private readonly apiKey: string;
  private readonly noteForAudio: NonNullable<FakeBackendOptions['noteForAudio']>;
  /** Mutable so a test can simulate note generation recovering mid-run. */
  failNoteGeneration: boolean;

  /** Plug this into `new ApiClient({ ..., fetch: backend.fetch })`. */
  readonly fetch: HttpFetch;

  constructor(options: FakeBackendOptions = {}) {
    this.apiKey = options.apiKey ?? '';
    this.failNoteGeneration = options.failNoteGeneration ?? false;
    this.noteForAudio =
      options.noteForAudio ??
      (() => ({
        subjective: 'Patient presented for exam.',
        objective: 'BAR, TPR normal.',
        assessment: 'Healthy.',
        plan: 'Recheck PRN.',
        transcript: 'vet: the patient looks healthy today',
      }));
    this.fetch = this.handle.bind(this);
  }

  /** Seed an exam directly (e.g. to give it a patient name a fresh upload wouldn't). */
  seedExam(overrides: Partial<RawExam> = {}): RawExam {
    const exam: RawExam = {
      id: this.nextExamId(),
      created_at: this.nextClock(),
      patient_name: null,
      subjective: 'S',
      objective: 'O',
      assessment: 'A',
      plan: 'P',
      transcript: 'vet: hello',
      note_pending: false,
      ...overrides,
    };
    this.exams.push(exam);
    return exam;
  }

  /** The raw injection requests currently held (for assertions). */
  injectionRequests(): RawInjection[] {
    return this.injections.map((i) => ({ ...i }));
  }

  private nextExamId(): string {
    this.examSeq += 1;
    return `exam-${this.examSeq}`;
  }

  private nextInjectionId(): string {
    this.injectionSeq += 1;
    return `req-${this.injectionSeq}`;
  }

  private nextClock(): string {
    this.clockSeq += 1;
    return `2026-09-22T00:00:${String(this.clockSeq).padStart(2, '0')}Z`;
  }

  private getExam(id: string): RawExam | undefined {
    return this.exams.find((e) => e.id === id);
  }

  private async handle(url: string, init: HttpRequestInit = {}): Promise<HttpResponse> {
    const { pathname } = new URL(url);
    const method = (init.method ?? 'GET').toUpperCase();
    const headers = init.headers ?? {};

    if (this.apiKey && headers.Authorization !== `Bearer ${this.apiKey}`) {
      return response({ error: 'unauthorized' }, 401);
    }

    // POST /api/soap  — upload audio, persist a generated exam
    if (method === 'POST' && pathname === '/api/soap') {
      if (init.body == null) return response({ error: 'empty request body' }, 400);
      const note = this.noteForAudio(init.body);
      if (this.failNoteGeneration) {
        // Transcription succeeded, note-gen didn't: persist a partial exam (202).
        const partial: RawExam = {
          id: this.nextExamId(),
          created_at: this.nextClock(),
          patient_name: null,
          subjective: '',
          objective: '',
          assessment: '',
          plan: '',
          transcript: note.transcript,
          note_pending: true,
        };
        this.exams.push(partial);
        return response(partial, 202);
      }
      const exam: RawExam = {
        id: this.nextExamId(),
        created_at: this.nextClock(),
        patient_name: null,
        note_pending: false,
        ...note,
      };
      this.exams.push(exam);
      return response(exam);
    }

    // POST /api/soap/regenerate — note generation from a transcript
    if (method === 'POST' && pathname === '/api/soap/regenerate') {
      const body = this.parseJson(init.body);
      const transcript = typeof body?.transcript === 'string' ? body.transcript : '';
      if (!transcript.trim()) return response({ error: 'missing transcript' }, 400);
      const note = this.noteForAudio(null);
      return response({ ...note, transcript });
    }

    // GET /api/history — newest first
    if (method === 'GET' && pathname === '/api/history') {
      return response({ exams: [...this.exams].reverse() });
    }

    const examMatch = pathname.match(/^\/api\/exams\/([^/]+)$/);
    if (examMatch) {
      const id = decodeURIComponent(examMatch[1]);
      if (method === 'GET') {
        const exam = this.getExam(id);
        return exam ? response(exam) : response({ error: 'exam not found' }, 404);
      }
      if (method === 'PUT') {
        return this.updateExam(id, init.body);
      }
      if (method === 'DELETE') {
        const before = this.exams.length;
        for (let i = this.exams.length - 1; i >= 0; i -= 1) {
          if (this.exams[i].id === id) this.exams.splice(i, 1);
        }
        return before === this.exams.length
          ? response({ error: 'exam not found' }, 404)
          : response({ status: 'deleted' });
      }
    }

    // POST /api/exams/:id/note — finish a note-pending exam from its transcript
    const noteMatch = pathname.match(/^\/api\/exams\/([^/]+)\/note$/);
    if (noteMatch && method === 'POST') {
      const id = decodeURIComponent(noteMatch[1]);
      const exam = this.getExam(id);
      if (!exam) return response({ error: 'exam not found' }, 404);
      if (this.failNoteGeneration) return response({ error: 'note gen down' }, 502);
      const note = this.noteForAudio(null);
      exam.subjective = note.subjective;
      exam.objective = note.objective;
      exam.assessment = note.assessment;
      exam.plan = note.plan;
      exam.note_pending = false;
      return response(exam);
    }

    // POST /api/exams/:id/inject — enqueue a remote injection request
    const injectMatch = pathname.match(/^\/api\/exams\/([^/]+)\/inject$/);
    if (injectMatch && method === 'POST') {
      const id = decodeURIComponent(injectMatch[1]);
      if (!this.getExam(id)) return response({ error: 'exam not found' }, 404);
      const req: RawInjection = {
        id: this.nextInjectionId(),
        exam_id: id,
        created_at: this.nextClock(),
        status: 'pending',
        outcome: null,
      };
      this.injections.push(req);
      return response(req, 202);
    }

    // GET /api/injections/pending — desktop poll; note resolved fresh here
    if (method === 'GET' && pathname === '/api/injections/pending') {
      const requests = this.injections
        .filter((i) => i.status === 'pending')
        .map((i) => ({ ...i, exam: this.getExam(i.exam_id) ?? null }));
      return response({ requests });
    }

    // POST /api/injections/:id/ack — desktop acknowledges dispatch
    const ackMatch = pathname.match(/^\/api\/injections\/([^/]+)\/ack$/);
    if (ackMatch && method === 'POST') {
      const id = decodeURIComponent(ackMatch[1]);
      const req = this.injections.find((i) => i.id === id);
      if (!req) return response({ error: 'injection request not found' }, 404);
      const body = this.parseJson(init.body);
      req.status = 'done';
      req.outcome = typeof body?.outcome === 'string' ? body.outcome : 'injected';
      return response(req);
    }

    return response({ error: `no route for ${method} ${pathname}` }, 404);
  }

  private updateExam(id: string, rawBody: unknown): HttpResponse {
    const exam = this.getExam(id);
    if (!exam) return response({ error: 'exam not found' }, 404);
    const body = this.parseJson(rawBody) ?? {};
    const missing = NOTE_FIELDS.filter((f) => typeof body[f] !== 'string');
    if (missing.length) {
      return response({ error: `missing or invalid fields: ${missing.join(', ')}` }, 400);
    }
    if (body.patient_name != null && typeof body.patient_name !== 'string') {
      return response({ error: 'patient_name must be a string' }, 400);
    }
    exam.subjective = body.subjective;
    exam.objective = body.objective;
    exam.assessment = body.assessment;
    exam.plan = body.plan;
    exam.transcript = body.transcript;
    if (body.patient_name != null) exam.patient_name = body.patient_name;
    return response(exam);
  }

  private parseJson(body: unknown): Record<string, any> | null {
    if (typeof body !== 'string') return null;
    try {
      return JSON.parse(body);
    } catch {
      return null;
    }
  }
}
