import { router, Stack, useFocusEffect } from 'expo-router';
import { useCallback, useRef, useState } from 'react';

import { HistoryScreen } from '../components/HistoryScreen';
import { useServices } from '../services/context';

/** History route: the synced exam feed; tapping a row opens it in the editor. */
export default function HistoryRoute() {
  const { apiClient } = useServices();

  // The list stays mounted while the exam editor is pushed on top, so returning
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
      <Stack.Screen options={{ title: 'Exam History' }} />
      <HistoryScreen
        apiClient={apiClient}
        reloadSignal={reloadSignal}
        onOpenExam={(id) => router.push(`/exam/${id}`)}
      />
    </>
  );
}
