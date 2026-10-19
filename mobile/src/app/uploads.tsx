import { router, Stack } from 'expo-router';

import { UploadsScreen } from '../components/UploadsScreen';
import { useServices } from '../services/context';

/** Outbox route (☰ → Outbox, or the home banner): recordings still on the phone, with a manual Retry and Discard. */
export default function UploadsRoute() {
  const { uploads, activeUploadId, retryUpload, discardUpload } = useServices();

  return (
    <>
      <Stack.Screen options={{ title: 'Outbox' }} />
      <UploadsScreen
        entries={uploads}
        activeId={activeUploadId}
        onRetry={retryUpload}
        onDiscard={discardUpload}
        onOpenAppointment={(id) => router.push(`/appointment/${id}`)}
      />
    </>
  );
}
