import { useEffect, useMemo } from 'react';
import { setAudioModeAsync, useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';

import type { Playback } from './types';

/**
 * The real {@link Playback}, adapting expo-audio's player hooks for the Outbox's
 * Play/Stop. Like useExpoAudioRecorder this is the thin native edge; when to play
 * and stop lives in useOutboxPlayer and is tested against a fake.
 * A null uri (nothing playing, or the copy isn't ready yet) gives a player with nothing loaded.
 */
export function useExpoPlayback(uri: string | null): Playback {
  const player = useAudioPlayer(uri ? { uri } : null);
  const status = useAudioPlayerStatus(player);

  // Stopping or leaving the Outbox silences it, whatever expo-audio does when it releases the player.
  useEffect(
    () => () => {
      try {
        player.pause();
      } catch {
        // Already released.
      }
    },
    [player],
  );

  return useMemo<Playback>(
    () => ({
      status: { loaded: status.isLoaded, playing: status.playing, finished: status.didJustFinish },
      play() {
        // Audible with the silent switch on, and out of record mode.
        void setAudioModeAsync({ playsInSilentMode: true, allowsRecording: false }).then(() => player.play());
      },
      pause() {
        player.pause();
      },
    }),
    [player, status.isLoaded, status.playing, status.didJustFinish],
  );
}
