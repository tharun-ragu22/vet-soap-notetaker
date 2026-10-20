import AsyncStorage from '@react-native-async-storage/async-storage';

import type { WaitingStore } from './appointmentWatcher';

/** AsyncStorage key for the uploaded recordings still processing on the backend. */
export const WAITING_APPOINTMENTS_KEY = 'vetscribe.waitingAppointments';

/** The real, on-device {@link WaitingStore}: just the appointment ids, as JSON. */
export const asyncWaitingStore: WaitingStore = {
  async load(): Promise<string[]> {
    try {
      const raw = await AsyncStorage.getItem(WAITING_APPOINTMENTS_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : [];
    } catch {
      // Unreadable: start empty. Those notes are still in Notes, just not announced.
      return [];
    }
  },
  async save(ids: string[]): Promise<void> {
    await AsyncStorage.setItem(WAITING_APPOINTMENTS_KEY, JSON.stringify(ids));
  },
};
