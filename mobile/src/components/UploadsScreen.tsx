import { useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';

import type { Appointment } from '../services/api/types';
import { describeUpload } from '../services/upload/describeUpload';
import type { QueueEntry } from '../services/upload/types';

export interface UploadsScreenProps {
  /** Every recording not yet turned into notes, oldest first (the queue's order). */
  entries: QueueEntry[];
  /** The entry uploading right now, if any. */
  activeId: string | null;
  /** Manual retry: resolves to the appointment if it landed, else null. */
  onRetry: (id: string) => Promise<Appointment | null>;
  /** Discard a recording (or forget an uploaded one) — only ever the vet's choice. */
  onDiscard: (id: string) => Promise<void>;
  onOpenAppointment: (id: string) => void;
}

function formatDuration(ms: number): string {
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/**
 * Uploads: every recording still on the phone waiting to become notes, with where
 * it's up to and why, plus a manual Retry and a two-tap Discard. Nothing here is
 * ever removed automatically except by a successful upload.
 */
export function UploadsScreen({
  entries,
  activeId,
  onRetry,
  onDiscard,
  onOpenAppointment,
}: UploadsScreenProps) {
  const [retrying, setRetrying] = useState<string | null>(null);
  const [armed, setArmed] = useState<string | null>(null);

  if (entries.length === 0) {
    return (
      <View style={styles.center}>
        <Text style={styles.muted}>All recordings are uploaded.</Text>
      </View>
    );
  }

  const handleRetry = async (id: string) => {
    setArmed(null);
    setRetrying(id);
    try {
      const appointment = await onRetry(id);
      if (appointment) onOpenAppointment(appointment.id);
    } finally {
      setRetrying(null);
    }
  };

  const handleDiscard = async (id: string) => {
    if (armed !== id) {
      setArmed(id);
      return;
    }
    setArmed(null);
    await onDiscard(id);
  };

  return (
    <FlatList
      style={styles.screen}
      contentContainerStyle={styles.list}
      data={entries}
      keyExtractor={(entry) => entry.id}
      renderItem={({ item }) => {
        const { status, detail } = describeUpload(item, retrying === item.id ? item.id : activeId);
        const busy = item.id === activeId || item.id === retrying;
        const uploaded = item.stage === 'note';
        const failed = Boolean(item.failed);
        return (
          <View testID={`upload-row-${item.id}`} style={styles.row}>
            <Text style={styles.date}>
              {new Date(item.createdAt).toLocaleString()}
              {item.stage === 'audio' ? ` · ${formatDuration(item.durationMillis)}` : ''}
            </Text>
            <Text style={[styles.status, failed && styles.failed]}>{status}</Text>
            {detail ? <Text style={styles.detail}>{detail}</Text> : null}
            {uploaded ? (
              <Text style={styles.detail}>
                Removing it here only clears this list; the appointment stays in History.
              </Text>
            ) : null}
            <View style={styles.actions}>
              <Pressable
                testID={`retry-${item.id}`}
                accessibilityRole="button"
                disabled={busy}
                style={[styles.button, styles.retry, busy && styles.disabled]}
                onPress={() => void handleRetry(item.id)}
              >
                <Text style={styles.buttonText}>{busy ? 'Uploading…' : 'Retry'}</Text>
              </Pressable>
              <Pressable
                testID={`discard-${item.id}`}
                accessibilityRole="button"
                disabled={busy}
                style={[styles.button, styles.discard, busy && styles.disabled]}
                onPress={() => void handleDiscard(item.id)}
              >
                <Text style={styles.discardText}>
                  {armed === item.id ? 'Tap again to discard' : uploaded ? 'Remove' : 'Discard'}
                </Text>
              </Pressable>
            </View>
          </View>
        );
      }}
    />
  );
}

const styles = StyleSheet.create({
  screen: {
    backgroundColor: '#fff',
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
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
  date: {
    fontSize: 12,
    color: '#6b7480',
  },
  status: {
    fontSize: 16,
    fontWeight: '700',
    color: '#1b3a5b',
  },
  failed: {
    color: '#c0392b',
  },
  detail: {
    fontSize: 14,
    color: '#333',
  },
  muted: {
    fontSize: 16,
    color: '#6b7480',
  },
  actions: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 8,
  },
  button: {
    paddingVertical: 10,
    paddingHorizontal: 18,
    borderRadius: 10,
  },
  retry: {
    backgroundColor: '#1b7f4b',
  },
  discard: {
    borderWidth: 1,
    borderColor: '#c0392b',
  },
  disabled: {
    opacity: 0.5,
  },
  buttonText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '700',
  },
  discardText: {
    color: '#c0392b',
    fontSize: 15,
    fontWeight: '600',
  },
});
