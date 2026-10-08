import AsyncStorage from '@react-native-async-storage/async-storage';

import type { QueueEntry, QueueStore } from './types';

/** AsyncStorage key for the upload queue metadata. Namespaced like the settings keys. */
export const UPLOAD_QUEUE_KEY = 'vetscribe.uploadQueue';

/**
 * The real, on-device {@link QueueStore}, backed by AsyncStorage. Stores only the
 * queue *metadata* (ids, stages, attempts) — never the audio bytes, which live on
 * disk via the FileStore. Kept in its own module so the pure UploadQueue logic can
 * be tested in Node without the native AsyncStorage module.
 */
export const asyncQueueStore: QueueStore = {
  async load(): Promise<QueueEntry[]> {
    try {
      const raw = await AsyncStorage.getItem(UPLOAD_QUEUE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? (parsed as QueueEntry[]) : [];
    } catch {
      // A corrupt/unreadable queue must not crash startup; start empty.
      return [];
    }
  },
  async save(entries: QueueEntry[]): Promise<void> {
    await AsyncStorage.setItem(UPLOAD_QUEUE_KEY, JSON.stringify(entries));
  },
};
