import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { asyncSettingsStorage } from '../config/asyncStorage';
import {
  loadSettings,
  saveSettings,
  type AppSettings,
  type SettingsStorage,
} from '../config/settings';
import { ApiClient } from './api/ApiClient';
import type { Exam } from './api/types';
import { AudioService } from './audio/AudioService';
import { readRecording } from './audio/readRecording';
import type { RecordingResult } from './audio/types';
import { useExpoAudioRecorder } from './audio/useExpoAudioRecorder';

/**
 * The app's wired collaborators, provided once at the root and consumed by the route
 * screens — the mobile analogue of the desktop app's build_app(). Screens receive
 * these through props for testability; only the route files reach for this context.
 */
export interface Services {
  apiClient: ApiClient;
  audioService: AudioService;
  /** Reads a finished recording off disk and uploads it, returning the created exam. */
  uploadRecording: (result: RecordingResult) => Promise<Exam>;
  /** The backend connection currently in effect (editable via the Settings screen). */
  settings: AppSettings;
  /** Persists new settings and rebuilds the ApiClient against them, no restart needed. */
  updateSettings: (next: AppSettings) => Promise<void>;
}

const ServicesContext = createContext<Services | null>(null);

export function ServicesProvider({
  children,
  storage = asyncSettingsStorage,
}: {
  children: ReactNode;
  /** Injectable for tests; defaults to the real AsyncStorage-backed store. */
  storage?: SettingsStorage;
}) {
  // The real microphone Recorder is hook-managed by expo-audio, so it must be
  // obtained here and fed into the AudioService instance.
  const recorder = useExpoAudioRecorder();

  // Settings are read from on-device storage (falling back to the build-time defaults),
  // so they aren't known until an async load resolves — null means "still loading".
  const [settings, setSettings] = useState<AppSettings | null>(null);

  useEffect(() => {
    let cancelled = false;
    void loadSettings(storage).then((loaded) => {
      if (!cancelled) setSettings(loaded);
    });
    return () => {
      cancelled = true;
    };
  }, [storage]);

  const updateSettings = useCallback(
    async (next: AppSettings) => {
      // Persist first, then apply exactly what was stored (normalized) so a later
      // reload matches what's live — mirrors the desktop Settings window's live-apply.
      const stored = await saveSettings(storage, next);
      setSettings(stored);
    },
    [storage],
  );

  const services = useMemo<Services | null>(() => {
    if (!settings) return null;
    const apiClient = new ApiClient({ baseUrl: settings.apiUrl, apiKey: settings.apiKey });
    const audioService = new AudioService(recorder);
    const uploadRecording = async (result: RecordingResult): Promise<Exam> => {
      const bytes = await readRecording(result.uri);
      // expo-audio's HIGH_QUALITY preset records AAC in an .m4a container.
      return apiClient.generateNote(bytes, 'audio/m4a');
    };
    return { apiClient, audioService, uploadRecording, settings, updateSettings };
  }, [recorder, settings, updateSettings]);

  if (!services) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator />
        <Text style={styles.loadingText}>Loading…</Text>
      </View>
    );
  }

  return <ServicesContext.Provider value={services}>{children}</ServicesContext.Provider>;
}

export function useServices(): Services {
  const services = useContext(ServicesContext);
  if (!services) {
    throw new Error('useServices must be used within a ServicesProvider');
  }
  return services;
}

const styles = StyleSheet.create({
  loading: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    backgroundColor: '#fff',
  },
  loadingText: {
    fontSize: 16,
    color: '#6b7480',
  },
});
