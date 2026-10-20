import { router, Stack } from 'expo-router';

import { UploadsScreen } from '../components/UploadsScreen';
import { useExpoPlayback } from '../services/audio/useExpoPlayback';
import { useOutboxPlayer } from '../services/audio/useOutboxPlayer';
import { useServices } from '../services/context';
import { expoPlaybackFiles } from '../services/upload/expoFileStore';

/**
 * Outbox route (☰ → Outbox, or the home banner): recordings still on the phone, with
 * ▶ Play / ■ Stop, a manual Retry and Discard. Leaving the Outbox stops the sound.
 */
export default function UploadsRoute() {
  const { audioService, uploads, activeUploadId, retryUpload, discardUpload } = useServices();
  const player = useOutboxPlayer(uploads, expoPlaybackFiles, useExpoPlayback);

  return (
    <>
      <Stack.Screen options={{ title: 'Outbox' }} />
      <UploadsScreen
        entries={uploads}
        activeId={activeUploadId}
        onRetry={retryUpload}
        onDiscard={discardUpload}
        onOpenAppointment={(id) => router.push(`/appointment/${id}`)}
        onPlay={player.play}
        onStop={player.stop}
        playingId={player.playingId}
        failedId={player.failedId}
        recording={audioService.isRecording}
      />
    </>
  );
}
