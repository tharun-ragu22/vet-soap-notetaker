import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import type { Appointment } from '../services/api/types';
import type { AudioEntry, NoteEntry, QueueEntry } from '../services/upload/types';
import { UploadsScreen, type UploadsScreenProps } from './UploadsScreen';

function audio(overrides: Partial<AudioEntry> = {}): AudioEntry {
  return {
    id: 'a1',
    stage: 'audio',
    fileName: 'f.m4a',
    mimeType: 'audio/m4a',
    createdAt: '2026-10-16T15:50:00Z',
    durationMillis: 28_000,
    attempts: 0,
    ...overrides,
  };
}

function note(overrides: Partial<NoteEntry> = {}): NoteEntry {
  return {
    id: 'n1',
    stage: 'note',
    appointmentId: 'appt-9',
    createdAt: '2026-10-16T16:00:00Z',
    attempts: 0,
    ...overrides,
  };
}

const failed = audio({ attempts: 5, failed: true, lastErrorKind: 'backend', lastStatus: 502 });

function renderScreen(entries: QueueEntry[], overrides: Partial<UploadsScreenProps> = {}) {
  const props: UploadsScreenProps = {
    entries,
    activeId: null,
    onRetry: jest.fn(async () => null),
    onDiscard: jest.fn(async () => {}),
    onOpenAppointment: jest.fn(),
    ...overrides,
  };
  const utils = render(<UploadsScreen {...props} />);
  return { ...utils, props };
}

describe('UploadsScreen', () => {
  it('shows a row per recording with its time, length, status and reason', () => {
    renderScreen([failed, audio({ id: 'a2' })]);

    const row = screen.getByTestId('upload-row-a1');
    expect(row).toHaveTextContent(new Date('2026-10-16T15:50:00Z').toLocaleString(), { exact: false });
    expect(row).toHaveTextContent('0:28', { exact: false });
    expect(row).toHaveTextContent('Upload failed after 5 tries', { exact: false });
    expect(row).toHaveTextContent('Backend error (502)', { exact: false });
    expect(screen.getByTestId('upload-row-a2')).toHaveTextContent('Waiting to upload', { exact: false });
  });

  it('shows the entry being uploaded: Retry is off, Discard still works', async () => {
    const { props } = renderScreen([audio()], { activeId: 'a1' });

    expect(screen.getByTestId('upload-row-a1')).toHaveTextContent('Uploading…', { exact: false });
    expect(screen.getByTestId('retry-a1')).toBeDisabled();
    expect(screen.getByTestId('discard-a1')).toBeEnabled();

    fireEvent.press(screen.getByTestId('discard-a1'));
    fireEvent.press(screen.getByTestId('discard-a1'));
    await waitFor(() => expect(props.onDiscard).toHaveBeenCalledWith('a1'));
  });

  it('says when it last tried, on its clock', () => {
    const unreachable = audio({ lastErrorKind: 'unreachable', lastAttemptAt: '2026-10-17T12:00:00Z' });
    renderScreen([unreachable], { now: () => Date.parse('2026-10-17T12:03:10Z') });

    expect(screen.getByTestId('upload-row-a1')).toHaveTextContent('Last tried 3 min ago.', { exact: false });
  });

  it('opens the appointment when a Retry lands', async () => {
    const landed = { id: 'appt-7' } as Appointment;
    const { props } = renderScreen([failed], { onRetry: jest.fn(async () => landed) });

    fireEvent.press(screen.getByTestId('retry-a1'));

    await waitFor(() => expect(props.onOpenAppointment).toHaveBeenCalledWith('appt-7'));
    expect(props.onRetry).toHaveBeenCalledWith('a1');
  });

  it('keeps the row when a Retry does not land, and allows another try', async () => {
    let resolve!: (a: Appointment | null) => void;
    const onRetry = jest.fn(() => new Promise<Appointment | null>((r) => { resolve = r; }));
    const { props } = renderScreen([failed], { onRetry });

    fireEvent.press(screen.getByTestId('retry-a1'));
    await waitFor(() => expect(screen.getByTestId('retry-a1')).toBeDisabled());
    await act(async () => resolve(null));

    expect(props.onOpenAppointment).not.toHaveBeenCalled();
    expect(screen.getByTestId('upload-row-a1')).toBeTruthy();
    expect(screen.getByTestId('retry-a1')).toBeEnabled();
  });

  it('asks for a second tap before discarding a recording', async () => {
    const { props } = renderScreen([failed]);

    fireEvent.press(screen.getByTestId('discard-a1'));
    expect(screen.getByTestId('discard-a1')).toHaveTextContent('Tap again to discard');
    expect(props.onDiscard).not.toHaveBeenCalled();

    fireEvent.press(screen.getByTestId('discard-a1'));
    await waitFor(() => expect(props.onDiscard).toHaveBeenCalledWith('a1'));
  });

  it('offers Remove for an uploaded recording and says it stays in Notes', () => {
    renderScreen([note()]);

    expect(screen.getByTestId('discard-n1')).toHaveTextContent('Remove');
    expect(screen.getByTestId('upload-row-n1')).toHaveTextContent('the appointment stays in Notes.', { exact: false });
    expect(screen.getByTestId('upload-row-n1')).toHaveTextContent('Uploaded — notes still generating', {
      exact: false,
    });
  });

  it('says everything is uploaded when the queue is empty', () => {
    renderScreen([]);

    expect(screen.getByText('All recordings are uploaded.')).toBeTruthy();
  });
});

describe('playing a recording from the Outbox', () => {
  it('opens the player for a recording still on the phone', () => {
    const onPlay = jest.fn();
    renderScreen([failed, audio({ id: 'a2' })], { onPlay });

    expect(screen.getByTestId('play-a1')).toHaveTextContent('▶ Play');
    fireEvent.press(screen.getByTestId('play-a2'));

    expect(onPlay).toHaveBeenCalledWith('a2');
  });

  it('can be played while it is uploading', () => {
    const onPlay = jest.fn();
    renderScreen([audio()], { onPlay, activeId: 'a1' });

    fireEvent.press(screen.getByTestId('play-a1'));

    expect(onPlay).toHaveBeenCalledWith('a1');
  });

  it('has no Play for an uploaded recording, whose audio is no longer on the phone', () => {
    renderScreen([note()], { onPlay: jest.fn() });

    expect(screen.queryByTestId('play-n1')).toBeNull();
  });

  it('has no Play without a player', () => {
    renderScreen([audio()]);

    expect(screen.queryByTestId('play-a1')).toBeNull();
  });

  it('turns Play off while a new recording is being made', () => {
    const onPlay = jest.fn();
    renderScreen([audio()], { onPlay, recording: true });

    expect(screen.getByTestId('play-a1')).toBeDisabled();
    fireEvent.press(screen.getByTestId('play-a1'));
    expect(onPlay).not.toHaveBeenCalled();
  });
});
