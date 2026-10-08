import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { ApiClient } from '../services/api/ApiClient';
import { AudioService } from '../services/audio/AudioService';
import type { Recorder, RecordingResult } from '../services/audio/types';
import { ExamEditor } from '../components/ExamEditor';
import { HistoryScreen } from '../components/HistoryScreen';
import { RecorderScreen } from '../components/RecorderScreen';
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

function makeQueue(apiClient: ApiClient): UploadQueue {
  return new UploadQueue({
    store: new MemQueueStore(),
    files: new MemFileStore(),
    uploader: {
      generateNote: (bytes, mime) => apiClient.generateNote(bytes, mime),
      completeNote: (id) => apiClient.completeNote(id),
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
    const history = await apiClient.fetchHistory();
    expect(history).toHaveLength(1);
    expect(onRecorded).toHaveBeenCalledWith(expect.objectContaining({ id: history[0].id }));
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

    // The transcript is preserved on the backend as a pending exam, and the queue
    // now holds a cheap note-stage entry (the audio has been discarded).
    let history = await apiClient.fetchHistory();
    expect(history).toHaveLength(1);
    expect(history[0].notePending).toBe(true);
    expect(queue.pending()).toHaveLength(1);
    expect(queue.pending()[0]).toMatchObject({ stage: 'note' });

    // Note generation recovers; the queue completes it with no re-upload.
    backend.failNoteGeneration = false;
    await queue.processOnce();

    expect(queue.pending()).toHaveLength(0);
    history = await apiClient.fetchHistory();
    expect(history[0].notePending).toBe(false);
    expect(history[0].assessment).toBe('Healthy.');
  });

  it('history feed lists exams synced from the backend', async () => {
    const backend = new FakeBackend();
    backend.seedExam({ patient_name: 'Rex', assessment: 'Otitis externa' });
    backend.seedExam({ patient_name: 'Bella' });

    render(<HistoryScreen apiClient={client(backend)} />);

    await waitFor(() => expect(screen.getByText('Rex')).toBeTruthy());
    expect(screen.getByText('Bella')).toBeTruthy();
    expect(screen.getByText('Otitis externa')).toBeTruthy();
  });

  it('editor: editing and saving writes through to the backend', async () => {
    const backend = new FakeBackend();
    const seeded = backend.seedExam({ patient_name: 'Rex' });
    const apiClient = client(backend);
    const exam = await apiClient.getExam(seeded.id);

    render(<ExamEditor exam={exam} apiClient={apiClient} />);

    fireEvent.changeText(screen.getByTestId('field-assessment'), 'Gastroenteritis');
    fireEvent.press(screen.getByText(/save changes/i));

    await waitFor(() => expect(screen.getByText(/saved/i)).toBeTruthy());
    const persisted = await apiClient.getExam(seeded.id);
    expect(persisted.assessment).toBe('Gastroenteritis');
  });

  it('editor: tapping Inject enqueues a remote injection for this exam', async () => {
    const backend = new FakeBackend();
    const seeded = backend.seedExam({ patient_name: 'Rex' });
    const apiClient = client(backend);
    const exam = await apiClient.getExam(seeded.id);

    render(<ExamEditor exam={exam} apiClient={apiClient} />);

    fireEvent.press(screen.getByText(/inject into avimark/i));

    await waitFor(() => expect(screen.getByText(/sent to the desktop/i)).toBeTruthy());
    const pending = backend.injectionRequests();
    expect(pending).toHaveLength(1);
    expect(pending[0]).toMatchObject({ exam_id: seeded.id, status: 'pending' });
  });
});
