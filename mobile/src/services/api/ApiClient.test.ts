import { ApiClient, ApiClientError, DEFAULT_TIMEOUT_MS, REACHABILITY_TIMEOUT_MS } from './ApiClient';
import type { HttpFetch, HttpResponse } from './ApiClient';

function jsonResponse(body: unknown, init: { ok?: boolean; status?: number } = {}): HttpResponse {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
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

/** Records every request and replays a queued (or default) response. */
function stubFetch(responder: (call: Call) => HttpResponse | Promise<HttpResponse>) {
  const calls: Call[] = [];
  const fetchFn: HttpFetch = async (url, init = {}) => {
    const call: Call = {
      url,
      method: init.method ?? 'GET',
      headers: init.headers ?? {},
      body: init.body,
    };
    calls.push(call);
    return responder(call);
  };
  return { fetchFn, calls };
}

const exampleExam = {
  id: 'exam-1',
  created_at: '2026-09-22T10:00:00Z',
  patient_name: 'Rex',
  subjective: 'S',
  objective: 'O',
  assessment: 'A',
  plan: 'P',
  transcript: 'vet: hello',
};

describe('ApiClient', () => {
  describe('generateNote', () => {
    it('POSTs raw audio bytes to /api/soap with the audio content type and bearer auth', async () => {
      const { fetchFn, calls } = stubFetch(() => jsonResponse(exampleExam));
      const client = new ApiClient({ baseUrl: 'http://host:8000', apiKey: 'secret', fetch: fetchFn });
      const audio = new Uint8Array([1, 2, 3]);

      const exam = await client.generateNote(audio, 'audio/m4a');

      expect(calls).toHaveLength(1);
      expect(calls[0].url).toBe('http://host:8000/api/soap');
      expect(calls[0].method).toBe('POST');
      expect(calls[0].headers['Content-Type']).toBe('audio/m4a');
      expect(calls[0].headers['Authorization']).toBe('Bearer secret');
      expect(calls[0].body).toBe(audio);
      // snake_case backend fields are mapped to camelCase
      expect(exam).toEqual({
        id: 'exam-1',
        createdAt: '2026-09-22T10:00:00Z',
        patientName: 'Rex',
        subjective: 'S',
        objective: 'O',
        assessment: 'A',
        plan: 'P',
        transcript: 'vet: hello',
        notePending: false,
      });
    });

    it('maps note_pending=true (202 partial) to notePending on the exam', async () => {
      const { fetchFn } = stubFetch(() =>
        jsonResponse(
          { ...exampleExam, subjective: '', note_pending: true },
          { status: 202 },
        ),
      );
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      const exam = await client.generateNote(new Uint8Array([1]), 'audio/m4a');

      expect(exam.notePending).toBe(true);
    });

    it('omits the Authorization header when no api key is configured', async () => {
      const { fetchFn, calls } = stubFetch(() => jsonResponse(exampleExam));
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      await client.generateNote(new Uint8Array([0]), 'audio/wav');

      expect(calls[0].headers['Authorization']).toBeUndefined();
    });

    it('raises ApiClientError with the status on a non-2xx response', async () => {
      const { fetchFn } = stubFetch(() =>
        jsonResponse({ error: 'boom' }, { ok: false, status: 502 }),
      );
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      await expect(client.generateNote(new Uint8Array([0]), 'audio/wav')).rejects.toThrow(
        /502/,
      );
      await expect(client.generateNote(new Uint8Array([0]), 'audio/wav')).rejects.toBeInstanceOf(
        ApiClientError,
      );
    });

    it('raises ApiClientError when the network request itself fails', async () => {
      const fetchFn: HttpFetch = async () => {
        throw new Error('connection refused');
      };
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      await expect(client.generateNote(new Uint8Array([0]), 'audio/wav')).rejects.toBeInstanceOf(
        ApiClientError,
      );
    });
  });

  describe('completeNote', () => {
    it('POSTs to /api/exams/:id/note and returns the completed exam', async () => {
      const { fetchFn, calls } = stubFetch(() =>
        jsonResponse({ ...exampleExam, assessment: 'Otitis', note_pending: false }),
      );
      const client = new ApiClient({ baseUrl: 'http://host:8000', apiKey: 'k', fetch: fetchFn });

      const exam = await client.completeNote('exam-1');

      expect(calls[0].url).toBe('http://host:8000/api/exams/exam-1/note');
      expect(calls[0].method).toBe('POST');
      expect(calls[0].headers['Authorization']).toBe('Bearer k');
      expect(exam.assessment).toBe('Otitis');
      expect(exam.notePending).toBe(false);
    });

    it('url-encodes the exam id', async () => {
      const { fetchFn, calls } = stubFetch(() => jsonResponse(exampleExam));
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      await client.completeNote('a/b');

      expect(calls[0].url).toBe('http://host:8000/api/exams/a%2Fb/note');
    });

    it('raises ApiClientError when note generation is still failing (502)', async () => {
      const { fetchFn } = stubFetch(() =>
        jsonResponse({ error: 'provider down' }, { ok: false, status: 502 }),
      );
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      await expect(client.completeNote('exam-1')).rejects.toBeInstanceOf(ApiClientError);
    });
  });

  describe('fetchHistory', () => {
    it('GETs /api/history and returns exams mapped to camelCase', async () => {
      const { fetchFn, calls } = stubFetch(() => jsonResponse({ exams: [exampleExam] }));
      const client = new ApiClient({ baseUrl: 'http://host:8000', apiKey: 'k', fetch: fetchFn });

      const exams = await client.fetchHistory();

      expect(calls[0].url).toBe('http://host:8000/api/history');
      expect(calls[0].method).toBe('GET');
      expect(calls[0].headers['Authorization']).toBe('Bearer k');
      expect(exams).toHaveLength(1);
      expect(exams[0].id).toBe('exam-1');
      expect(exams[0].createdAt).toBe('2026-09-22T10:00:00Z');
      expect(exams[0].patientName).toBe('Rex');
    });
  });

  describe('getExam', () => {
    it('GETs a single exam by id', async () => {
      const { fetchFn, calls } = stubFetch(() => jsonResponse(exampleExam));
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      const exam = await client.getExam('exam-1');

      expect(calls[0].url).toBe('http://host:8000/api/exams/exam-1');
      expect(calls[0].method).toBe('GET');
      expect(exam.id).toBe('exam-1');
    });
  });

  describe('updateExam', () => {
    it('PUTs edited note fields as JSON and returns the updated exam', async () => {
      const updated = { ...exampleExam, assessment: 'edited' };
      const { fetchFn, calls } = stubFetch(() => jsonResponse(updated));
      const client = new ApiClient({ baseUrl: 'http://host:8000', apiKey: 'k', fetch: fetchFn });

      const exam = await client.updateExam('exam-1', {
        subjective: 'S',
        objective: 'O',
        assessment: 'edited',
        plan: 'P',
        transcript: 'vet: hello',
      });

      expect(calls[0].url).toBe('http://host:8000/api/exams/exam-1');
      expect(calls[0].method).toBe('PUT');
      expect(calls[0].headers['Content-Type']).toBe('application/json');
      expect(calls[0].headers['Authorization']).toBe('Bearer k');
      expect(JSON.parse(calls[0].body as string)).toEqual({
        subjective: 'S',
        objective: 'O',
        assessment: 'edited',
        plan: 'P',
        transcript: 'vet: hello',
      });
      expect(exam.assessment).toBe('edited');
    });
  });

  describe('deleteExam', () => {
    it('DELETEs the exam by id with bearer auth', async () => {
      const { fetchFn, calls } = stubFetch(() => jsonResponse({ status: 'deleted' }));
      const client = new ApiClient({ baseUrl: 'http://host:8000', apiKey: 'k', fetch: fetchFn });

      await client.deleteExam('exam-1');

      expect(calls[0].url).toBe('http://host:8000/api/exams/exam-1');
      expect(calls[0].method).toBe('DELETE');
      expect(calls[0].headers['Authorization']).toBe('Bearer k');
    });

    it('url-encodes the exam id', async () => {
      const { fetchFn, calls } = stubFetch(() => jsonResponse({ status: 'deleted' }));
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      await client.deleteExam('a/b');

      expect(calls[0].url).toBe('http://host:8000/api/exams/a%2Fb');
    });

    it('raises ApiClientError when the exam is unknown (404)', async () => {
      const { fetchFn } = stubFetch(() =>
        jsonResponse({ error: 'exam not found' }, { ok: false, status: 404 }),
      );
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      await expect(client.deleteExam('missing')).rejects.toBeInstanceOf(ApiClientError);
      await expect(client.deleteExam('missing')).rejects.toThrow(/404/);
    });
  });

  describe('regenerateNote', () => {
    it('POSTs a hand-corrected transcript to /api/soap/regenerate', async () => {
      const { fetchFn, calls } = stubFetch(() => jsonResponse(exampleExam));
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      await client.regenerateNote('corrected transcript');

      expect(calls[0].url).toBe('http://host:8000/api/soap/regenerate');
      expect(calls[0].method).toBe('POST');
      expect(calls[0].headers['Content-Type']).toBe('application/json');
      expect(JSON.parse(calls[0].body as string)).toEqual({ transcript: 'corrected transcript' });
    });
  });

  describe('requestInjection', () => {
    const pendingRequest = {
      id: 'req-1',
      exam_id: 'exam-1',
      created_at: '2026-09-22T10:05:00Z',
      status: 'pending',
      outcome: null,
    };

    it('POSTs to /api/exams/:id/inject with bearer auth and maps the response', async () => {
      const { fetchFn, calls } = stubFetch(() =>
        jsonResponse(pendingRequest, { status: 202 }),
      );
      const client = new ApiClient({ baseUrl: 'http://host:8000', apiKey: 'secret', fetch: fetchFn });

      const req = await client.requestInjection('exam-1');

      expect(calls[0].url).toBe('http://host:8000/api/exams/exam-1/inject');
      expect(calls[0].method).toBe('POST');
      expect(calls[0].headers['Authorization']).toBe('Bearer secret');
      expect(req).toEqual({
        id: 'req-1',
        examId: 'exam-1',
        createdAt: '2026-09-22T10:05:00Z',
        status: 'pending',
        outcome: null,
      });
    });

    it('url-encodes the exam id', async () => {
      const { fetchFn, calls } = stubFetch(() =>
        jsonResponse(pendingRequest, { status: 202 }),
      );
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      await client.requestInjection('a/b');

      expect(calls[0].url).toBe('http://host:8000/api/exams/a%2Fb/inject');
    });

    it('raises ApiClientError when the exam is unknown (404)', async () => {
      const { fetchFn } = stubFetch(() =>
        jsonResponse({ error: 'exam not found' }, { ok: false, status: 404 }),
      );
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      await expect(client.requestInjection('missing')).rejects.toBeInstanceOf(ApiClientError);
      await expect(client.requestInjection('missing')).rejects.toThrow(/404/);
    });
  });

  describe('timeout', () => {
    // A fetch that never resolves on its own, only rejecting when the request is aborted.
    const hangingFetch: HttpFetch = (_url, init) =>
      new Promise((_resolve, reject) => {
        const signal = init?.signal as AbortSignal | undefined;
        signal?.addEventListener('abort', () => reject(new Error('aborted')));
      });

    it('aborts a hung request after the configured timeout', async () => {
      jest.useFakeTimers();
      try {
        const client = new ApiClient({
          baseUrl: 'http://host:8000',
          fetch: hangingFetch,
          timeoutMs: 500,
        });
        const promise = client.generateNote(new Uint8Array([1]), 'audio/m4a');
        const rejection = expect(promise).rejects.toBeInstanceOf(ApiClientError);
        // advanceTimersByTimeAsync fires the timer AND flushes the microtask
        // chain, so the abort actually propagates through to the rejection.
        await jest.advanceTimersByTimeAsync(500);
        await rejection;
      } finally {
        jest.useRealTimers();
      }
    });

    it('defaults to a timeout that outlasts the backend transcription path, not 60s', async () => {
      jest.useFakeTimers();
      try {
        const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: hangingFetch });
        let settled = false;
        const tracked = client
          .generateNote(new Uint8Array([1]), 'audio/m4a')
          .then(
            () => {
              settled = true;
            },
            () => {
              settled = true;
            },
          );

        // The old 60s default would have aborted here; the new default must not.
        await jest.advanceTimersByTimeAsync(60_000);
        expect(settled).toBe(false);

        // ...but the timer is real: at the configured default it does abort.
        await jest.advanceTimersByTimeAsync(DEFAULT_TIMEOUT_MS - 60_000);
        await tracked;
        expect(settled).toBe(true);
      } finally {
        jest.useRealTimers();
      }
    });
  });

  describe('cancelling from outside', () => {
    function hanging() {
      const signals: AbortSignal[] = [];
      const fetchFn: HttpFetch = (_url, init) =>
        new Promise((_resolve, reject) => {
          const signal = init?.signal as AbortSignal;
          signals.push(signal);
          signal?.addEventListener('abort', () => reject(new Error('Aborted')));
        });
      return { fetchFn, signals };
    }

    it.each([
      ['createAppointment', (c: ApiClient, signal: AbortSignal) => c.createAppointment(new Uint8Array([1]), 'audio/m4a', { signal })],
      ['completeAppointment', (c: ApiClient, signal: AbortSignal) => c.completeAppointment('a1', { signal })],
    ])('%s stops when its signal aborts, as "no answer"', async (_name, call) => {
      const { fetchFn, signals } = hanging();
      // A short own timeout keeps a failing run from hanging for the default 8 minutes.
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn, timeoutMs: 1000 });
      const controller = new AbortController();

      const result = call(client, controller.signal).then(
        () => null,
        (error: ApiClientError) => error,
      );
      await Promise.resolve();
      controller.abort();

      expect(signals[0]?.aborted).toBe(true); // straight away, not at the timeout
      const error = await result;
      expect(error).toBeInstanceOf(ApiClientError);
      expect(error?.status).toBeUndefined();
    });
  });

  describe('checkReachable', () => {
    // Records the signal it was given; never answers until that signal aborts.
    function hangingWithSignal() {
      const signals: AbortSignal[] = [];
      const fetchFn: HttpFetch = (_url, init) =>
        new Promise((_resolve, reject) => {
          const signal = init?.signal as AbortSignal;
          signals.push(signal);
          signal?.addEventListener('abort', () => reject(new Error('aborted')));
        });
      return { fetchFn, signals };
    }

    async function errorOf(promise: Promise<unknown>): Promise<ApiClientError | null> {
      try {
        await promise;
        return null;
      } catch (error) {
        return error as ApiClientError;
      }
    }

    it.each([200, 404, 401])('treats any reply (%i) as reachable without reading the body', async (status) => {
      const json = jest.fn();
      const { fetchFn, calls } = stubFetch(() => ({
        ok: status === 200,
        status,
        json,
        text: async () => '',
      }));
      const client = new ApiClient({ baseUrl: 'http://host:8000/', apiKey: 'k', fetch: fetchFn });

      await expect(client.checkReachable()).resolves.toBeUndefined();

      expect(calls).toHaveLength(1);
      expect(calls[0]).toMatchObject({
        url: 'http://host:8000/api/health',
        method: 'GET',
        headers: { Authorization: 'Bearer k' },
      });
      expect(json).not.toHaveBeenCalled();
    });

    it('has no status when nothing answers', async () => {
      const fetchFn: HttpFetch = async () => {
        throw new TypeError('Network request failed');
      };
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      const error = await errorOf(client.checkReachable());

      expect(error).toBeInstanceOf(ApiClientError);
      expect(error?.status).toBeUndefined();
    });

    it('gives up after its own short timeout, not the long upload one', async () => {
      const { fetchFn, signals } = hangingWithSignal();
      const client = new ApiClient({
        baseUrl: 'http://host:8000',
        fetch: fetchFn,
        reachabilityTimeoutMs: 50,
      });

      const error = await errorOf(client.checkReachable());

      expect(error).toBeInstanceOf(ApiClientError);
      expect(error?.status).toBeUndefined();
      expect(signals[0]?.aborted).toBe(true);
    });

    it('defaults to a 5 second timeout', async () => {
      expect(REACHABILITY_TIMEOUT_MS).toBe(5000);
      jest.useFakeTimers();
      try {
        const { fetchFn, signals } = hangingWithSignal();
        const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });
        const result = errorOf(client.checkReachable());

        await jest.advanceTimersByTimeAsync(4900);
        expect(signals[0]?.aborted).toBe(false);

        await jest.advanceTimersByTimeAsync(100);
        expect(signals[0]?.aborted).toBe(true);
        expect(await result).toBeInstanceOf(ApiClientError);
      } finally {
        jest.useRealTimers();
      }
    });
  });

  describe('error status (did the backend answer?)', () => {
    async function rejectionOf(promise: Promise<unknown>): Promise<ApiClientError> {
      try {
        await promise;
      } catch (error) {
        return error as ApiClientError;
      }
      throw new Error('expected a rejection');
    }

    it('carries the HTTP status when the backend replies with an error', async () => {
      const { fetchFn } = stubFetch(() => jsonResponse({ error: 'upstream' }, { ok: false, status: 502 }));
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      const error = await rejectionOf(client.createAppointment(new Uint8Array([1]), 'audio/m4a'));

      expect(error).toBeInstanceOf(ApiClientError);
      expect(error.status).toBe(502);
    });

    it('carries the status when the backend answers with invalid JSON', async () => {
      const fetchFn: HttpFetch = async () => ({
        ok: true,
        status: 200,
        json: async () => {
          throw new Error('Unexpected token <');
        },
        text: async () => '<html>',
      });
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      const error = await rejectionOf(client.fetchAppointments());

      expect(error.status).toBe(200);
    });

    it('has no status when the request never got an answer', async () => {
      const fetchFn: HttpFetch = async () => {
        throw new TypeError('Network request failed');
      };
      const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: fetchFn });

      const error = await rejectionOf(client.createAppointment(new Uint8Array([1]), 'audio/m4a'));

      expect(error).toBeInstanceOf(ApiClientError);
      expect(error.status).toBeUndefined();
    });

    it('has no status when the request timed out', async () => {
      jest.useFakeTimers();
      try {
        const hanging: HttpFetch = (_url, init) =>
          new Promise((_resolve, reject) => {
            const signal = init?.signal as AbortSignal | undefined;
            signal?.addEventListener('abort', () => reject(new Error('aborted')));
          });
        const client = new ApiClient({ baseUrl: 'http://host:8000', fetch: hanging, timeoutMs: 500 });
        const promise = rejectionOf(client.createAppointment(new Uint8Array([1]), 'audio/m4a'));
        await jest.advanceTimersByTimeAsync(500);

        const error = await promise;

        expect(error).toBeInstanceOf(ApiClientError);
        expect(error.status).toBeUndefined();
      } finally {
        jest.useRealTimers();
      }
    });
  });
});
