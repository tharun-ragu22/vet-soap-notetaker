import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { useState } from 'react';
import { Text } from 'react-native';

import { ApiClient } from '../services/api/ApiClient';
import { AudioService } from '../services/audio/AudioService';
import type { Recorder, RecordingResult } from '../services/audio/types';
import { AppointmentScreen } from '../components/AppointmentScreen';
import { HistoryScreen } from '../components/HistoryScreen';
import { RecorderScreen } from '../components/RecorderScreen';
import { UploadsScreen } from '../components/UploadsScreen';
import { uploadBanner } from '../services/upload/uploadBanner';
import { UploadQueue } from '../services/upload/uploadQueue';
import type { FileStore, QueueEntry, QueueStore } from '../services/upload/types';
import { FakeBackend } from './fakeBackend';

/** In-memory queue persistence + file storage, so the real UploadQueue runs in Node. */
class MemQueueStore implements QueueStore {
  saved: QueueEntry[] = [];
  async load(): Promise<QueueEntry[]> {
    return JSON.parse(JSON.stringify(this.saved));
  }
  async save(entries: QueueEntry[]): Promise<void> {
    this.saved = JSON.parse(JSON.stringify(entries));
  }
}
class MemFileStore implements FileStore {
  private seq = 0;
  files = new Map<string, Uint8Array>();
  async save(): Promise<string> {
    const name = `f${this.seq++}`;
    this.files.set(name, new Uint8Array([1, 2, 3]));
    return name;
  }
  async read(name: string): Promise<Uint8Array> {
    return this.files.get(name)!;
  }
  async delete(name: string): Promise<void> {
    this.files.delete(name);
  }
}

function makeQueue(apiClient: ApiClient, maxAttempts?: number): UploadQueue {
  return new UploadQueue({
    maxAttempts,
    store: new MemQueueStore(),
    files: new MemFileStore(),
    uploader: {
      createAppointment: (bytes, mime) => apiClient.createAppointment(bytes, mime),
      completeAppointment: (id) => apiClient.completeAppointment(id),
    },
  });
}

function enqueueVia(queue: UploadQueue) {
  return async (result: RecordingResult) => {
    const entry = await queue.enqueue({
      uri: result.uri,
      mimeType: 'audio/m4a',
      durationMillis: result.durationMillis,
    });
    return queue.tryProcess(entry.id);
  };
}

/**
 * End-to-end through the real screens, the real ApiClient, and the faithful fake
 * backend — the closest we get to a device run in Node. Drives actual user gestures
 * (tap record, edit + save, tap inject) and asserts on backend state afterwards.
 */
describe('screens end-to-end', () => {
  function client(backend: FakeBackend): ApiClient {
    return new ApiClient({ baseUrl: 'http://clinic:8000', fetch: backend.fetch });
  }

  it('records an exam: tap start/stop uploads mocked audio and persists it', async () => {
    const backend = new FakeBackend();
    const apiClient = client(backend);
    const recorder: Recorder = {
      start: jest.fn(async () => {}),
      stop: jest.fn(async (): Promise<RecordingResult> => ({ uri: 'file:///r.m4a', durationMillis: 3000 })),
    };
    const audioService = new AudioService(recorder);
    const enqueueRecording = enqueueVia(makeQueue(apiClient));
    const onRecorded = jest.fn();

    render(
      <RecorderScreen
        audioService={audioService}
        enqueueRecording={enqueueRecording}
        onRecorded={onRecorded}
      />,
    );

    fireEvent.press(screen.getByText(/start/i));
    await waitFor(() => expect(screen.getByText(/stop/i)).toBeTruthy());
    fireEvent.press(screen.getByText(/stop/i));

    await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(1));
    const appointments = await apiClient.fetchAppointments();
    expect(appointments).toHaveLength(1);
    expect(onRecorded).toHaveBeenCalledWith(appointments[0]);
  });

  it('queues the recording when note-gen is down, then drains it when the backend recovers', async () => {
    const backend = new FakeBackend({ failNoteGeneration: true });
    const apiClient = client(backend);
    const recorder: Recorder = {
      start: jest.fn(async () => {}),
      stop: jest.fn(async (): Promise<RecordingResult> => ({ uri: 'file:///r.m4a', durationMillis: 3000 })),
    };
    const audioService = new AudioService(recorder);
    const queue = makeQueue(apiClient);
    const onRecorded = jest.fn();

    render(
      <RecorderScreen
        audioService={audioService}
        enqueueRecording={enqueueVia(queue)}
        onRecorded={onRecorded}
      />,
    );

    fireEvent.press(screen.getByText(/start/i));
    await waitFor(() => expect(screen.getByText(/stop/i)).toBeTruthy());
    fireEvent.press(screen.getByText(/stop/i));

    // Not uploaded as a complete note, so it's queued rather than navigated to.
    await waitFor(() => expect(screen.getByText(/uploading in the background/i)).toBeTruthy());
    expect(onRecorded).not.toHaveBeenCalled();

    // The transcript is preserved on the backend as a pending appointment, and the
    // queue now holds a cheap note-stage entry (the audio has been discarded).
    let appointments = await apiClient.fetchAppointments();
    expect(appointments).toHaveLength(1);
    expect(appointments[0].notePending).toBe(true);
    expect(queue.pending()).toHaveLength(1);
    expect(queue.pending()[0]).toMatchObject({ stage: 'note' });

    // Note generation recovers; the queue completes it with no re-upload.
    backend.failNoteGeneration = false;
    await queue.processOnce();

    expect(queue.pending()).toHaveLength(0);
    appointments = await apiClient.fetchAppointments();
    expect(appointments[0].notePending).toBe(false);
    expect(appointments[0].exams[0].assessment).toBe('Healthy.');
  });

  it('history feed lists appointments synced from the backend', async () => {
    const backend = new FakeBackend();
    backend.seedExam({ patient_name: 'Rex', assessment: 'Otitis externa' });
    backend.seedExam({ patient_name: 'Bella' });

    render(<HistoryScreen apiClient={client(backend)} />);

    await waitFor(() => expect(screen.getByText('Rex')).toBeTruthy());
    expect(screen.getByText('Bella')).toBeTruthy();
    expect(screen.getByText('Otitis externa')).toBeTruthy();
  });

  it('appointment: editing and saving writes through to the backend', async () => {
    const backend = new FakeBackend();
    const seeded = backend.seedExam({ patient_name: 'Rex' });
    const apiClient = client(backend);
    const appointment = await apiClient.getAppointment(seeded.appointment_id);

    render(<AppointmentScreen appointment={appointment} apiClient={apiClient} pendingPollMs={0} />);

    fireEvent.changeText(screen.getByTestId('field-0-assessment'), 'Gastroenteritis');
    fireEvent.press(screen.getByText(/save changes/i));

    await waitFor(() => expect(screen.getByText(/saved/i)).toBeTruthy());
    const persisted = await apiClient.getExam(seeded.id);
    expect(persisted.assessment).toBe('Gastroenteritis');
  });

  it('a two-animal visit: one recording, a note per animal, each injected into its own chart', async () => {
    // The feature's acceptance scenario: the vet records the whole appointment,
    // stops, and sees an individual SOAP note per animal sharing one transcript,
    // each of which they can inject into AVImark.
    const backend = new FakeBackend({
      notesForAudio: () => ({
        transcript: 'vet: Bella has otitis, Max has a cut pad',
        patients: [
          { patient_name: 'Bella', subjective: 'S1', objective: 'O1', assessment: 'Otitis externa', plan: 'Otomax' },
          { patient_name: 'Max', subjective: 'S2', objective: 'O2', assessment: 'Pad laceration', plan: 'Carprofen' },
        ],
      }),
    });
    const apiClient = client(backend);
    const recorder: Recorder = {
      start: jest.fn(async () => {}),
      stop: jest.fn(async (): Promise<RecordingResult> => ({ uri: 'file:///r.m4a', durationMillis: 3000 })),
    };
    const onRecorded = jest.fn();
    const { unmount } = render(
      <RecorderScreen
        audioService={new AudioService(recorder)}
        enqueueRecording={enqueueVia(makeQueue(apiClient))}
        onRecorded={onRecorded}
      />,
    );
    fireEvent.press(screen.getByText(/start/i));
    await waitFor(() => expect(screen.getByText(/stop/i)).toBeTruthy());
    fireEvent.press(screen.getByText(/stop/i));
    await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(1));
    unmount();

    // The route opens the appointment the recorder reported.
    render(<AppointmentScreen appointment={onRecorded.mock.calls[0][0]} apiClient={apiClient} pendingPollMs={0} />);

    expect(screen.getByTestId('name-0').props.value).toBe('Bella');
    expect(screen.getByTestId('field-0-assessment').props.value).toBe('Otitis externa');
    expect(screen.getByTestId('name-1').props.value).toBe('Max');
    expect(screen.getByTestId('field-1-assessment').props.value).toBe('Pad laceration');
    expect(screen.getAllByTestId('field-transcript')).toHaveLength(1);

    fireEvent.press(screen.getByTestId('inject-0'));
    await waitFor(() => expect(screen.getByText(/sent to the desktop/i)).toBeTruthy());
    fireEvent.press(screen.getByTestId('inject-1'));
    await waitFor(() => expect(backend.injectionRequests()).toHaveLength(2));

    // What the desktop's poll pastes: each animal's own note, the same transcript.
    const res = await backend.fetch('http://clinic:8000/api/injections/pending');
    const { requests } = (await res.json()) as {
      requests: { exam: { patient_name: string; plan: string; transcript: string } }[];
    };
    expect(requests.map((r) => [r.exam.patient_name, r.exam.plan])).toEqual([
      ['Bella', 'Otomax'],
      ['Max', 'Carprofen'],
    ]);
    expect(new Set(requests.map((r) => r.exam.transcript))).toEqual(
      new Set(['vet: Bella has otitis, Max has a cut pad']),
    );
  });

  describe('recordings that did not upload', () => {
    const recorder = (): Recorder => ({
      start: jest.fn(async () => {}),
      stop: jest.fn(async (): Promise<RecordingResult> => ({ uri: 'file:///r.m4a', durationMillis: 28_000 })),
    });

    async function recordOnce(queue: UploadQueue) {
      const onRecorded = jest.fn();
      const { unmount } = render(
        <RecorderScreen
          audioService={new AudioService(recorder())}
          enqueueRecording={enqueueVia(queue)}
          onRecorded={onRecorded}
        />,
      );
      fireEvent.press(screen.getByText(/start/i));
      await waitFor(() => expect(screen.getByText(/stop/i)).toBeTruthy());
      fireEvent.press(screen.getByText(/stop/i));
      await waitFor(() => expect(screen.getByText(/uploading in the background/i)).toBeTruthy());
      unmount();
      return onRecorded;
    }

    function renderUploads(queue: UploadQueue, onOpenAppointment = jest.fn()) {
      render(
        <UploadsScreen
          entries={queue.pending()}
          activeId={null}
          onRetry={(id) => queue.retry(id)}
          onDiscard={(id) => queue.remove(id)}
          onOpenAppointment={onOpenAppointment}
        />,
      );
      return onOpenAppointment;
    }

    it('keeps retrying while the backend is unreachable, then a manual Retry lands on the notes', async () => {
      const backend = new FakeBackend();
      backend.unreachable = true;
      const apiClient = client(backend);
      const queue = makeQueue(apiClient, 5);

      const onRecorded = await recordOnce(queue);
      for (let i = 0; i < 8; i += 1) await queue.processOnce();

      expect(onRecorded).not.toHaveBeenCalled();
      const [entry] = queue.pending();
      expect(entry.failed).toBeFalsy();

      backend.unreachable = false;
      const onOpenAppointment = renderUploads(queue);
      expect(screen.getByTestId(`upload-row-${entry.id}`)).toHaveTextContent("Can't reach the backend", {
        exact: false,
      });
      fireEvent.press(screen.getByTestId(`retry-${entry.id}`));

      await waitFor(() => expect(onOpenAppointment).toHaveBeenCalled());
      const [appointment] = await apiClient.fetchAppointments();
      expect(onOpenAppointment).toHaveBeenCalledWith(appointment.id);
      expect(queue.pending()).toHaveLength(0);
    });

    /** The app's own wiring: a short reachability check and cancellable uploads. */
    function appQueue(backend: FakeBackend, onChange?: (entries: QueueEntry[]) => void) {
      const apiClient = new ApiClient({
        baseUrl: 'http://clinic:8000',
        fetch: backend.fetch,
        reachabilityTimeoutMs: 50,
      });
      const files = new MemFileStore();
      const queue = new UploadQueue({
        store: new MemQueueStore(),
        files,
        uploader: {
          checkReachable: () => apiClient.checkReachable(),
          createAppointment: (bytes, mime, options) => apiClient.createAppointment(bytes, mime, options),
          completeAppointment: (id, options) => apiClient.completeAppointment(id, options),
        },
        onChange,
      });
      return { apiClient, files, queue };
    }

    it('says it cannot reach a backend that never answers, within seconds, and keeps the buttons', async () => {
      const backend = new FakeBackend();
      backend.hangs = true; // e.g. a firewall silently dropping the packets
      const { apiClient, files, queue } = appQueue(backend);

      const onRecorded = await recordOnce(queue); // Stop comes back instead of hanging
      await queue.processOnce();
      await queue.processOnce();

      expect(onRecorded).not.toHaveBeenCalled();
      const [entry] = queue.pending();
      expect(entry).toMatchObject({ lastErrorKind: 'unreachable', attempts: 0 });
      expect(entry.failed).toBeFalsy();

      const onOpenAppointment = jest.fn();
      render(
        <UploadsScreen
          entries={queue.pending()}
          activeId={queue.uploading()}
          onRetry={(id) => queue.retry(id)}
          onDiscard={(id) => queue.remove(id)}
          onOpenAppointment={onOpenAppointment}
        />,
      );
      const row = screen.getByTestId(`upload-row-${entry.id}`);
      expect(row).toHaveTextContent("Can't reach the backend — retrying automatically", { exact: false });
      expect(row).toHaveTextContent('Last tried just now.', { exact: false });
      expect(screen.getByTestId(`retry-${entry.id}`)).toBeEnabled();
      expect(screen.getByTestId(`discard-${entry.id}`)).toBeEnabled();

      backend.hangs = false;
      fireEvent.press(screen.getByTestId(`retry-${entry.id}`));

      await waitFor(() => expect(onOpenAppointment).toHaveBeenCalled());
      const [appointment] = await apiClient.fetchAppointments();
      expect(onOpenAppointment).toHaveBeenCalledWith(appointment.id);
      expect(files.files.size).toBe(0);
    });

    it('discards a recording while it is uploading, cancelling the upload', async () => {
      const backend = new FakeBackend();
      backend.hangUploads = true; // up, but this upload is taking a long time
      const { apiClient, files, queue } = appQueue(backend);
      const entry = await queue.enqueue({ uri: 'file:///r.m4a', mimeType: 'audio/m4a', durationMillis: 28_000 });
      const running = queue.processOnce();
      await waitFor(() => expect(queue.uploading()).toBe(entry.id));

      render(
        <UploadsScreen
          entries={queue.pending()}
          activeId={queue.uploading()}
          onRetry={(id) => queue.retry(id)}
          onDiscard={(id) => queue.remove(id)}
          onOpenAppointment={jest.fn()}
        />,
      );
      expect(screen.getByTestId(`upload-row-${entry.id}`)).toHaveTextContent('Uploading…', { exact: false });
      fireEvent.press(screen.getByTestId(`discard-${entry.id}`));
      fireEvent.press(screen.getByTestId(`discard-${entry.id}`));

      await waitFor(() => expect(queue.pending()).toHaveLength(0));
      await running;
      expect(files.files.size).toBe(0);
      expect(await apiClient.fetchAppointments()).toHaveLength(0);
    });

    it('drops the "uploading in the background" notice when the recording is discarded mid-upload', async () => {
      const backend = new FakeBackend();
      backend.hangUploads = true;
      let showEntries: (entries: QueueEntry[]) => void = () => {};
      const { files, queue } = appQueue(backend, (entries) => showEntries(entries));

      // The home route: the recorder plus the queue banner, both fed by the queue.
      function Home() {
        const [entries, setEntries] = useState<QueueEntry[]>([]);
        showEntries = setEntries;
        const banner = uploadBanner(entries);
        return (
          <>
            <RecorderScreen
              audioService={new AudioService(recorder())}
              enqueueRecording={enqueueVia(queue)}
              hasPendingUploads={entries.length > 0}
            />
            {banner ? <Text>{banner.text}</Text> : null}
          </>
        );
      }
      render(<Home />);

      fireEvent.press(screen.getByText(/start/i));
      await waitFor(() => expect(screen.getByText(/stop/i)).toBeTruthy());
      fireEvent.press(screen.getByText(/stop/i));
      await waitFor(() => expect(queue.uploading()).not.toBeNull());
      expect(screen.getByText('1 recording waiting to upload…')).toBeTruthy();

      await act(() => queue.remove(queue.uploading()!)); // the Uploads screen's Discard

      await waitFor(() => expect(screen.getByText(/start/i)).toBeTruthy()); // the Stop has returned
      expect(screen.queryByText(/uploading in the background/i)).toBeNull();
      expect(screen.queryByText(/waiting to upload/i)).toBeNull();
      expect(files.files.size).toBe(0);
    });

    it('stops retrying after 5 backend errors, shows why, and a Retry after recovery uploads it', async () => {
      const backend = new FakeBackend();
      backend.failTranscription = true;
      const apiClient = client(backend);
      const queue = makeQueue(apiClient, 5);

      await recordOnce(queue); // the immediate attempt is the first try
      for (let i = 0; i < 6; i += 1) await queue.processOnce();

      const [entry] = queue.pending();
      expect(entry).toMatchObject({ failed: true, attempts: 5 });
      expect(await apiClient.fetchAppointments()).toHaveLength(0);

      backend.failTranscription = false;
      const onOpenAppointment = renderUploads(queue);
      const row = screen.getByTestId(`upload-row-${entry.id}`);
      expect(row).toHaveTextContent('Upload failed after 5 tries', { exact: false });
      expect(row).toHaveTextContent('Backend error (502)', { exact: false });

      fireEvent.press(screen.getByTestId(`retry-${entry.id}`));

      await waitFor(() => expect(onOpenAppointment).toHaveBeenCalled());
      expect(await apiClient.fetchAppointments()).toHaveLength(1);
      expect(queue.pending()).toHaveLength(0);
    });

    it('a recording with no speech is failed at once, says so, and is never retried in the background', async () => {
      const backend = new FakeBackend();
      backend.noSpeech = true;
      const apiClient = client(backend);
      const uploads = jest.spyOn(apiClient, 'createAppointment');
      const queue = makeQueue(apiClient, 5);

      await recordOnce(queue);
      await queue.processOnce();
      await queue.processOnce();

      expect(uploads).toHaveBeenCalledTimes(1);
      const [entry] = queue.pending();
      expect(entry).toMatchObject({ failed: true, attempts: 1 });
      expect(await apiClient.fetchAppointments()).toHaveLength(0);

      backend.noSpeech = false;
      const onOpenAppointment = renderUploads(queue);
      expect(screen.getByTestId(`upload-row-${entry.id}`)).toHaveTextContent('No speech heard in this recording', {
        exact: false,
      });

      fireEvent.press(screen.getByTestId(`retry-${entry.id}`));

      await waitFor(() => expect(onOpenAppointment).toHaveBeenCalled());
      expect(await apiClient.fetchAppointments()).toHaveLength(1);
    });
  });
});
