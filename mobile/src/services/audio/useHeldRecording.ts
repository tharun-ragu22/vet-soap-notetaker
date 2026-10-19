import { useEffect, useState } from 'react';

import type { PlaybackFiles } from './types';

export interface HeldRecording {
  /** The player's own copy, once it's ready. */
  uri: string | null;
  /** The recording couldn't be copied (e.g. it had already uploaded and been deleted). */
  error: boolean;
}

/**
 * Holds a private copy of a queued recording for as long as the player is open, and
 * releases it when the player closes. The player plays the copy, so the upload
 * queue can finish and delete the original without cutting the vet off.
 */
export function useHeldRecording(fileName: string | null, files: PlaybackFiles): HeldRecording {
  const [held, setHeld] = useState<HeldRecording>({ uri: null, error: false });

  useEffect(() => {
    if (!fileName) return;
    let closed = false;
    let uri: string | null = null;
    files.hold(fileName).then(
      (copy) => {
        uri = copy;
        // Closed before the copy finished: nobody will play it.
        if (closed) void files.release(copy);
        else setHeld({ uri: copy, error: false });
      },
      () => {
        if (!closed) setHeld({ uri: null, error: true });
      },
    );
    return () => {
      closed = true;
      if (uri) void files.release(uri);
    };
    // Held once for the life of the player: a new `files` object mustn't re-copy.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileName]);

  return held;
}
