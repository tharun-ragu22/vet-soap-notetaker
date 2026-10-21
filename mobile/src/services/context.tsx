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
import type { Appointment } from './api/types';
import { AudioService } from './audio/AudioService';
import type { RecordingResult } from './audio/types';
import { useExpoAudioRecorder } from './audio/useExpoAudioRecorder';
import { AppointmentWatcher, readyNoteOf, type ReadyNote } from './events/appointmentWatcher';
import { asyncWaitingStore } from './events/asyncWaitingStore';
import { expoStreamFetch } from './events/expoStreamFetch';
import { readEventStream } from './events/sse';
import { asyncQueueStore } from './upload/asyncQueueStore';
import { expoFileStore } from './upload/expoFileStore';
import type { QueueEntry } from './upload/types';
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
   * appointment if it uploaded right away (jump straight to the notes), or null if
   * it's still queued — the background queue keeps retrying either way, so nothing is lost.
   */
  enqueueRecording: (result: RecordingResult) => Promise<Appointment | null>;
  /** Recordings still on the phone waiting to become notes (banner + Uploads screen). */
  uploads: QueueEntry[];
  /** The recording uploading right now, if any. */
  activeUploadId: string | null;
  /** The vet's manual Retry: resolves to the appointment if it landed. */
  retryUpload: (id: string) => Promise<Appointment | null>;
  /** The vet's Discard: deletes the recording from the phone. */
  discardUpload: (id: string) => Promise<void>;
  /** Recordings that finished processing since the toast was last dismissed. */
  readyNotes: ReadyNote[];
  /** Hide the toast (it timed out, or the vet tapped it). */
  dismissReady: () => void;
  /** Every recording announced as finished this session (kept after the toast hides). */
  finishedNotes: ReadonlySet<string>;
  /** Finished recordings the vet has since looked at (Notes, or the appointment itself). */
  seenNotes: ReadonlySet<string>;
  markNotesSeen: (appointmentIds: string[]) => void;
  /** The backend connection currently in effect (editable via the Settings screen). */
  settings: AppSettings;
  /** Persists new settings and rebuilds the ApiClient against them, no restart needed. */
  updateSettings: (next: AppSettings) => Promise<void>;
}

/** `set` plus `ids`, or `set` itself when it already has them all (no re-render). */
function withAll(set: ReadonlySet<string>, ids: string[]): ReadonlySet<string> {
  if (ids.every((id) => set.has(id))) return set;
  return new Set([...set, ...ids]);
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
  const [uploads, setUploads] = useState<QueueEntry[]>([]);
  const [activeUploadId, setActiveUploadId] = useState<string | null>(null);
  const [readyNotes, setReadyNotes] = useState<ReadyNote[]>([]);
  const [finishedNotes, setFinishedNotes] = useState<ReadonlySet<string>>(() => new Set());
  const [seenNotes, setSeenNotes] = useState<ReadonlySet<string>>(() => new Set());

  const announce = useCallback((note: ReadyNote) => {
    setReadyNotes((current) => [...current.filter((n) => n.appointmentId !== note.appointmentId), note]);
    setFinishedNotes((current) => withAll(current, [note.appointmentId]));
  }, []);
  const dismissReady = useCallback(() => setReadyNotes([]), []);
  const markNotesSeen = useCallback((ids: string[]) => {
    setSeenNotes((current) => withAll(current, ids));
  }, []);

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

  // Hears when uploaded recordings finish processing on the backend (its /api/events
  // stream, open only while the app is in front and something is waiting) and
  // announces them through the toast. Rebuilt with the backend connection; what it
  // waits on is persisted.
  const watcher = useMemo(() => {
    if (!apiClient) return null;
    return new AppointmentWatcher({
      store: asyncWaitingStore,
      getAppointment: (id) => apiClient.getAppointment(id),
      openStream: (signal, onEvent) =>
        readEventStream({ target: apiClient.eventStream(), fetch: expoStreamFetch, signal, onEvent }),
      onReady: announce,
    });
  }, [apiClient, announce]);

  useEffect(() => {
    if (!watcher) return;
    void watcher.load();
    watcher.setActive(AppState.currentState === 'active');
    const subscription = AppState.addEventListener('change', (state) => {
      watcher.setActive(state === 'active');
    });
    return () => {
      subscription.remove();
      watcher.stop();
    };
  }, [watcher]);

  // One queue, rebuilt only when the backend connection changes (rare — a Settings
  // edit). Its state is persisted, so a rebuild reloads the pending entries from disk;
  // nothing is lost. Null until the first settings load resolves.
  const queue = useMemo(() => {
    if (!apiClient || !watcher) return null;
    return new UploadQueue({
      store: asyncQueueStore,
      files: expoFileStore,
      uploader: {
        checkReachable: () => apiClient.checkReachable(),
        createAppointment: (bytes, mime, options) => apiClient.createAppointment(bytes, mime, options),
        completeAppointment: (id, options) => apiClient.completeAppointment(id, options),
      },
      onChange: (entries, activeId) => {
        setUploads(entries);
        setActiveUploadId(activeId);
      },
      // The backend has the recording: wait for its outcome (or announce it, if a
      // repeat found it already failed).
      onUploaded: (appointment) => {
        if (appointment.status === 'processing') void watcher.wait(appointment.id);
        else announce(readyNoteOf(appointment));
      },
      // An older, synchronous backend finished it during the upload itself.
      onAppointmentReady: (appointment) => announce(readyNoteOf(appointment)),
    });
  }, [apiClient, watcher, announce]);

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
    async (result: RecordingResult): Promise<Appointment | null> => {
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

  const retryUpload = useCallback(
    async (id: string): Promise<Appointment | null> => (queue ? queue.retry(id) : null),
    [queue],
  );

  const discardUpload = useCallback(
    async (id: string): Promise<void> => {
      await queue?.remove(id);
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
      uploads,
      activeUploadId,
      retryUpload,
      discardUpload,
      readyNotes,
      dismissReady,
      finishedNotes,
      seenNotes,
      markNotesSeen,
      settings,
      updateSettings,
    };
  }, [
    apiClient,
    audioService,
    enqueueRecording,
    uploads,
    activeUploadId,
    retryUpload,
    discardUpload,
    readyNotes,
    dismissReady,
    finishedNotes,
    seenNotes,
    markNotesSeen,
    settings,
    updateSettings,
  ]);

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
