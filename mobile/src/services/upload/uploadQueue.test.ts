import { ApiClientError } from '../api/ApiClient';
import type { Appointment } from '../api/types';
import { UploadQueue, type UploadQueueOptions } from './uploadQueue';
import type { FileStore, QueueEntry, QueueStore, QueueUploader } from './types';

class FakeQueueStore implements QueueStore {
  saved: QueueEntry[] = [];
  async load(): Promise<QueueEntry[]> {
    return JSON.parse(JSON.stringify(this.saved));
  }
  async save(entries: QueueEntry[]): Promise<void> {
    this.saved = JSON.parse(JSON.stringify(entries));
  }
}

class FakeFileStore implements FileStore {
  files = new Map<string, Uint8Array>();
  deleted: string[] = [];
  private seq = 0;
  async save(_uri: string): Promise<string> {
    const name = `file-${this.seq++}.m4a`;
    this.files.set(name, new Uint8Array([1, 2, 3]));
    return name;
  }
  async read(name: string): Promise<Uint8Array> {
    const bytes = this.files.get(name);
    if (!bytes) throw new Error(`no such file ${name}`);
    return bytes;
  }
  async delete(name: string): Promise<void> {
    this.deleted.push(name);
    this.files.delete(name);
  }
}

function appointment(overrides: Partial<Appointment> = {}): Appointment {
  return {
    id: 'a1',
    createdAt: '2026-01-01T00:00:00Z',
    transcript: '',
    notePending: false,
    exams: [],
    ...overrides,
  };
}

function makeUploader(): QueueUploader & { createAppointment: jest.Mock; completeAppointment: jest.Mock } {
  return {
    createAppointment: jest.fn(async () => appointment()),
    completeAppointment: jest.fn(async () => appointment()),
  };
}

function makeQueue(opts: Partial<UploadQueueOptions> = {}) {
  const store = (opts.store as FakeQueueStore) ?? new FakeQueueStore();
  const files = (opts.files as FakeFileStore) ?? new FakeFileStore();
  const uploader = (opts.uploader as ReturnType<typeof makeUploader>) ?? makeUploader();
  const onAppointmentReady = jest.fn();
  const onChange = jest.fn();
  let seq = 0;
  const queue = new UploadQueue({
    store,
    files,
    uploader,
    idFactory: () => `q${seq++}`,
    now: () => 'T',
    onAppointmentReady,
    onChange,
    ...opts,
  });
  return { queue, store, files, uploader, onAppointmentReady, onChange };
}

/** Let the queue's async steps run until `mock` has been called. */
async function waitForCall(mock: jest.Mock): Promise<void> {
  for (let i = 0; i < 50 && mock.mock.calls.length === 0; i += 1) {
    await new Promise<void>((resolve) => setImmediate(() => resolve()));
  }
  expect(mock).toHaveBeenCalled();
}

const REC = { uri: 'file:///cache/rec.m4a', mimeType: 'audio/m4a', durationMillis: 3000 };

describe('UploadQueue', () => {
  it('persists the recording to disk and metadata before any upload (persist-first)', async () => {
    const { queue, store, files } = makeQueue();

    const entry = await queue.enqueue(REC);

    expect(entry.stage).toBe('audio');
    expect(files.files.size).toBe(1); // bytes saved durably
    expect(store.saved).toHaveLength(1); // metadata persisted
    expect(store.saved[0]).toMatchObject({ stage: 'audio', mimeType: 'audio/m4a', attempts: 0 });
  });

  it('restores queued entries from the store on load (survives a restart)', async () => {
    const store = new FakeQueueStore();
    await makeQueue({ store }).queue.enqueue(REC);

    const { queue } = makeQueue({ store });
    await queue.load();

    expect(queue.pending()).toHaveLength(1);
  });

  it('uploads an audio entry, then removes it and deletes the file on success', async () => {
    const { queue, files, uploader, onAppointmentReady } = makeQueue();
    uploader.createAppointment.mockResolvedValue(appointment({ id: 'done', transcript: 'Otitis' }));

    await queue.enqueue(REC);
    await queue.processOnce();

    expect(queue.pending()).toHaveLength(0);
    expect(files.deleted).toHaveLength(1);
    expect(onAppointmentReady).toHaveBeenCalledWith(expect.objectContaining({ id: 'done' }));
  });

  it('on a 202 partial: switches the entry to the note stage and deletes the audio file', async () => {
    const { queue, files, uploader, onAppointmentReady } = makeQueue();
    uploader.createAppointment.mockResolvedValue(appointment({ id: 'partial', notePending: true }));
    uploader.completeAppointment.mockRejectedValue(new Error('note gen still down'));

    await queue.enqueue(REC);
    await queue.processOnce();

    const pending = queue.pending();
    expect(pending).toHaveLength(1);
    expect(pending[0]).toMatchObject({ stage: 'note', appointmentId: 'partial' });
    expect(files.deleted).toHaveLength(1); // audio no longer needed
    expect(uploader.createAppointment).toHaveBeenCalledTimes(1);
    expect(onAppointmentReady).not.toHaveBeenCalled();
  });

  it('completes a note-stage entry without re-uploading audio', async () => {
    const { queue, uploader, onAppointmentReady } = makeQueue();
    uploader.createAppointment.mockResolvedValue(appointment({ id: 'x1', notePending: true }));
    uploader.completeAppointment.mockResolvedValue(appointment({ id: 'x1', transcript: 'A', notePending: false }));

    await queue.enqueue(REC);
    await queue.processOnce();

    expect(uploader.completeAppointment).toHaveBeenCalledWith('x1', expect.anything());
    expect(queue.pending()).toHaveLength(0);
    expect(onAppointmentReady).toHaveBeenCalledWith(expect.objectContaining({ id: 'x1', transcript: 'A' }));
  });

  it('keeps the entry and file on a transient failure, recording the attempt', async () => {
    const { queue, files, uploader, onAppointmentReady } = makeQueue();
    uploader.createAppointment.mockRejectedValue(new Error('connection refused'));

    await queue.enqueue(REC);
    await queue.processOnce();

    const pending = queue.pending();
    expect(pending).toHaveLength(1);
    expect(pending[0]).toMatchObject({ stage: 'audio', attempts: 1, lastError: 'connection refused' });
    expect(files.deleted).toHaveLength(0); // audio preserved for retry
    expect(onAppointmentReady).not.toHaveBeenCalled();
  });

  it('processes FIFO and stops the pass at the first failure', async () => {
    const { queue, uploader } = makeQueue();
    uploader.createAppointment.mockRejectedValue(new Error('down'));

    await queue.enqueue(REC);
    await queue.enqueue(REC);
    await queue.processOnce();

    const [first, second] = queue.pending();
    expect(first.attempts).toBe(1);
    expect(second.attempts).toBe(0); // never reached this pass
    expect(uploader.createAppointment).toHaveBeenCalledTimes(1);
  });

  it('parks an entry after maxAttempts and then skips it', async () => {
    const { queue, uploader } = makeQueue({ maxAttempts: 2 });
    uploader.createAppointment.mockRejectedValue(new Error('down'));

    await queue.enqueue(REC);
    await queue.processOnce(); // attempt 1
    await queue.processOnce(); // attempt 2 -> parked
    await queue.processOnce(); // skipped

    expect(queue.pending()[0]).toMatchObject({ attempts: 2, failed: true });
    expect(uploader.createAppointment).toHaveBeenCalledTimes(2);
  });

  it('a parked entry does not block the ones behind it', async () => {
    const { queue, uploader, onAppointmentReady } = makeQueue({ maxAttempts: 1 });
    // First call (entry A) fails and parks immediately; second call (entry B) succeeds.
    uploader.createAppointment
      .mockRejectedValueOnce(new Error('poison'))
      .mockResolvedValueOnce(appointment({ id: 'B' }));

    await queue.enqueue(REC); // A
    await queue.enqueue(REC); // B
    await queue.processOnce();

    expect(queue.pending()).toHaveLength(1); // only the parked A remains
    expect(queue.pending()[0]).toMatchObject({ failed: true });
    expect(onAppointmentReady).toHaveBeenCalledWith(expect.objectContaining({ id: 'B' }));
  });

  it('on load, keeps queued audio from before appointments and drops old note-stage entries', async () => {
    // Audio entries are unchanged. A note entry from before appointments points at
    // an exam, not an appointment; its transcript is safe on the backend, where the
    // pending appointment shows in History, so it's dropped rather than retried.
    const store = new FakeQueueStore();
    store.saved = [
      { id: 'old-audio', stage: 'audio', fileName: 'f.m4a', mimeType: 'audio/m4a', createdAt: 'T',
        durationMillis: 1, attempts: 0 },
      { id: 'old-note', stage: 'note', examId: 'exam-1', createdAt: 'T', attempts: 2 } as unknown as QueueEntry,
    ];
    const { queue } = makeQueue({ store });

    await queue.load();

    expect(queue.pending().map((e) => e.id)).toEqual(['old-audio']);
    expect(store.saved.map((e) => e.id)).toEqual(['old-audio']);
  });

  it('remove discards the entry and deletes its file', async () => {
    const { queue, files } = makeQueue();
    const entry = await queue.enqueue(REC);

    await queue.remove(entry.id);

    expect(queue.pending()).toHaveLength(0);
    expect(files.deleted).toHaveLength(1);
  });

  it('does not run overlapping passes (run-lock)', async () => {
    const { queue, uploader } = makeQueue();
    let release!: (a: Appointment) => void;
    uploader.createAppointment.mockImplementation(
      () => new Promise<Appointment>((resolve) => { release = resolve; }),
    );

    await queue.enqueue(REC);
    const first = queue.processOnce(); // starts, awaits the in-flight upload
    await queue.processOnce(); // locked out, returns immediately

    expect(uploader.createAppointment).toHaveBeenCalledTimes(1);
    release(appointment());
    await first;
  });

  describe('tryProcess (immediate single-entry attempt)', () => {
    it('returns the completed appointment on an immediate success', async () => {
      const { queue, uploader } = makeQueue();
      uploader.createAppointment.mockResolvedValue(appointment({ id: 'fast', transcript: 'A' }));

      const entry = await queue.enqueue(REC);
      const result = await queue.tryProcess(entry.id);

      expect(result).toMatchObject({ id: 'fast', transcript: 'A' });
      expect(queue.pending()).toHaveLength(0);
    });

    it('carries a 202 partial through to the completed note in one call', async () => {
      const { queue, uploader } = makeQueue();
      uploader.createAppointment.mockResolvedValue(appointment({ id: 'p1', notePending: true }));
      uploader.completeAppointment.mockResolvedValue(appointment({ id: 'p1', transcript: 'Done', notePending: false }));

      const entry = await queue.enqueue(REC);
      const result = await queue.tryProcess(entry.id);

      expect(result).toMatchObject({ id: 'p1', transcript: 'Done' });
      expect(uploader.completeAppointment).toHaveBeenCalledWith('p1', expect.anything());
      expect(queue.pending()).toHaveLength(0);
    });

    it('returns null and leaves the entry queued when the attempt fails', async () => {
      const { queue, uploader } = makeQueue();
      uploader.createAppointment.mockRejectedValue(new Error('down'));

      const entry = await queue.enqueue(REC);
      const result = await queue.tryProcess(entry.id);

      expect(result).toBeNull();
      expect(queue.pending()).toHaveLength(1);
      expect(queue.pending()[0].attempts).toBe(1);
    });
  });

  it('start() drains on an interval', async () => {
    jest.useFakeTimers();
    try {
      const { queue, uploader } = makeQueue();
      uploader.createAppointment.mockResolvedValue(appointment());
      await queue.enqueue(REC);

      queue.start(1000);
      await jest.advanceTimersByTimeAsync(1000);

      expect(uploader.createAppointment).toHaveBeenCalledTimes(1);
      queue.stop();
    } finally {
      jest.useRealTimers();
    }
  });

  describe('unreachable backend vs backend errors', () => {
    const unreachable = () => new ApiClientError('request failed: Network request failed');
    const badGateway = () => new ApiClientError('backend returned 502: {}', 502);

    it('never gives up on a recording while the backend simply cannot be reached', async () => {
      const { queue, uploader } = makeQueue({ maxAttempts: 2, now: () => '2026-10-16T15:50:00Z' });
      uploader.createAppointment.mockRejectedValue(unreachable());

      await queue.enqueue(REC);
      for (let i = 0; i < 5; i += 1) await queue.processOnce();

      const [entry] = queue.pending();
      expect(entry.failed).toBeFalsy();
      expect(entry.attempts).toBe(0);
      expect(entry).toMatchObject({ lastErrorKind: 'unreachable', lastAttemptAt: '2026-10-16T15:50:00Z' });
      expect(entry.lastStatus).toBeUndefined();
      expect(uploader.createAppointment).toHaveBeenCalledTimes(5);
    });

    it('still stops the pass at an unreachable backend', async () => {
      const { queue, uploader } = makeQueue();
      uploader.createAppointment.mockRejectedValue(unreachable());

      await queue.enqueue(REC);
      await queue.enqueue(REC);
      await queue.processOnce();

      expect(uploader.createAppointment).toHaveBeenCalledTimes(1);
    });

    it('marks a recording failed after maxAttempts backend error replies', async () => {
      const { queue, uploader } = makeQueue({ maxAttempts: 2 });
      uploader.createAppointment.mockRejectedValue(badGateway());

      await queue.enqueue(REC);
      await queue.processOnce();
      await queue.processOnce();

      expect(queue.pending()[0]).toMatchObject({
        failed: true,
        attempts: 2,
        lastErrorKind: 'backend',
        lastStatus: 502,
      });
    });

    it('counts any other error, as kind "other"', async () => {
      const { queue, uploader } = makeQueue({ maxAttempts: 1 });
      uploader.createAppointment.mockRejectedValue(new Error('no such file'));

      await queue.enqueue(REC);
      await queue.processOnce();

      expect(queue.pending()[0]).toMatchObject({ failed: true, lastErrorKind: 'other' });
    });
  });

  describe('reachability check before each upload step', () => {
    function withCheck(check: () => Promise<void>) {
      const uploader = { ...makeUploader(), checkReachable: jest.fn(check) };
      return { ...makeQueue({ uploader }), uploader };
    }

    it('never uploads when nothing answers, and that never counts as a try', async () => {
      const { queue, uploader } = withCheck(async () => {
        throw new ApiClientError('request to / failed: aborted');
      });

      await queue.enqueue(REC);
      await queue.enqueue(REC);
      await queue.processOnce();
      await queue.processOnce();

      expect(uploader.createAppointment).not.toHaveBeenCalled();
      expect(uploader.checkReachable).toHaveBeenCalledTimes(2); // the pass stops at the first
      const [entry] = queue.pending();
      expect(entry).toMatchObject({ lastErrorKind: 'unreachable', attempts: 0, lastAttemptAt: 'T' });
      expect(entry.failed).toBeFalsy();
    });

    it('checks before the audio upload and again before the note step', async () => {
      const order: string[] = [];
      const { queue, uploader } = withCheck(async () => {
        order.push('check');
      });
      uploader.createAppointment.mockImplementation(async () => {
        order.push('create');
        return appointment({ id: 'p', notePending: true });
      });
      uploader.completeAppointment.mockImplementation(async () => {
        order.push('complete');
        return appointment({ id: 'p' });
      });

      await queue.enqueue(REC);
      await queue.processOnce();

      expect(order).toEqual(['check', 'create', 'check', 'complete']);
      expect(queue.pending()).toHaveLength(0);
    });

    it('never runs the note step when nothing answers', async () => {
      const { queue, uploader } = withCheck(async () => undefined);
      uploader.createAppointment.mockResolvedValue(appointment({ id: 'p', notePending: true }));
      uploader.checkReachable
        .mockResolvedValueOnce(undefined)
        .mockRejectedValueOnce(new ApiClientError('request to / failed: aborted'));

      await queue.enqueue(REC);
      await queue.processOnce();

      expect(uploader.completeAppointment).not.toHaveBeenCalled();
      expect(queue.pending()[0]).toMatchObject({ stage: 'note', lastErrorKind: 'unreachable', attempts: 0 });
    });
  });

  describe('a recording with no speech (422)', () => {
    const noSpeech = () => new ApiClientError('backend returned 422: {"error": "no speech detected"}', 422);

    it('is marked failed on the first reply, not retried in the background', async () => {
      const { queue, uploader } = makeQueue({ maxAttempts: 5 });
      uploader.createAppointment.mockRejectedValue(noSpeech());

      await queue.enqueue(REC);
      await queue.processOnce();
      await queue.processOnce();
      await queue.processOnce();

      expect(uploader.createAppointment).toHaveBeenCalledTimes(1);
      expect(queue.pending()[0]).toMatchObject({
        failed: true,
        attempts: 1,
        lastErrorKind: 'backend',
        lastStatus: 422,
      });
    });

    it('is kept, and a manual retry still uploads it', async () => {
      const { queue, uploader, files } = makeQueue();
      uploader.createAppointment.mockRejectedValueOnce(noSpeech());
      const entry = await queue.enqueue(REC);
      await queue.processOnce();
      expect(files.deleted).toEqual([]);

      uploader.createAppointment.mockResolvedValueOnce(appointment({ id: 'spoken' }));
      const result = await queue.retry(entry.id);

      expect(result).toMatchObject({ id: 'spoken' });
    });
  });

  describe('retry (manual, from the Uploads screen)', () => {
    it('clears a failed entry and uploads it now', async () => {
      const { queue, uploader } = makeQueue({ maxAttempts: 1 });
      uploader.createAppointment.mockRejectedValueOnce(new ApiClientError('502', 502));
      const entry = await queue.enqueue(REC);
      await queue.processOnce();
      expect(queue.pending()[0].failed).toBe(true);

      uploader.createAppointment.mockResolvedValueOnce(appointment({ id: 'back' }));
      const result = await queue.retry(entry.id);

      expect(result).toMatchObject({ id: 'back' });
      expect(queue.pending()).toHaveLength(0);
    });

    it('resets the attempt count, so a failed retry starts counting again', async () => {
      const { queue, uploader } = makeQueue({ maxAttempts: 3 });
      uploader.createAppointment.mockRejectedValue(new ApiClientError('502', 502));
      const entry = await queue.enqueue(REC);
      for (let i = 0; i < 3; i += 1) await queue.processOnce();

      const result = await queue.retry(entry.id);

      expect(result).toBeNull();
      expect(queue.pending()[0]).toMatchObject({ attempts: 1 });
      expect(queue.pending()[0].failed).toBeFalsy();
    });

    it('while another upload is running, uploads the entry as soon as that pass ends', async () => {
      const { queue, uploader } = makeQueue({ maxAttempts: 1 });
      uploader.createAppointment.mockRejectedValueOnce(new ApiClientError('502', 502));
      const failedEntry = await queue.enqueue(REC);
      await queue.processOnce();

      let release!: (a: Appointment) => void;
      uploader.createAppointment.mockImplementationOnce(
        () => new Promise<Appointment>((resolve) => { release = resolve; }),
      );
      await queue.enqueue(REC);
      const running = queue.processOnce(); // busy with the second recording

      const result = await queue.retry(failedEntry.id);
      expect(result).toBeNull();

      uploader.createAppointment.mockResolvedValueOnce(appointment({ id: 'retried' }));
      release(appointment({ id: 'second' }));
      await running;

      expect(queue.pending()).toHaveLength(0);
      expect(uploader.createAppointment).toHaveBeenCalledTimes(3);
    });
  });

  it('a recording stopped during another upload is uploaded right after it, not on the next tick', async () => {
    const { queue, uploader, onAppointmentReady } = makeQueue();
    let release!: (a: Appointment) => void;
    uploader.createAppointment.mockImplementationOnce(
      () => new Promise<Appointment>((resolve) => { release = resolve; }),
    );
    // Stop on the first recording: the immediate attempt holds the queue.
    const first = await queue.enqueue(REC);
    const running = queue.tryProcess(first.id);

    const second = await queue.enqueue(REC);
    expect(await queue.tryProcess(second.id)).toBeNull(); // busy: stays queued

    uploader.createAppointment.mockResolvedValueOnce(appointment({ id: 'second' }));
    release(appointment({ id: 'first' }));
    // Stop's own attempt returns as soon as its recording is done (the record
    // button mustn't wait on others); the follow-up pass runs in the background.
    expect(await running).toMatchObject({ id: 'first' });
    await queue.idle();

    expect(queue.pending()).toHaveLength(0);
    expect(onAppointmentReady).toHaveBeenCalledWith(expect.objectContaining({ id: 'second' }));
  });

  it('reports which entry is uploading through onChange', async () => {
    const { queue, onChange } = makeQueue();
    const entry = await queue.enqueue(REC);
    onChange.mockClear();

    await queue.processOnce();

    const activeIds = onChange.mock.calls.map((call) => call[1]);
    expect(activeIds).toContain(entry.id);
    expect(activeIds[activeIds.length - 1]).toBeNull();
  });

  describe('discarding the recording that is uploading', () => {
    /** createAppointment hangs until its signal aborts, then fails like fetch does. */
    function hangUntilAborted(uploader: ReturnType<typeof makeUploader>) {
      const signals: AbortSignal[] = [];
      uploader.createAppointment.mockImplementationOnce(
        (_bytes: unknown, _mime: string, options?: { signal?: AbortSignal }) =>
          new Promise<Appointment>((_resolve, reject) => {
            const signal = options?.signal as AbortSignal;
            signals.push(signal);
            signal?.addEventListener('abort', () =>
              reject(new ApiClientError('request to /api/appointments failed: Aborted')),
            );
          }),
      );
      return signals;
    }

    it('cancels the upload, then deletes the recording', async () => {
      const { queue, uploader, files, store } = makeQueue();
      const signals = hangUntilAborted(uploader);
      const entry = await queue.enqueue(REC);
      const running = queue.processOnce();
      await waitForCall(uploader.createAppointment);

      await queue.remove(entry.id);

      expect(signals[0]?.aborted).toBe(true);
      expect(files.deleted).toEqual([entry.fileName]);
      expect(queue.pending()).toHaveLength(0);
      expect(store.saved).toHaveLength(0);
      await running;
    });

    it('carries on with the next recording, without counting a failure', async () => {
      const { queue, uploader, onAppointmentReady } = makeQueue();
      hangUntilAborted(uploader);
      uploader.createAppointment.mockResolvedValueOnce(appointment({ id: 'second' }));
      const first = await queue.enqueue(REC);
      await queue.enqueue(REC);
      const running = queue.processOnce();
      await waitForCall(uploader.createAppointment);

      await queue.remove(first.id);
      await running;

      expect(uploader.createAppointment).toHaveBeenCalledTimes(2);
      expect(onAppointmentReady).toHaveBeenCalledWith(expect.objectContaining({ id: 'second' }));
      expect(queue.pending()).toHaveLength(0);
    });

    it('never starts uploading it again while its file is being deleted', async () => {
      const { queue, uploader, files } = makeQueue();
      hangUntilAborted(uploader);
      const entry = await queue.enqueue(REC);
      const running = queue.processOnce();
      await waitForCall(uploader.createAppointment);
      let releaseDelete!: () => void;
      const realDelete = files.delete.bind(files);
      // Only the first delete (the discard's) is slow.
      files.delete = jest.fn(realDelete).mockImplementationOnce(
        (name: string) =>
          new Promise<void>((resolve) => {
            releaseDelete = () => void realDelete(name).then(resolve);
          }),
      );

      const removing = queue.remove(entry.id);
      await running; // the cancelled pass has ended...
      const again = queue.processOnce(); // ...and another starts while the file is still going
      await new Promise<void>((resolve) => setImmediate(() => resolve()));
      releaseDelete();
      await Promise.all([removing, again]);

      expect(uploader.createAppointment).toHaveBeenCalledTimes(1);
      expect(queue.pending()).toHaveLength(0);
    });

    it('when the upload lands before the cancel does, the appointment is kept', async () => {
      const { queue, uploader, onAppointmentReady } = makeQueue();
      let release!: (a: Appointment) => void;
      uploader.createAppointment.mockImplementationOnce(
        () => new Promise<Appointment>((resolve) => { release = resolve; }),
      );
      const entry = await queue.enqueue(REC);
      const running = queue.processOnce();
      await waitForCall(uploader.createAppointment);

      const removing = queue.remove(entry.id);
      release(appointment({ id: 'landed' })); // ignores the abort: it had already finished
      await removing;
      await running;

      expect(onAppointmentReady).toHaveBeenCalledWith(expect.objectContaining({ id: 'landed' }));
      expect(queue.pending()).toHaveLength(0);
    });
  });
});
