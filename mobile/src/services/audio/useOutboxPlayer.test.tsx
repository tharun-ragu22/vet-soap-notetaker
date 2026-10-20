import { act, renderHook, waitFor } from '@testing-library/react-native';

import type { AudioEntry, NoteEntry, QueueEntry } from '../upload/types';
import type { Playback, PlaybackFiles } from './types';
import { useOutboxPlayer } from './useOutboxPlayer';

function audio(id: string): AudioEntry {
  return {
    id,
    stage: 'audio',
    fileName: `${id}.m4a`,
    mimeType: 'audio/m4a',
    createdAt: '2026-10-16T15:50:00Z',
    durationMillis: 28_000,
    attempts: 0,
  };
}

function note(id: string): NoteEntry {
  return { id, stage: 'note', appointmentId: 'appt-9', createdAt: '2026-10-16T15:50:00Z', attempts: 0 };
}

function fakeFiles(onPhone: string[] = ['a1.m4a', 'a2.m4a']) {
  const files: PlaybackFiles = {
    hold: jest.fn(async (fileName: string) => {
      if (!onPhone.includes(fileName)) throw new Error('gone');
      return `file:///cache/playback/${fileName}`;
    }),
    release: jest.fn(async () => {}),
  };
  return files;
}

/** A fake playback hook: loaded as soon as it has a uri; `finished` is set by the test. */
function fakePlayback() {
  const fake = { play: jest.fn(), pause: jest.fn(), finished: false, uris: [] as (string | null)[] };
  const usePlayback = (uri: string | null): Playback => {
    fake.uris.push(uri);
    return {
      status: { loaded: uri !== null, playing: false, finished: uri !== null && fake.finished },
      play: () => fake.play(uri),
      pause: () => fake.pause(uri),
    };
  };
  return { fake, usePlayback };
}

function setup(entries: QueueEntry[] = [audio('a1'), audio('a2')], files = fakeFiles()) {
  const { fake, usePlayback } = fakePlayback();
  const hook = renderHook(({ list }: { list: QueueEntry[] }) => useOutboxPlayer(list, files, usePlayback), {
    initialProps: { list: entries },
  });
  return { ...hook, fake, files };
}

const A1 = 'file:///cache/playback/a1.m4a';
const A2 = 'file:///cache/playback/a2.m4a';

describe('useOutboxPlayer', () => {
  it('plays a copy of the recording from the start once it has loaded', async () => {
    const { result, fake, files } = setup();
    expect(result.current.playingId).toBeNull();

    act(() => result.current.play('a1'));

    expect(result.current.playingId).toBe('a1');
    await waitFor(() => expect(fake.play).toHaveBeenCalledWith(A1));
    expect(fake.play).toHaveBeenCalledTimes(1);
    expect(files.hold).toHaveBeenCalledWith('a1.m4a');
  });

  it('stops: pauses the sound and deletes the copy', async () => {
    const { result, fake, files } = setup();
    act(() => result.current.play('a1'));
    await waitFor(() => expect(fake.play).toHaveBeenCalled());

    act(() => result.current.stop());

    expect(fake.pause).toHaveBeenCalledWith(A1);
    expect(result.current.playingId).toBeNull();
    await waitFor(() => expect(files.release).toHaveBeenCalledWith(A1));
  });

  it('plays one recording at a time', async () => {
    const { result, fake, files } = setup();
    act(() => result.current.play('a1'));
    await waitFor(() => expect(fake.play).toHaveBeenCalledWith(A1));

    act(() => result.current.play('a2'));

    expect(result.current.playingId).toBe('a2');
    await waitFor(() => expect(fake.play).toHaveBeenCalledWith(A2));
    expect(fake.pause).toHaveBeenCalledWith(A1);
    expect(files.release).toHaveBeenCalledWith(A1);
  });

  it('goes back to Play when the recording reaches the end', async () => {
    const { result, fake, rerender, files } = setup();
    act(() => result.current.play('a1'));
    await waitFor(() => expect(fake.play).toHaveBeenCalled());

    fake.finished = true;
    rerender({ list: [audio('a1'), audio('a2')] });

    await waitFor(() => expect(result.current.playingId).toBeNull());
    expect(files.release).toHaveBeenCalledWith(A1);
  });

  it('stops when the recording leaves the Outbox', async () => {
    const { result, fake, rerender, files } = setup();
    act(() => result.current.play('a1'));
    await waitFor(() => expect(fake.play).toHaveBeenCalled());

    rerender({ list: [audio('a2')] });

    await waitFor(() => expect(result.current.playingId).toBeNull());
    expect(files.release).toHaveBeenCalledWith(A1);
  });

  it('keeps playing when the upload finishes, from its own copy', async () => {
    const { result, fake, rerender, files } = setup();
    act(() => result.current.play('a1'));
    await waitFor(() => expect(fake.play).toHaveBeenCalled());

    rerender({ list: [note('a1'), audio('a2')] });

    expect(result.current.playingId).toBe('a1');
    expect(fake.pause).not.toHaveBeenCalled();
    expect(files.release).not.toHaveBeenCalled();
  });

  it('says which recording could not be played, and plays nothing', async () => {
    const { result, fake } = setup([audio('a1'), audio('gone')]);

    act(() => result.current.play('gone'));

    await waitFor(() => expect(result.current.failedId).toBe('gone'));
    expect(result.current.playingId).toBeNull();
    expect(fake.play).not.toHaveBeenCalled();

    act(() => result.current.play('a1'));
    expect(result.current.failedId).toBeNull();
    await waitFor(() => expect(fake.play).toHaveBeenCalledWith(A1));
  });

  it('stops the sound when the Outbox closes', async () => {
    const { result, fake, unmount, files } = setup();
    act(() => result.current.play('a1'));
    await waitFor(() => expect(fake.play).toHaveBeenCalled());

    unmount();

    await waitFor(() => expect(files.release).toHaveBeenCalledWith(A1));
  });
});
