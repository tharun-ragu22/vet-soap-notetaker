import { ApiClient, ApiClientError } from './ApiClient';
import type { HttpFetch, HttpResponse } from './ApiClient';

function jsonResponse(body: unknown, status = 200): HttpResponse {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
}

interface Call {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

function stubFetch(responder: (call: Call) => HttpResponse) {
  const calls: Call[] = [];
  const fetchFn: HttpFetch = async (url, init = {}) => {
    const call = { url, method: init.method ?? 'GET', headers: init.headers ?? {}, body: init.body };
    calls.push(call);
    return responder(call);
  };
  return { fetchFn, calls };
}

function client(fetchFn: HttpFetch) {
  return new ApiClient({ baseUrl: 'http://host:8000/', apiKey: 'secret', fetch: fetchFn });
}

const rawExam = (id: string, name: string | null, plan: string) => ({
  id,
  appointment_id: 'appt-1',
  created_at: '2026-10-16T10:00:00Z',
  patient_name: name,
  subjective: 'S',
  objective: 'O',
  assessment: 'A',
  plan,
  note_pending: false,
});

const rawAppointment = {
  id: 'appt-1',
  created_at: '2026-10-16T10:00:00Z',
  transcript: 'two dogs today',
  note_pending: false,
  exams: [rawExam('exam-1', 'Bella', 'P1'), rawExam('exam-2', null, 'P2')],
};

const appointment = {
  id: 'appt-1',
  createdAt: '2026-10-16T10:00:00Z',
  transcript: 'two dogs today',
  notePending: false,
  status: 'complete',
  exams: [
    {
      id: 'exam-1',
      appointmentId: 'appt-1',
      createdAt: '2026-10-16T10:00:00Z',
      patientName: 'Bella',
      subjective: 'S',
      objective: 'O',
      assessment: 'A',
      plan: 'P1',
      notePending: false,
    },
    {
      id: 'exam-2',
      appointmentId: 'appt-1',
      createdAt: '2026-10-16T10:00:00Z',
      patientName: undefined,
      subjective: 'S',
      objective: 'O',
      assessment: 'A',
      plan: 'P2',
      notePending: false,
    },
  ],
};

describe('ApiClient appointments', () => {
  it('createAppointment POSTs the audio and maps the appointment', async () => {
    const { fetchFn, calls } = stubFetch(() => jsonResponse(rawAppointment));
    const audio = new Uint8Array([1, 2, 3]);

    const result = await client(fetchFn).createAppointment(audio, 'audio/m4a');

    expect(calls[0]).toMatchObject({
      url: 'http://host:8000/api/appointments',
      method: 'POST',
      body: audio,
    });
    expect(calls[0].headers).toMatchObject({
      'Content-Type': 'audio/m4a',
      Authorization: 'Bearer secret',
    });
    expect(result).toEqual(appointment);
  });

  it('createAppointment asks for async processing and sends the recording key', async () => {
    const { fetchFn, calls } = stubFetch(() => jsonResponse(rawAppointment));

    await client(fetchFn).createAppointment(new Uint8Array([1]), 'audio/m4a', {
      idempotencyKey: 'rec-uuid-1',
    });

    expect(calls[0].headers).toMatchObject({
      Prefer: 'respond-async',
      'Idempotency-Key': 'rec-uuid-1',
    });
  });

  it('createAppointment sends no key when none is given', async () => {
    const { fetchFn, calls } = stubFetch(() => jsonResponse(rawAppointment));

    await client(fetchFn).createAppointment(new Uint8Array([1]), 'audio/m4a');

    expect(calls[0].headers['Idempotency-Key']).toBeUndefined();
  });

  it('createAppointment maps a 202 processing reply', async () => {
    const processing = {
      ...rawAppointment,
      transcript: '',
      note_pending: true,
      status: 'processing',
      exams: [{ ...rawExam('exam-1', null, ''), note_pending: true }],
    };
    const { fetchFn } = stubFetch(() => jsonResponse(processing, 202));

    const result = await client(fetchFn).createAppointment(new Uint8Array([1]), 'audio/m4a');

    expect(result.status).toBe('processing');
  });

  it.each(['processing', 'note_pending', 'failed', 'no_speech', 'complete'] as const)(
    'maps the backend status %s',
    async (status) => {
      const { fetchFn } = stubFetch(() => jsonResponse({ ...rawAppointment, status }));
      expect((await client(fetchFn).getAppointment('appt-1')).status).toBe(status);
    },
  );

  it('derives the status from note_pending for a backend that sends none', async () => {
    const pending = { ...rawAppointment, note_pending: true };
    const { fetchFn } = stubFetch((call) =>
      jsonResponse(call.url.endsWith('appt-1') ? rawAppointment : pending),
    );

    expect((await client(fetchFn).getAppointment('appt-1')).status).toBe('complete');
    expect((await client(fetchFn).getAppointment('appt-2')).status).toBe('note_pending');
  });

  it('retryAppointment POSTs to the retry route', async () => {
    const { fetchFn, calls } = stubFetch(() =>
      jsonResponse({ ...rawAppointment, status: 'processing' }, 202),
    );

    const result = await client(fetchFn).retryAppointment('appt/1');

    expect(calls[0]).toMatchObject({
      url: 'http://host:8000/api/appointments/appt%2F1/retry',
      method: 'POST',
    });
    expect(result.status).toBe('processing');
  });

  it('eventStream points at /api/events with the bearer key', () => {
    const { fetchFn } = stubFetch(() => jsonResponse({}));

    expect(client(fetchFn).eventStream()).toEqual({
      url: 'http://host:8000/api/events',
      headers: { Authorization: 'Bearer secret', Accept: 'text/event-stream' },
    });
  });

  it('createAppointment maps a 202 to a note-pending appointment', async () => {
    const pending = {
      ...rawAppointment,
      note_pending: true,
      exams: [{ ...rawExam('exam-1', null, ''), note_pending: true }],
    };
    const { fetchFn } = stubFetch(() => jsonResponse(pending, 202));

    const result = await client(fetchFn).createAppointment(new Uint8Array([1]), 'audio/m4a');

    expect(result.notePending).toBe(true);
    expect(result.exams[0].notePending).toBe(true);
  });

  it('completeAppointment POSTs to the notes route', async () => {
    const { fetchFn, calls } = stubFetch(() => jsonResponse(rawAppointment));

    const result = await client(fetchFn).completeAppointment('appt/1');

    expect(calls[0]).toMatchObject({
      url: 'http://host:8000/api/appointments/appt%2F1/notes',
      method: 'POST',
    });
    expect(result).toEqual(appointment);
  });

  it('fetchAppointments lists them newest first as the backend returns them', async () => {
    const { fetchFn, calls } = stubFetch(() =>
      jsonResponse({ appointments: [rawAppointment, { ...rawAppointment, id: 'appt-0' }] }),
    );

    const result = await client(fetchFn).fetchAppointments();

    expect(calls[0]).toMatchObject({ url: 'http://host:8000/api/appointments', method: 'GET' });
    expect(result.map((a) => a.id)).toEqual(['appt-1', 'appt-0']);
    expect(result[0]).toEqual(appointment);
  });

  it('getAppointment fetches one by id', async () => {
    const { fetchFn, calls } = stubFetch(() => jsonResponse(rawAppointment));

    expect(await client(fetchFn).getAppointment('appt-1')).toEqual(appointment);
    expect(calls[0]).toMatchObject({ url: 'http://host:8000/api/appointments/appt-1', method: 'GET' });
  });

  it('updateAppointment PUTs the transcript and every animal in snake_case', async () => {
    const { fetchFn, calls } = stubFetch(() => jsonResponse(rawAppointment));

    const result = await client(fetchFn).updateAppointment('appt-1', {
      transcript: 'corrected',
      exams: [
        { id: 'exam-1', patientName: 'Bella', subjective: 's', objective: 'o', assessment: 'a', plan: 'p' },
        { subjective: 's2', objective: 'o2', assessment: 'a2', plan: 'p2' },
      ],
    });

    expect(calls[0]).toMatchObject({ url: 'http://host:8000/api/appointments/appt-1', method: 'PUT' });
    expect(calls[0].headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(calls[0].body as string)).toEqual({
      transcript: 'corrected',
      exams: [
        { id: 'exam-1', patient_name: 'Bella', subjective: 's', objective: 'o', assessment: 'a', plan: 'p' },
        { id: null, patient_name: null, subjective: 's2', objective: 'o2', assessment: 'a2', plan: 'p2' },
      ],
    });
    expect(result).toEqual(appointment);
  });

  it('deleteAppointment DELETEs it', async () => {
    const { fetchFn, calls } = stubFetch(() => jsonResponse({ status: 'deleted' }));

    await client(fetchFn).deleteAppointment('appt-1');

    expect(calls[0]).toMatchObject({ url: 'http://host:8000/api/appointments/appt-1', method: 'DELETE' });
  });

  it('regenerateAppointment returns every animal without saving', async () => {
    const { fetchFn, calls } = stubFetch(() =>
      jsonResponse({
        transcript: 'corrected',
        patients: [
          { patient_name: 'Bella', subjective: 's', objective: 'o', assessment: 'a', plan: 'p' },
          { patient_name: null, subjective: 's2', objective: 'o2', assessment: 'a2', plan: 'p2' },
        ],
      }),
    );

    const result = await client(fetchFn).regenerateAppointment('corrected', 'appt-1');

    expect(calls[0]).toMatchObject({ url: 'http://host:8000/api/appointments/regenerate', method: 'POST' });
    expect(JSON.parse(calls[0].body as string)).toEqual({
      transcript: 'corrected',
      appointment_id: 'appt-1',
    });
    expect(result).toEqual({
      transcript: 'corrected',
      patients: [
        { patientName: 'Bella', subjective: 's', objective: 'o', assessment: 'a', plan: 'p' },
        { patientName: undefined, subjective: 's2', objective: 'o2', assessment: 'a2', plan: 'p2' },
      ],
    });
  });

  it('surfaces a backend error as ApiClientError', async () => {
    const { fetchFn } = stubFetch(() => jsonResponse({ error: 'appointment not found' }, 404));

    await expect(client(fetchFn).getAppointment('nope')).rejects.toThrow(ApiClientError);
  });

  it('single exams carry their appointment id', async () => {
    const { fetchFn } = stubFetch(() => jsonResponse({ ...rawExam('exam-1', 'Bella', 'P'), transcript: 't' }));

    const exam = await client(fetchFn).getExam('exam-1');

    expect(exam.appointmentId).toBe('appt-1');
    expect(exam.transcript).toBe('t');
  });
});
