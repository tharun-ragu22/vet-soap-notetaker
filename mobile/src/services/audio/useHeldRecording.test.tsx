import { act, renderHook, waitFor } from '@testing-library/react-native';

import type { PlaybackFiles } from './types';
import { useHeldRecording } from './useHeldRecording';

/** Copies "originals" into a separate set of "copies", like the real cache copy. */
function fakeFiles() {
  const originals = new Set(['rec.m4a']);
  const copies = new Set<string>();
  const files: PlaybackFiles & { originals: Set<string>; copies: Set<string> } = {
    originals,
    copies,
    hold: jest.fn(async (fileName: string) => {
      if (!originals.has(fileName)) throw new Error('gone');
      const uri = `file:///cache/playback/${fileName}`;
      copies.add(uri);
      return uri;
    }),
    release: jest.fn(async (uri: string) => {
      copies.delete(uri);
    }),
  };
  return files;
}

describe('useHeldRecording', () => {
  it('holds a copy of the recording and returns its uri', async () => {
    const files = fakeFiles();
    const { result } = renderHook(() => useHeldRecording('rec.m4a', files));

    await waitFor(() => expect(result.current.uri).toBe('file:///cache/playback/rec.m4a'));
    expect(result.current.error).toBe(false);
    expect(files.hold).toHaveBeenCalledTimes(1);
  });

  it('keeps the copy when the queue deletes the original (the upload finished)', async () => {
    const files = fakeFiles();
    const { result, rerender } = renderHook(() => useHeldRecording('rec.m4a', files));
    await waitFor(() => expect(result.current.uri).not.toBeNull());

    files.originals.delete('rec.m4a');
    rerender({});

    expect(result.current.uri).toBe('file:///cache/playback/rec.m4a');
    expect(files.copies.has('file:///cache/playback/rec.m4a')).toBe(true);
    expect(files.release).not.toHaveBeenCalled();
    expect(files.hold).toHaveBeenCalledTimes(1);
  });

  it('releases the copy when the player closes', async () => {
    const files = fakeFiles();
    const { result, unmount } = renderHook(() => useHeldRecording('rec.m4a', files));
    await waitFor(() => expect(result.current.uri).not.toBeNull());

    unmount();

    await waitFor(() => expect(files.release).toHaveBeenCalledWith('file:///cache/playback/rec.m4a'));
    expect(files.copies.size).toBe(0);
  });

  it('releases a copy that only finishes after the player has closed', async () => {
    let finish!: (uri: string) => void;
    const files = fakeFiles();
    files.hold = jest.fn(() => new Promise<string>((resolve) => { finish = resolve; }));
    const { unmount } = renderHook(() => useHeldRecording('rec.m4a', files));

    unmount();
    await act(async () => finish('file:///cache/playback/late.m4a'));

    expect(files.release).toHaveBeenCalledWith('file:///cache/playback/late.m4a');
  });

  it('reports an error when the recording is no longer on the phone, and releases nothing', async () => {
    const files = fakeFiles();
    files.originals.clear();
    const { result, unmount } = renderHook(() => useHeldRecording('rec.m4a', files));

    await waitFor(() => expect(result.current.error).toBe(true));
    expect(result.current.uri).toBeNull();
    unmount();
    expect(files.release).not.toHaveBeenCalled();
  });
});

describe('useHeldRecording when the recording changes', () => {
  it("never hands back the previous recording's copy or error", async () => {
    const files = fakeFiles();
    const { result, rerender } = renderHook(({ name }: { name: string | null }) => useHeldRecording(name, files), {
      initialProps: { name: 'rec.m4a' as string | null },
    });
    await waitFor(() => expect(result.current.uri).not.toBeNull());

    rerender({ name: 'other.m4a' });
    // other.m4a isn't on the phone: an error, and never rec.m4a's copy meanwhile.
    expect(result.current.uri).toBeNull();
    await waitFor(() => expect(result.current.error).toBe(true));

    rerender({ name: null });
    expect(result.current).toEqual({ uri: null, error: false });
  });
});
