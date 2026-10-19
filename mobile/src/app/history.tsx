import { router, Stack, useFocusEffect } from 'expo-router';
import { useCallback, useRef, useState } from 'react';

import { HistoryScreen } from '../components/HistoryScreen';
import { useServices } from '../services/context';

/** Notes route (☰ → Notes): the synced appointment feed; tapping a row opens the appointment. */
export default function HistoryRoute() {
  const { apiClient } = useServices();

  // The list stays mounted while an appointment is pushed on top, so returning
  // after a delete wouldn't otherwise refetch. Bump a signal on every *re-focus*
  // (skipping the initial one, which the list's own mount load already covers) to
  // tell HistoryScreen to quietly refresh and drop any now-deleted rows.
  const [reloadSignal, setReloadSignal] = useState(0);
  const focusedOnce = useRef(false);
  useFocusEffect(
    useCallback(() => {
      if (!focusedOnce.current) {
        focusedOnce.current = true;
        return;
      }
      setReloadSignal((n) => n + 1);
    }, []),
  );

  return (
    <>
      <Stack.Screen options={{ title: 'Notes' }} />
      <HistoryScreen
        apiClient={apiClient}
        reloadSignal={reloadSignal}
        onOpenAppointment={(id) => router.push(`/appointment/${id}`)}
      />
    </>
  );
}
