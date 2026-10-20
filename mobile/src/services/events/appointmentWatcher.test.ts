import { ApiClientError } from '../api/ApiClient';
import type { Appointment, AppointmentStatus } from '../api/types';
import { AppointmentWatcher, type ReadyNote, type WaitingStore } from './appointmentWatcher';
import type { SseEvent } from './sse';

class FakeWaitingStore implements WaitingStore {
  ids: string[] = [];
  async load() {
    return [...this.ids];
  }
  async save(ids: string[]) {
    this.ids = [...ids];
  }
}

/** Each openStream call; the test drives it: emit events, end it, fail it. */
class FakeStreams {
  opened: { signal: AbortSignal; onEvent: (e: SseEvent) => void; end: () => void; fail: (e: Error) => void }[] = [];
  open = (signal: AbortSignal, onEvent: (e: SseEvent) => void) =>
    new Promise<void>((resolve, reject) => {
      signal.addEventListener('abort', () => resolve());
      this.opened.push({ signal, onEvent, end: resolve, fail: reject });
    });
  get current() {
    return this.opened[this.opened.length - 1];
  }
  get openCount() {
    return this.opened.filter((s) => !s.signal.aborted).length;
  }
}

function appt(id: string, status: AppointmentStatus, names: (string | undefined)[] = []): Appointment {
  return {
    id,
    createdAt: 'T',
    transcript: '',
    notePending: status === 'note_pending',
    status,
    exams: names.map((patientName, i) => ({
      id: `${id}-e${i}`,
      appointmentId: id,
      createdAt: 'T',
      patientName,
      subjective: '',
      objective: '',
      assessment: '',
      plan: '',
      notePending: false,
    })),
  };
}

const flush = async () => {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
};

function setup(server: Record<string, Appointment | Error> = {}, store = new FakeWaitingStore()) {
  const streams = new FakeStreams();
  const ready: ReadyNote[] = [];
  const timers: { fn: () => void; ms: number; cancelled: boolean }[] = [];
  const getAppointment = jest.fn(async (id: string) => {
    const found = server[id];
    if (!found) throw new ApiClientError('backend returned 404', 404);
    if (found instanceof Error) throw found;
    return found;
  });
  const watcher = new AppointmentWatcher({
    store,
    getAppointment,
    openStream: streams.open,
    onReady: (note) => ready.push(note),
    schedule: (fn, ms) => {
      const timer = { fn, ms, cancelled: false };
      timers.push(timer);
      return () => {
        timer.cancelled = true;
      };
    },
  });
  const fireTimers = async () => {
    for (const t of timers.splice(0)) if (!t.cancelled) t.fn();
    await flush();
  };
  return { watcher, store, streams, ready, timers, getAppointment, fireTimers, server };
}

const event = (data: object): SseEvent => ({ event: 'appointment', data: JSON.stringify(data) });

describe('AppointmentWatcher', () => {
  it('opens the stream only while the app is active and something is waiting', async () => {
    const { watcher, streams } = setup({ a1: appt('a1', 'processing') });
    await watcher.load();
    watcher.setActive(true);
    await flush();
    expect(streams.openCount).toBe(0); // nothing waiting

    await watcher.wait('a1');
    expect(streams.openCount).toBe(1);

    watcher.setActive(false);
    expect(streams.current.signal.aborted).toBe(true);
    expect(streams.openCount).toBe(0);
  });

  it('persists what it waits on, so a restart keeps waiting', async () => {
    const first = setup();
    first.watcher.setActive(true);
    await first.watcher.wait('a1');
    expect(first.store.ids).toEqual(['a1']);

    const { watcher, streams } = setup({ a1: appt('a1', 'processing') }, first.store);
    await watcher.load();
    watcher.setActive(true);
    await flush();
    expect(streams.openCount).toBe(1);
  });

  it('announces a finished appointment from the stream, with its animals', async () => {
    const { watcher, streams, ready, store } = setup({ a1: appt('a1', 'processing') });
    watcher.setActive(true);
    await watcher.wait('a1');

    streams.current.onEvent(event({ id: 'a1', status: 'complete', patient_names: ['Bella', 'Max'] }));
    await flush();

    expect(ready).toEqual([{ appointmentId: 'a1', status: 'complete', patientNames: ['Bella', 'Max'] }]);
    expect(store.ids).toEqual([]);
    expect(streams.openCount).toBe(0); // nothing left to wait for
  });

  it('ignores events for appointments it is not waiting on, and malformed ones', async () => {
    const { watcher, streams, ready } = setup({ a1: appt('a1', 'processing') });
    watcher.setActive(true);
    await watcher.wait('a1');

    streams.current.onEvent(event({ id: 'other', status: 'complete', patient_names: [] }));
    streams.current.onEvent({ event: 'appointment', data: 'not json' });
    streams.current.onEvent({ event: 'ping', data: '{}' });
    await flush();

    expect(ready).toEqual([]);
    expect(streams.openCount).toBe(1);
  });

  it('catches up on connect: an appointment that finished while not listening is announced', async () => {
    const { watcher, streams, ready, getAppointment } = setup({
      a1: appt('a1', 'complete', ['Bella', undefined]),
      a2: appt('a2', 'processing'),
    });
    watcher.setActive(true);
    await watcher.wait('a1');
    await watcher.wait('a2');
    getAppointment.mockClear();

    streams.current.onEvent({ event: 'ready', data: '{}' });
    await flush();

    expect(getAppointment.mock.calls.map(([id]) => id).sort()).toEqual(['a1', 'a2']);
    expect(ready).toEqual([{ appointmentId: 'a1', status: 'complete', patientNames: ['Bella'] }]);
  });

  it.each(['failed', 'no_speech', 'note_pending'] as const)('announces a %s outcome too', async (status) => {
    const { watcher, streams, ready } = setup({ a1: appt('a1', 'processing') });
    watcher.setActive(true);
    await watcher.wait('a1');

    streams.current.onEvent(event({ id: 'a1', status, patient_names: [] }));
    await flush();

    expect(ready).toEqual([{ appointmentId: 'a1', status, patientNames: [] }]);
  });

  it('stops waiting on an appointment that was deleted', async () => {
    const { watcher, streams, ready, store } = setup({});
    watcher.setActive(true);
    await watcher.wait('gone');

    streams.current.onEvent({ event: 'ready', data: '{}' });
    await flush();

    expect(ready).toEqual([]);
    expect(store.ids).toEqual([]);
  });

  it('keeps waiting when the catch-up read fails for any other reason', async () => {
    const { watcher, streams, store } = setup({ a1: new ApiClientError('request failed') });
    watcher.setActive(true);
    await watcher.wait('a1');

    streams.current.onEvent({ event: 'ready', data: '{}' });
    await flush();

    expect(store.ids).toEqual(['a1']);
  });

  it('reconnects after the stream drops, backing off up to 30 s and resetting once connected', async () => {
    const { watcher, streams, timers, fireTimers } = setup({ a1: appt('a1', 'processing') });
    watcher.setActive(true);
    await watcher.wait('a1');

    const delays: number[] = [];
    for (let i = 0; i < 7; i += 1) {
      streams.current.fail(new Error('dropped'));
      await flush();
      delays.push(timers[0].ms);
      await fireTimers();
    }
    expect(delays).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000]);

    streams.current.onEvent({ event: 'ready', data: '{}' });
    streams.current.end();
    await flush();
    expect(timers[0].ms).toBe(1000);
  });

  it('does not reconnect once the app is backgrounded', async () => {
    const { watcher, streams, timers, fireTimers } = setup({ a1: appt('a1', 'processing') });
    watcher.setActive(true);
    await watcher.wait('a1');
    streams.current.fail(new Error('dropped'));
    await flush();

    watcher.setActive(false);
    await fireTimers();

    expect(streams.opened).toHaveLength(1);
    expect(timers).toEqual([]);
  });

  it('stop closes the stream for good', async () => {
    const { watcher, streams } = setup({ a1: appt('a1', 'processing') });
    watcher.setActive(true);
    await watcher.wait('a1');

    watcher.stop();
    await watcher.wait('a2');

    expect(streams.opened).toHaveLength(1);
    expect(streams.current.signal.aborted).toBe(true);
  });
});
