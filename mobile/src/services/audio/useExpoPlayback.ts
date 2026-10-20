import { useEffect, useMemo } from 'react';
import { setAudioModeAsync, useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';

import type { Playback } from './types';

/**
 * The real {@link Playback}, adapting expo-audio's player hooks for
 * RecordingPlayerSheet. Like useExpoAudioRecorder this is the thin, untested native
 * edge; the controls' logic lives in the sheet and is tested against a fake.
 * A null uri (the copy isn't ready yet) gives a player with nothing loaded.
 */
export function useExpoPlayback(uri: string | null): Playback {
  // More frequent position updates than the 500 ms default, for a smooth scrubber.
  const player = useAudioPlayer(uri ? { uri } : null, { updateInterval: 250 });
  const status = useAudioPlayerStatus(player);

  // Closing the sheet stops the sound, whatever expo-audio does when it releases the player.
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
      status: {
        loaded: status.isLoaded,
        playing: status.playing,
        currentTime: status.currentTime,
        duration: status.duration,
      },
      play() {
        // Audible with the silent switch on, and out of record mode.
        void setAudioModeAsync({ playsInSilentMode: true, allowsRecording: false }).then(() => player.play());
      },
      pause() {
        player.pause();
      },
      // Exactly there: without tolerances expo-audio's iOS seek allows any error,
      // which landed scrubs back at the start or where it already was.
      seekTo: (seconds) => player.seekTo(seconds, 0, 0),
    }),
    [player, status.isLoaded, status.playing, status.currentTime, status.duration],
  );
}
