/** The three states the exam-capture UI reflects: Idle, Recording, Processing. */
export type RecordingState = 'idle' | 'recording' | 'processing';

/** The artifact a finished recording produces, ready to hand to the ApiClient. */
export interface RecordingResult {
  /** Local file URI of the captured audio (e.g. file:///.../rec.m4a). */
  uri: string;
  /** How long the recording ran, in milliseconds. */
  durationMillis: number;
}

/**
 * The thin native-audio seam. AudioService owns the state machine and depends only
 * on this interface, so tests inject a fake and the real ExpoAudioRecorder (wrapping
 * expo-audio) is wired in only at the app's edge — the same dependency-injection
 * pattern the desktop app uses through build_app().
 */
export interface Recorder {
  start(): Promise<void>;
  stop(): Promise<RecordingResult>;
}

/**
 * Keeps the device display from sleeping while an exam is being recorded. Like
 * {@link Recorder} it's a thin injectable seam: RecorderScreen owns *when* to hold
 * the screen awake (only while recording), and the real expoKeepAwake wrapper is
 * wired in only at the edge, so component tests inject a fake and import no native
 * module. Both methods are best-effort — a failure must never break recording.
 */
export interface KeepAwake {
  activate(): void;
  deactivate(): void;
}

/** Where a recording's playback is up to. */
export interface PlaybackStatus {
  loaded: boolean;
  playing: boolean;
  /** It has just played to the end. */
  finished: boolean;
}

/**
 * The thin native-playback seam for the Outbox's Play/Stop. useOutboxPlayer owns
 * when to play and stop and depends only on this, so tests inject a fake; the real
 * useExpoPlayback (wrapping expo-audio) is wired in only at the route.
 */
export interface Playback {
  status: PlaybackStatus;
  play(): void;
  pause(): void;
}

/**
 * Gives playback its own copy of a queued recording, so the queue can upload
 * and delete the original while the vet is still listening.
 */
export interface PlaybackFiles {
  /** Copy a stored recording somewhere private to playback; returns the copy's uri. */
  hold(fileName: string): Promise<string>;
  /** Delete a copy made by {@link hold}. */
  release(uri: string): Promise<void>;
}
