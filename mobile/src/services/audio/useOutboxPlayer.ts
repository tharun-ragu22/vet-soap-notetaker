import { useEffect, useRef, useState } from 'react';

import type { QueueEntry } from '../upload/types';
import type { Playback, PlaybackFiles } from './types';
import { useHeldRecording } from './useHeldRecording';

export interface OutboxPlayer {
  /** The recording playing now (its row shows Stop). */
  playingId: string | null;
  /** The recording that couldn't be played, if the last Play failed. */
  failedId: string | null;
  /** Play a recording from the start, stopping any other. */
  play(id: string): void;
  stop(): void;
}

/**
 * The Outbox's Play/Stop: one recording at a time, played from its own cache copy
 * (so its upload finishing doesn't cut it off), stopped by Stop, by reaching the
 * end, by its row leaving the Outbox, or by the Outbox closing.
 * `usePlayback` is the native player hook (useExpoPlayback; a fake in tests).
 */
export function useOutboxPlayer(
  entries: QueueEntry[],
  files: PlaybackFiles,
  usePlayback: (uri: string | null) => Playback,
): OutboxPlayer {
  // The file is captured on Play: the entry loses it once it uploads.
  const [current, setCurrent] = useState<{ id: string; fileName: string } | null>(null);
  const [failedId, setFailedId] = useState<string | null>(null);
  const held = useHeldRecording(current?.fileName ?? null, files);
  const playback = usePlayback(held.uri);
  // The newest player, for the start effect below (which runs after this one).
  const latest = useRef(playback);
  useEffect(() => {
    latest.current = playback;
  });

  // Start once the copy has loaded.
  useEffect(() => {
    if (held.uri && playback.status.loaded) latest.current.play();
  }, [held.uri, playback.status.loaded]);

  // Over when it reaches the end, its row leaves the Outbox, or it can't be copied.
  // (Adjusted while rendering, React's pattern for state that follows other state.)
  if (current) {
    if (held.error) {
      setFailedId(current.id);
      setCurrent(null);
    } else if (playback.status.finished || !entries.some((entry) => entry.id === current.id)) {
      setCurrent(null);
    }
  }

  return {
    playingId: current?.id ?? null,
    failedId,
    play(playId) {
      const entry = entries.find((item) => item.id === playId);
      if (!entry || entry.stage !== 'audio') return;
      if (current) playback.pause();
      setFailedId(null);
      setCurrent({ id: playId, fileName: entry.fileName });
    },
    stop() {
      playback.pause();
      setCurrent(null);
    },
  };
}
