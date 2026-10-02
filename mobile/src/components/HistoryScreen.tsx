import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';

import type { ApiClient } from '../services/api/ApiClient';
import type { Exam } from '../services/api/types';

export interface HistoryScreenProps {
  /** Only the read surface is needed here; the backend is the source of truth. */
  apiClient: Pick<ApiClient, 'fetchHistory'>;
  /** Called with the exam id when a row is tapped (route pushes the editor). */
  onOpenExam?: (id: string) => void;
  /**
   * Bumped by the route each time the screen regains focus. A change triggers a
   * quiet background refetch, so an exam deleted on the editor screen disappears
   * the moment the user returns here. The list stays mounted under the pushed
   * editor, so a plain mount effect would never re-run on the way back and the
   * stale (deleted) row would linger until the screen was left entirely. Left
   * undefined in unit tests, which render this screen with no navigator.
   */
  reloadSignal?: number;
}

type Status = 'loading' | 'ready' | 'error';

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

/**
 * Feature B: the exam history feed, synced across mobile and desktop via the backend.
 * Loads on mount and exposes explicit loading / empty / error (with retry) states so a
 * transient backend hiccup never leaves a blank screen with no way forward.
 */
export function HistoryScreen({ apiClient, onOpenExam, reloadSignal }: HistoryScreenProps) {
  const [status, setStatus] = useState<Status>('loading');
  const [exams, setExams] = useState<Exam[]>([]);

  const load = useCallback(
    async (quiet = false) => {
      // A quiet refresh keeps the current list on screen (no full-screen spinner)
      // so returning to History doesn't flash "Loading…" every time.
      if (!quiet) setStatus('loading');
      try {
        const result = await apiClient.fetchHistory();
        setExams(result);
        setStatus('ready');
      } catch {
        // Don't let a failed background refresh wipe out a list we already have;
        // only surface the error screen when there's nothing to fall back to.
        if (!quiet) setStatus('error');
      }
    },
    [apiClient],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Refetch quietly whenever the route reports the screen was re-focused (e.g. the
  // user came back after deleting an exam). Skip the first run: the mount effect
  // above already did the initial load, so firing here too would double-fetch.
  const firstFocus = useRef(true);
  useEffect(() => {
    if (reloadSignal === undefined) return;
    if (firstFocus.current) {
      firstFocus.current = false;
      return;
    }
    void load(true);
  }, [reloadSignal, load]);

  if (status === 'loading') {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
        <Text style={styles.muted}>Loading…</Text>
      </View>
    );
  }

  if (status === 'error') {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>Couldn't load exams.</Text>
        <Pressable accessibilityRole="button" style={styles.retry} onPress={() => load()}>
          <Text style={styles.retryText}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  if (exams.length === 0) {
    return (
      <View style={styles.center}>
        <Text style={styles.muted}>No exams yet.</Text>
      </View>
    );
  }

  return (
    <FlatList
      data={exams}
      keyExtractor={(exam) => exam.id}
      contentContainerStyle={styles.list}
      renderItem={({ item }) => (
        <Pressable
          testID={`exam-row-${item.id}`}
          accessibilityRole="button"
          style={styles.row}
          onPress={() => onOpenExam?.(item.id)}
        >
          {/* Exams rarely carry a patient name yet, so fall back to the creation
              date as the heading rather than a useless "Unknown patient". */}
          <Text style={styles.patient}>{item.patientName ?? formatDate(item.createdAt)}</Text>
          {/* Only show the date as a subtitle when it isn't already the heading. */}
          {item.patientName ? (
            <Text style={styles.date}>{formatDate(item.createdAt)}</Text>
          ) : null}
          <Text style={styles.snippet} numberOfLines={2}>
            {item.assessment || item.subjective || 'No note yet'}
          </Text>
        </Pressable>
      )}
    />
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    padding: 24,
    backgroundColor: '#fff',
  },
  list: {
    padding: 12,
    gap: 10,
  },
  row: {
    padding: 16,
    borderRadius: 12,
    backgroundColor: '#f2f5f8',
    gap: 4,
  },
  patient: {
    fontSize: 18,
    fontWeight: '700',
    color: '#1b3a5b',
  },
  date: {
    fontSize: 12,
    color: '#6b7480',
  },
  snippet: {
    fontSize: 14,
    color: '#333',
  },
  muted: {
    fontSize: 16,
    color: '#6b7480',
  },
  error: {
    fontSize: 16,
    color: '#c0392b',
    textAlign: 'center',
  },
  retry: {
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderRadius: 10,
    backgroundColor: '#1b7f4b',
  },
  retryText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
});
