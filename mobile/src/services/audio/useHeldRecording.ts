import { useEffect, useState } from 'react';

import type { PlaybackFiles } from './types';

export interface HeldRecording {
  /** The private copy, once it's ready. */
  uri: string | null;
  /** The recording couldn't be copied (e.g. it had already uploaded and been deleted). */
  error: boolean;
}

const NOTHING: HeldRecording = { uri: null, error: false };

/**
 * Holds a private copy of a queued recording for as long as it's playing, and
 * releases it when playback stops (fileName goes null or changes). Playback uses
 * the copy, so the upload queue can finish and delete the original without
 * cutting the vet off.
 */
export function useHeldRecording(fileName: string | null, files: PlaybackFiles): HeldRecording {
  // Tagged with its file, so a change of recording never shows the last one's copy.
  const [held, setHeld] = useState<HeldRecording & { fileName: string | null }>({ ...NOTHING, fileName: null });

  useEffect(() => {
    if (!fileName) return;
    let closed = false;
    let uri: string | null = null;
    files.hold(fileName).then(
      (copy) => {
        uri = copy;
        // Stopped before the copy finished: nobody will play it.
        if (closed) void files.release(copy);
        else setHeld({ uri: copy, error: false, fileName });
      },
      () => {
        if (!closed) setHeld({ uri: null, error: true, fileName });
      },
    );
    return () => {
      closed = true;
      if (uri) void files.release(uri);
    };
    // Held once per recording: a new `files` object mustn't re-copy.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileName]);

  return fileName && held.fileName === fileName ? { uri: held.uri, error: held.error } : NOTHING;
}
