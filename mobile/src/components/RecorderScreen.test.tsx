import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { AudioService } from '../services/audio/AudioService';
import type { Recorder, RecordingResult } from '../services/audio/types';
import type { Exam } from '../services/api/types';
import { RecorderScreen } from './RecorderScreen';

/** A fake Recorder so the whole real AudioService state machine runs in the test. */
function makeRecorder(overrides: Partial<Recorder> = {}): jest.Mocked<Recorder> {
  return {
    start: jest.fn(async () => {}),
    stop: jest.fn(async (): Promise<RecordingResult> => ({
      uri: 'file:///rec.m4a',
      durationMillis: 4200,
    })),
    ...overrides,
  } as jest.Mocked<Recorder>;
}

const exam: Exam = {
  id: 'exam-9',
  createdAt: '2026-09-22T10:00:00Z',
  patientName: 'Rex',
  subjective: 'S',
  objective: 'O',
  assessment: 'A',
  plan: 'P',
  transcript: 'vet: hello',
};

describe('RecorderScreen', () => {
  it('shows a start control when idle', () => {
    const audioService = new AudioService(makeRecorder());
    render(<RecorderScreen audioService={audioService} enqueueRecording={jest.fn()} />);

    expect(screen.getByText(/start/i)).toBeTruthy();
  });

  it('starts the recorder and reflects the recording state when tapped', async () => {
    const recorder = makeRecorder();
    const audioService = new AudioService(recorder);
    render(<RecorderScreen audioService={audioService} enqueueRecording={jest.fn()} />);

    fireEvent.press(screen.getByText(/start/i));

    await waitFor(() => expect(screen.getByText(/stop/i)).toBeTruthy());
    expect(recorder.start).toHaveBeenCalledTimes(1);
    expect(audioService.isRecording).toBe(true);
  });

  it('on stop, queues the recording and reports the exam when it uploads immediately', async () => {
    const recorder = makeRecorder();
    const audioService = new AudioService(recorder);
    const enqueueRecording = jest.fn(async () => exam);
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

    await waitFor(() => expect(onRecorded).toHaveBeenCalledWith(exam));
    expect(enqueueRecording).toHaveBeenCalledWith({ uri: 'file:///rec.m4a', durationMillis: 4200 });
    // back to idle, ready for the next exam
    await waitFor(() => expect(screen.getByText(/start/i)).toBeTruthy());
    expect(audioService.state).toBe('idle');
  });

  it('on stop, shows a background-upload notice when the recording is only queued', async () => {
    const recorder = makeRecorder();
    const audioService = new AudioService(recorder);
    const enqueueRecording = jest.fn(async () => null); // queued, not uploaded yet
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

    await waitFor(() => expect(screen.getByText(/uploading in the background/i)).toBeTruthy());
    expect(onRecorded).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByText(/start/i)).toBeTruthy());
    expect(audioService.state).toBe('idle');
  });

  it('surfaces a start failure and stays idle', async () => {
    const recorder = makeRecorder({
      start: jest.fn(async () => {
        throw new Error('microphone permission denied');
      }),
    });
    const audioService = new AudioService(recorder);
    render(<RecorderScreen audioService={audioService} enqueueRecording={jest.fn()} />);

    fireEvent.press(screen.getByText(/start/i));

    await waitFor(() => expect(screen.getByText(/permission denied/i)).toBeTruthy());
    expect(screen.getByText(/start/i)).toBeTruthy();
    expect(audioService.state).toBe('idle');
  });

  it('surfaces a failure to even save the recording and returns to idle', async () => {
    const recorder = makeRecorder();
    const audioService = new AudioService(recorder);
    const enqueueRecording = jest.fn(async () => {
      throw new Error('disk full');
    });
    render(<RecorderScreen audioService={audioService} enqueueRecording={enqueueRecording} />);

    fireEvent.press(screen.getByText(/start/i));
    await waitFor(() => expect(screen.getByText(/stop/i)).toBeTruthy());
    fireEvent.press(screen.getByText(/stop/i));

    await waitFor(() => expect(screen.getByText(/couldn't save recording/i)).toBeTruthy());
    await waitFor(() => expect(screen.getByText(/start/i)).toBeTruthy());
    expect(audioService.state).toBe('idle');
  });
});
