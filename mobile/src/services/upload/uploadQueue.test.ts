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

    expect(uploader.completeAppointment).toHaveBeenCalledWith('x1');
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
      expect(uploader.completeAppointment).toHaveBeenCalledWith('p1');
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
});
