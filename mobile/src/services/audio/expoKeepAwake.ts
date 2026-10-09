import { activateKeepAwakeAsync, deactivateKeepAwake } from 'expo-keep-awake';

import type { KeepAwake } from './types';

/**
 * The real {@link KeepAwake}, backed by expo-keep-awake. This is the thin, untested
 * native edge (like useExpoAudioRecorder): RecorderScreen owns the decision of when
 * to hold the screen on, and this only translates that into the native calls.
 *
 * A fixed tag pairs each activate with its deactivate, so this wake-lock can't
 * desync with any other. Both calls are best-effort and swallow errors: keeping the
 * screen awake is a comfort feature and must never break or interrupt a recording.
 */
const TAG = 'vetscribe-recording';

export const expoKeepAwake: KeepAwake = {
  activate(): void {
    // Fire-and-forget: activateKeepAwakeAsync returns a promise we don't await, and
    // a rejection (e.g. unsupported platform) must not surface during a render.
    void activateKeepAwakeAsync(TAG).catch(() => {});
  },
  deactivate(): void {
    try {
      void Promise.resolve(deactivateKeepAwake(TAG)).catch(() => {});
    } catch {
      // ignore — releasing a lock that was never held, or on an unsupported
      // platform, is harmless.
    }
  },
};
