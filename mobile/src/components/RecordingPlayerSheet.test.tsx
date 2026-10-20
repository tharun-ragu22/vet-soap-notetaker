import { act, fireEvent, render, screen } from '@testing-library/react-native';

import type { Playback, PlaybackStatus } from '../services/audio/types';
import { RecordingPlayerSheet, type RecordingPlayerSheetProps } from './RecordingPlayerSheet';

function fakePlayback(status: Partial<PlaybackStatus> = {}): Playback {
  return {
    status: { loaded: true, playing: false, currentTime: 0, duration: 1200, ...status },
    play: jest.fn(),
    pause: jest.fn(),
    seekTo: jest.fn(async () => {}),
  };
}

function renderSheet(overrides: Partial<RecordingPlayerSheetProps> = {}) {
  const props: RecordingPlayerSheetProps = {
    title: 'Oct 14, 2:05 PM',
    durationMillis: 1_200_000,
    statusText: 'Waiting to upload',
    uploaded: false,
    error: false,
    playback: fakePlayback(),
    ...overrides,
  };
  const utils = render(<RecordingPlayerSheet {...props} />);
  return { ...utils, props };
}

/** Lay the scrubber out `width` points wide, as the device would. */
function layOut(width: number) {
  fireEvent(screen.getByTestId('player-scrubber'), 'layout', { nativeEvent: { layout: { width, height: 40 } } });
}

/** A touch on the bar: `x` along it, and `pageX` on screen (the same unless the finger drifts off). */
function touch(name: 'responderGrant' | 'responderMove' | 'responderRelease', x: number, pageX = x) {
  fireEvent(screen.getByTestId('player-scrubber'), name, { nativeEvent: { locationX: x, pageX } });
}

/** A seekTo that lands only when the test says so. */
function slowSeek(playback: Playback) {
  let land!: () => void;
  playback.seekTo = jest.fn(() => new Promise<void>((resolve) => { land = resolve; }));
  return () => act(async () => land());
}

describe('RecordingPlayerSheet', () => {
  it('shows the recording, where playback is, and the upload status', () => {
    renderSheet();

    expect(screen.getByText('Oct 14, 2:05 PM')).toBeTruthy();
    expect(screen.getByTestId('player-elapsed')).toHaveTextContent('0:00');
    expect(screen.getByTestId('player-total')).toHaveTextContent('20:00');
    expect(screen.getByText('Waiting to upload')).toBeTruthy();
    expect(screen.getByTestId('player-toggle')).toHaveProp('accessibilityLabel', 'Play');
  });

  it('plays, and pauses while playing', () => {
    const paused = fakePlayback();
    const { rerender, props } = renderSheet({ playback: paused });

    fireEvent.press(screen.getByTestId('player-toggle'));
    expect(paused.play).toHaveBeenCalledTimes(1);

    const playing = fakePlayback({ playing: true, currentTime: 192 });
    rerender(<RecordingPlayerSheet {...props} playback={playing} />);
    expect(screen.getByTestId('player-toggle')).toHaveProp('accessibilityLabel', 'Pause');
    expect(screen.getByTestId('player-elapsed')).toHaveTextContent('3:12');

    fireEvent.press(screen.getByTestId('player-toggle'));
    expect(playing.pause).toHaveBeenCalledTimes(1);
    expect(playing.play).not.toHaveBeenCalled();
  });

  it('starts over from the beginning after reaching the end', async () => {
    const ended = fakePlayback({ currentTime: 1200 });
    renderSheet({ playback: ended });

    await act(async () => fireEvent.press(screen.getByTestId('player-toggle')));

    expect(ended.seekTo).toHaveBeenCalledWith(0);
    expect(ended.play).toHaveBeenCalledTimes(1);
  });

  it('seeks to where the scrubber is released, following the drag until then', () => {
    const playback = fakePlayback();
    renderSheet({ playback });
    layOut(300);

    touch('responderGrant', 30);
    touch('responderMove', 150);
    expect(screen.getByTestId('player-elapsed')).toHaveTextContent('10:00');
    expect(playback.seekTo).not.toHaveBeenCalled();

    touch('responderRelease', 150);
    expect(playback.seekTo).toHaveBeenCalledWith(600);
  });

  it('a tap on the scrubber jumps there', () => {
    const playback = fakePlayback();
    renderSheet({ playback });
    layOut(300);

    touch('responderGrant', 75);
    touch('responderRelease', 75);

    expect(playback.seekTo).toHaveBeenCalledWith(300);
  });

  it('is adjustable by 15 seconds for VoiceOver, within the recording', () => {
    const playback = fakePlayback({ currentTime: 1190 });
    renderSheet({ playback });
    const scrubber = screen.getByTestId('player-scrubber');

    expect(scrubber).toHaveProp('accessibilityRole', 'adjustable');
    expect(scrubber).toHaveProp('accessibilityValue', { text: '19:50 of 20:00' });

    fireEvent(scrubber, 'accessibilityAction', { nativeEvent: { actionName: 'increment' } });
    expect(playback.seekTo).toHaveBeenLastCalledWith(1200);
    // From where the thumb now is (the end), so quick swipes add up.
    fireEvent(scrubber, 'accessibilityAction', { nativeEvent: { actionName: 'decrement' } });
    expect(playback.seekTo).toHaveBeenLastCalledWith(1185);
  });

  it('follows the finger along the screen even when it drifts off the bar', () => {
    const playback = fakePlayback();
    renderSheet({ playback });
    layOut(300);

    touch('responderGrant', 30, 50);
    // iOS measures locationX from whatever view is under the finger now.
    touch('responderMove', 5, 170);
    expect(screen.getByTestId('player-elapsed')).toHaveTextContent('10:00');

    touch('responderRelease', 5, 170);
    expect(playback.seekTo).toHaveBeenCalledWith(600);
  });

  it('keeps showing where it was let go until the seek lands, then follows the player', async () => {
    const playback = fakePlayback();
    const land = slowSeek(playback);
    const { rerender, props } = renderSheet({ playback });
    layOut(300);

    touch('responderGrant', 150);
    touch('responderRelease', 150);
    expect(screen.getByTestId('player-elapsed')).toHaveTextContent('10:00');

    await land();
    rerender(<RecordingPlayerSheet {...props} playback={{ ...playback, status: { ...playback.status, currentTime: 610 } }} />);
    expect(screen.getByTestId('player-elapsed')).toHaveTextContent('10:10');
  });

  it('after scrubbing back while paused, plays only once the seek has landed', async () => {
    const playback = fakePlayback({ currentTime: 600 });
    const land = slowSeek(playback);
    renderSheet({ playback });
    layOut(300);

    touch('responderGrant', 75);
    touch('responderRelease', 75);
    expect(playback.seekTo).toHaveBeenCalledWith(300);
    fireEvent.press(screen.getByTestId('player-toggle'));
    expect(playback.play).not.toHaveBeenCalled();

    await land();
    expect(playback.play).toHaveBeenCalledTimes(1);
    expect(playback.seekTo).toHaveBeenCalledTimes(1);
  });

  it('uses the recorded length until the player knows the real one', () => {
    renderSheet({ durationMillis: 95_000, playback: fakePlayback({ loaded: false, duration: 0 }) });

    expect(screen.getByTestId('player-total')).toHaveTextContent('1:35');
  });

  it('keeps playing after the upload finishes, and says so', () => {
    const playback = fakePlayback();
    renderSheet({ uploaded: true, playback });

    expect(screen.getByText("Uploaded — it's in Notes. You can keep listening until you close this.")).toBeTruthy();
    fireEvent.press(screen.getByTestId('player-toggle'));
    expect(playback.play).toHaveBeenCalledTimes(1);
  });

  it('says so when the recording is no longer on the phone, with no controls', () => {
    renderSheet({ error: true });

    expect(
      screen.getByText("This recording is no longer on the phone. If it uploaded, it's in Notes."),
    ).toBeTruthy();
    expect(screen.queryByTestId('player-toggle')).toBeNull();
    expect(screen.queryByTestId('player-scrubber')).toBeNull();
  });
});
