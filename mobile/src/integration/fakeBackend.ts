import type { HttpFetch, HttpResponse, HttpRequestInit } from '../services/api/ApiClient';

/**
 * An in-memory stand-in for the real Vet Soap Notetaker backend, faithful to the contract in
 * backend/src/vet_soap_notetaker_backend/app.py: the same routes, the same snake_case JSON
 * shapes, the same status codes (202 on inject or a pending note, 404 on unknown, 401 on
 * bad auth) and the same "resolve the note fresh at poll time" behaviour for pending
 * injections.
 *
 * Like the backend, it stores appointments: one recording's transcript plus one exam
 * per animal. The appointment routes (the phone) and the single-exam routes (the
 * desktop) read and write the same records.
 *
 * It's wired in as the ApiClient's injectable `fetch`, so integration tests exercise
 * the real ApiClient (and screens) end to end without a network or the Python server.
 */

interface StoredExam {
  id: string;
  created_at: string;
  patient_name: string | null;
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
  note_pending: boolean;
}

interface StoredAppointment {
  id: string;
  created_at: string;
  transcript: string;
  exams: StoredExam[];
}

/** A single exam as the backend's exam routes return it. */
export interface RawExam extends StoredExam {
  appointment_id: string;
  transcript: string;
}

/** One animal's note as the (fake) note generator produces it. */
export interface RawPatientNote {
  patient_name: string | null;
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
}

export interface GeneratedNotes {
  transcript: string;
  patients: RawPatientNote[];
}

interface RawInjection {
  id: string;
  exam_id: string;
  created_at: string;
  status: string;
  outcome: string | null;
}

const SOAP_FIELDS = ['subjective', 'objective', 'assessment', 'plan'] as const;

export interface FakeBackendOptions {
  /** If set, requests must carry `Authorization: Bearer <apiKey>` or get a 401. */
  apiKey?: string;
  /**
   * How an upload turns audio into a transcript and one note per animal (mirrors the
   * real transcribe+generate pipeline). Defaults to one canned, unnamed animal.
   */
  notesForAudio?: (audio: unknown) => GeneratedNotes;
  /**
   * When true, transcription still succeeds but note generation fails — an upload
   * persists a note-pending appointment and returns 202, and completing it returns
   * 502. Toggle it off to simulate the provider coming back.
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

function notFound(what: string): HttpResponse {
  return response({ error: `${what} not found` }, 404);
}

export class FakeBackend {
  /** Oldest first, like the backend's insertion order. */
  private readonly appointments: StoredAppointment[] = [];
  private readonly injections: RawInjection[] = [];
  private idSeq = 0;
  private injectionSeq = 0;
  private clockSeq = 0;
  private readonly apiKey: string;
  private readonly notesForAudio: NonNullable<FakeBackendOptions['notesForAudio']>;
  /** Mutable so a test can simulate note generation recovering mid-run. */
  failNoteGeneration: boolean;

  /** Plug this into `new ApiClient({ ..., fetch: backend.fetch })`. */
  readonly fetch: HttpFetch;

  constructor(options: FakeBackendOptions = {}) {
    this.apiKey = options.apiKey ?? '';
    this.failNoteGeneration = options.failNoteGeneration ?? false;
    this.notesForAudio =
      options.notesForAudio ??
      (() => ({
        transcript: 'vet: the patient looks healthy today',
        patients: [
          {
            patient_name: null,
            subjective: 'Patient presented for exam.',
            objective: 'BAR, TPR normal.',
            assessment: 'Healthy.',
            plan: 'Recheck PRN.',
          },
        ],
      }));
    this.fetch = this.handle.bind(this);
  }

  /**
   * Seed a one-animal appointment directly (e.g. to give it a patient name a fresh
   * upload wouldn't); returns its exam as the exam routes would.
   */
  seedExam(overrides: Partial<RawExam> = {}): RawExam {
    const { transcript = 'vet: hello', appointment_id: _ignored, ...fields } = overrides;
    const appointment = this.addAppointment(transcript, [
      { patient_name: null, subjective: 'S', objective: 'O', assessment: 'A', plan: 'P' },
    ]);
    Object.assign(appointment.exams[0], fields);
    return this.examJson(appointment, appointment.exams[0]);
  }

  /** The raw injection requests currently held (for assertions). */
  injectionRequests(): RawInjection[] {
    return this.injections.map((i) => ({ ...i }));
  }

  private nextId(prefix: string): string {
    this.idSeq += 1;
    return `${prefix}-${this.idSeq}`;
  }

  private nextInjectionId(): string {
    this.injectionSeq += 1;
    return `req-${this.injectionSeq}`;
  }

  private nextClock(): string {
    this.clockSeq += 1;
    return `2026-09-22T00:00:${String(this.clockSeq).padStart(2, '0')}Z`;
  }

  private newExam(note: RawPatientNote, createdAt: string, notePending = false): StoredExam {
    return {
      id: this.nextId('exam'),
      created_at: createdAt,
      patient_name: note.patient_name,
      subjective: note.subjective,
      objective: note.objective,
      assessment: note.assessment,
      plan: note.plan,
      note_pending: notePending,
    };
  }

  private addAppointment(transcript: string, notes: RawPatientNote[], notePending = false) {
    const id = this.nextId('appt');
    const createdAt = this.nextClock();
    const appointment: StoredAppointment = {
      id,
      created_at: createdAt,
      transcript,
      exams: notes.map((n) => this.newExam(n, createdAt, notePending)),
    };
    this.appointments.push(appointment);
    return appointment;
  }

  private addPendingAppointment(transcript: string): StoredAppointment {
    const empty = { patient_name: null, subjective: '', objective: '', assessment: '', plan: '' };
    return this.addAppointment(transcript, [empty], true);
  }

  private appointmentJson(a: StoredAppointment) {
    return {
      id: a.id,
      created_at: a.created_at,
      transcript: a.transcript,
      note_pending: a.exams.some((e) => e.note_pending),
      exams: a.exams.map((e) => ({ ...e, appointment_id: a.id })),
    };
  }

  private examJson(a: StoredAppointment, e: StoredExam): RawExam {
    return { ...e, appointment_id: a.id, transcript: a.transcript };
  }

  private findAppointment(id: string): StoredAppointment | undefined {
    return this.appointments.find((a) => a.id === id);
  }

  private findExam(id: string): { appointment: StoredAppointment; exam: StoredExam } | undefined {
    for (const appointment of this.appointments) {
      const exam = appointment.exams.find((e) => e.id === id);
      if (exam) return { appointment, exam };
    }
    return undefined;
  }

  /** Fill a pending exam with the first note and add the rest (the backend's complete_pending). */
  private completePending(appointment: StoredAppointment, exam: StoredExam): void {
    const [first, ...others] = this.notesForAudio(null).patients;
    Object.assign(exam, {
      subjective: first.subjective,
      objective: first.objective,
      assessment: first.assessment,
      plan: first.plan,
      patient_name: first.patient_name ?? exam.patient_name,
      note_pending: false,
    });
    const createdAt = this.nextClock();
    appointment.exams.push(...others.map((n) => this.newExam(n, createdAt)));
  }

  private async handle(url: string, init: HttpRequestInit = {}): Promise<HttpResponse> {
    const { pathname } = new URL(url);
    const method = (init.method ?? 'GET').toUpperCase();
    const headers = init.headers ?? {};

    if (this.apiKey && headers.Authorization !== `Bearer ${this.apiKey}`) {
      return response({ error: 'unauthorized' }, 401);
    }

    // --- appointments (the phone) ------------------------------------------

    // POST /api/appointments — upload audio: transcript + one exam per animal
    if (method === 'POST' && pathname === '/api/appointments') {
      if (init.body == null) return response({ error: 'empty request body' }, 400);
      const { transcript, patients } = this.notesForAudio(init.body);
      if (this.failNoteGeneration) {
        return response(this.appointmentJson(this.addPendingAppointment(transcript)), 202);
      }
      return response(this.appointmentJson(this.addAppointment(transcript, patients)));
    }

    // POST /api/appointments/regenerate — notes from a transcript, nothing saved
    if (method === 'POST' && pathname === '/api/appointments/regenerate') {
      const body = this.parseJson(init.body);
      const transcript = typeof body?.transcript === 'string' ? body.transcript : '';
      if (!transcript.trim()) return response({ error: 'missing transcript' }, 400);
      if (this.failNoteGeneration) return response({ error: 'note gen down' }, 502);
      return response({ transcript, patients: this.notesForAudio(null).patients });
    }

    // GET /api/appointments — newest first
    if (method === 'GET' && pathname === '/api/appointments') {
      return response({
        appointments: [...this.appointments].reverse().map((a) => this.appointmentJson(a)),
      });
    }

    // POST /api/appointments/:id/notes — finish a pending appointment (idempotent)
    const notesMatch = pathname.match(/^\/api\/appointments\/([^/]+)\/notes$/);
    if (notesMatch && method === 'POST') {
      const appointment = this.findAppointment(decodeURIComponent(notesMatch[1]));
      if (!appointment) return notFound('appointment');
      const pending = appointment.exams.find((e) => e.note_pending);
      if (pending) {
        if (this.failNoteGeneration) return response({ error: 'note gen down' }, 502);
        this.completePending(appointment, pending);
      }
      return response(this.appointmentJson(appointment));
    }

    const appointmentMatch = pathname.match(/^\/api\/appointments\/([^/]+)$/);
    if (appointmentMatch) {
      const id = decodeURIComponent(appointmentMatch[1]);
      const appointment = this.findAppointment(id);
      if (!appointment) return notFound('appointment');
      if (method === 'GET') return response(this.appointmentJson(appointment));
      if (method === 'PUT') return this.updateAppointment(appointment, init.body);
      if (method === 'DELETE') {
        this.appointments.splice(this.appointments.indexOf(appointment), 1);
        return response({ status: 'deleted' });
      }
    }

    // --- single exams (the desktop) ------------------------------------------

    // POST /api/soap — upload audio; returns the first animal's exam
    if (method === 'POST' && pathname === '/api/soap') {
      if (init.body == null) return response({ error: 'empty request body' }, 400);
      const { transcript, patients } = this.notesForAudio(init.body);
      if (this.failNoteGeneration) {
        const pending = this.addPendingAppointment(transcript);
        return response(this.examJson(pending, pending.exams[0]), 202);
      }
      const appointment = this.addAppointment(transcript, patients);
      return response(this.examJson(appointment, appointment.exams[0]));
    }

    // POST /api/soap/regenerate — the first animal's note flat, plus every animal's
    if (method === 'POST' && pathname === '/api/soap/regenerate') {
      const body = this.parseJson(init.body);
      const transcript = typeof body?.transcript === 'string' ? body.transcript : '';
      if (!transcript.trim()) return response({ error: 'missing transcript' }, 400);
      const { patients } = this.notesForAudio(null);
      return response({ ...patients[0], transcript, patients });
    }

    // GET /api/history — every exam, newest appointment first
    if (method === 'GET' && pathname === '/api/history') {
      const exams = [...this.appointments]
        .reverse()
        .flatMap((a) => a.exams.map((e) => this.examJson(a, e)));
      return response({ exams });
    }

    const examMatch = pathname.match(/^\/api\/exams\/([^/]+)$/);
    if (examMatch) {
      const found = this.findExam(decodeURIComponent(examMatch[1]));
      if (!found) return notFound('exam');
      if (method === 'GET') return response(this.examJson(found.appointment, found.exam));
      if (method === 'PUT') return this.updateExam(found.appointment, found.exam, init.body);
      if (method === 'DELETE') {
        const { appointment, exam } = found;
        appointment.exams.splice(appointment.exams.indexOf(exam), 1);
        if (appointment.exams.length === 0) {
          this.appointments.splice(this.appointments.indexOf(appointment), 1);
        }
        return response({ status: 'deleted' });
      }
    }

    // POST /api/exams/:id/note — finish a note-pending exam from its transcript
    const noteMatch = pathname.match(/^\/api\/exams\/([^/]+)\/note$/);
    if (noteMatch && method === 'POST') {
      const found = this.findExam(decodeURIComponent(noteMatch[1]));
      if (!found) return notFound('exam');
      if (found.exam.note_pending) {
        if (this.failNoteGeneration) return response({ error: 'note gen down' }, 502);
        this.completePending(found.appointment, found.exam);
      }
      return response(this.examJson(found.appointment, found.exam));
    }

    // POST /api/exams/:id/inject — enqueue a remote injection request
    const injectMatch = pathname.match(/^\/api\/exams\/([^/]+)\/inject$/);
    if (injectMatch && method === 'POST') {
      const id = decodeURIComponent(injectMatch[1]);
      if (!this.findExam(id)) return notFound('exam');
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
        .map((i) => {
          const found = this.findExam(i.exam_id);
          return { ...i, exam: found ? this.examJson(found.appointment, found.exam) : null };
        });
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

  private updateAppointment(appointment: StoredAppointment, rawBody: unknown): HttpResponse {
    const body = this.parseJson(rawBody) ?? {};
    if (typeof body.transcript !== 'string') {
      return response({ error: 'missing or invalid field: transcript' }, 400);
    }
    const entries = body.exams;
    if (!Array.isArray(entries) || entries.length === 0) {
      return response({ error: 'exams must be a non-empty list' }, 400);
    }
    for (const entry of entries) {
      if (typeof entry !== 'object' || entry === null) {
        return response({ error: 'each exam must be an object' }, 400);
      }
      const missing = SOAP_FIELDS.filter((f) => typeof entry[f] !== 'string');
      if (missing.length) {
        return response({ error: `missing or invalid fields: ${missing.join(', ')}` }, 400);
      }
    }
    const ids = entries.filter((e) => e.id != null).map((e) => e.id);
    const current = new Map(appointment.exams.map((e) => [e.id, e]));
    if (ids.some((id) => !current.has(id)) || new Set(ids).size !== ids.length) {
      return response({ error: 'exams must belong to this appointment, each at most once' }, 400);
    }
    const createdAt = this.nextClock();
    appointment.transcript = body.transcript;
    appointment.exams = entries.map((entry) => {
      const fields = {
        patient_name: entry.patient_name ?? null,
        subjective: entry.subjective,
        objective: entry.objective,
        assessment: entry.assessment,
        plan: entry.plan,
        note_pending: false,
      };
      const existing = entry.id != null ? current.get(entry.id) : undefined;
      return existing
        ? { ...existing, ...fields }
        : { ...this.newExam(fields, createdAt), note_pending: false };
    });
    return response(this.appointmentJson(appointment));
  }

  private updateExam(appointment: StoredAppointment, exam: StoredExam, rawBody: unknown): HttpResponse {
    const body = this.parseJson(rawBody) ?? {};
    const missing = SOAP_FIELDS.filter((f) => typeof body[f] !== 'string');
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
    exam.note_pending = false;
    if (body.patient_name != null) exam.patient_name = body.patient_name;
    // Optional: when sent, it replaces the transcript for every animal.
    if (typeof body.transcript === 'string') appointment.transcript = body.transcript;
    return response(this.examJson(appointment, exam));
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
