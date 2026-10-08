import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { ActivityIndicator, AppState, StyleSheet, Text, View } from 'react-native';

import { asyncSettingsStorage } from '../config/asyncStorage';
import {
  loadSettings,
  saveSettings,
  type AppSettings,
  type SettingsStorage,
} from '../config/settings';
import { ApiClient, ApiClientError } from './api/ApiClient';
import type { Exam } from './api/types';
import { AudioService } from './audio/AudioService';
import type { RecordingResult } from './audio/types';
import { useExpoAudioRecorder } from './audio/useExpoAudioRecorder';
import { asyncQueueStore } from './upload/asyncQueueStore';
import { expoFileStore } from './upload/expoFileStore';
import { UploadQueue } from './upload/uploadQueue';

/** How often the queue retries itself while the app is foregrounded. */
const QUEUE_POLL_MS = 30_000;

/**
 * The app's wired collaborators, provided once at the root and consumed by the route
 * screens — the mobile analogue of the desktop app's build_app(). Screens receive
 * these through props for testability; only the route files reach for this context.
 */
export interface Services {
  apiClient: ApiClient;
  audioService: AudioService;
  /**
   * Durably queue a finished recording and attempt it immediately. Resolves to the
   * exam if it uploaded right away (jump straight to the note), or null if it's
   * still queued — the background queue keeps retrying either way, so nothing is lost.
   */
  enqueueRecording: (result: RecordingResult) => Promise<Exam | null>;
  /** Number of recordings still waiting to upload (drives the pending banner). */
  pendingUploads: number;
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
  const [pendingUploads, setPendingUploads] = useState(0);

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

  const apiClient = useMemo(
    () => (settings ? new ApiClient({ baseUrl: settings.apiUrl, apiKey: settings.apiKey }) : null),
    [settings],
  );

  // One queue, rebuilt only when the backend connection changes (rare — a Settings
  // edit). Its state is persisted, so a rebuild reloads the pending entries from disk;
  // nothing is lost. Null until the first settings load resolves.
  const queue = useMemo(() => {
    if (!apiClient) return null;
    return new UploadQueue({
      store: asyncQueueStore,
      files: expoFileStore,
      uploader: {
        generateNote: (bytes, mime) => apiClient.generateNote(bytes, mime),
        completeNote: (id) => apiClient.completeNote(id),
      },
      onChange: (entries) => setPendingUploads(entries.length),
    });
  }, [apiClient]);

  // Restore persisted entries, drain once, then retry on a timer and whenever the
  // app returns to the foreground (a common moment for connectivity to be back).
  useEffect(() => {
    if (!queue) return;
    void queue.load().then(() => void queue.processOnce());
    queue.start(QUEUE_POLL_MS);
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') void queue.processOnce();
    });
    return () => {
      queue.stop();
      subscription.remove();
    };
  }, [queue]);

  const enqueueRecording = useCallback(
    async (result: RecordingResult): Promise<Exam | null> => {
      if (!queue) throw new ApiClientError('no backend configured');
      // Persist-first: the recording is durable before any upload is attempted.
      const entry = await queue.enqueue({
        uri: result.uri,
        // expo-audio's HIGH_QUALITY preset records AAC in an .m4a container.
        mimeType: 'audio/m4a',
        durationMillis: result.durationMillis,
      });
      return queue.tryProcess(entry.id);
    },
    [queue],
  );

  const audioService = useMemo(() => new AudioService(recorder), [recorder]);

  const services = useMemo<Services | null>(() => {
    if (!settings || !apiClient) return null;
    return {
      apiClient,
      audioService,
      enqueueRecording,
      pendingUploads,
      settings,
      updateSettings,
    };
  }, [apiClient, audioService, enqueueRecording, pendingUploads, settings, updateSettings]);

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
