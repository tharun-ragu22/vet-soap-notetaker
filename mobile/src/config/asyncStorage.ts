import AsyncStorage from '@react-native-async-storage/async-storage';

import type { SettingsStorage } from './settings';

/**
 * The real, on-device {@link SettingsStorage}, backed by AsyncStorage (the Expo-blessed
 * persistent key-value store). Kept in its own module so the pure settings logic can be
 * tested in Node without importing the native AsyncStorage module.
 */
export const asyncSettingsStorage: SettingsStorage = {
  getItem: (key) => AsyncStorage.getItem(key),
  setItem: (key, value) => AsyncStorage.setItem(key, value),
};
