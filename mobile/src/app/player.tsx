import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';

import { RecordingPlayerSheet } from '../components/RecordingPlayerSheet';
import { useExpoPlayback } from '../services/audio/useExpoPlayback';
import { useHeldRecording } from '../services/audio/useHeldRecording';
import { useServices } from '../services/context';
import { describeUpload } from '../services/upload/describeUpload';
import { expoPlaybackFiles } from '../services/upload/expoFileStore';
import type { AudioEntry } from '../services/upload/types';

/**
 * Player sheet (Outbox → ▶ Play), presented as a modal the vet swipes down to close
 * (see _layout.tsx). The recording is captured on open and played from the player's
 * own copy, so it stays playable if its upload finishes meanwhile.
 */
export default function PlayerRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { uploads, activeUploadId } = useServices();
  const [entry] = useState(() =>
    uploads.find((item): item is AudioEntry => item.id === id && item.stage === 'audio'),
  );
  const held = useHeldRecording(entry?.fileName ?? null, expoPlaybackFiles);
  const playback = useExpoPlayback(held.uri);

  const live = uploads.find((item) => item.id === id);
  return (
    <RecordingPlayerSheet
      title={entry ? new Date(entry.createdAt).toLocaleString() : 'Recording'}
      durationMillis={entry?.durationMillis ?? 0}
      statusText={live ? describeUpload(live, activeUploadId).status : ''}
      uploaded={Boolean(entry) && (!live || live.stage === 'note')}
      error={!entry || held.error}
      playback={playback}
    />
  );
}
