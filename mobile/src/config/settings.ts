import { ConfigError, loadConfig } from './env';
import type { AppConfig } from './env';

/**
 * Runtime-configurable app settings. Unlike {@link loadConfig}, which reads the URL/key
 * baked in at build time, these are editable on-device through the Settings screen and
 * persisted across launches. The build-time env values become the *defaults* the vet
 * sees on first launch; whatever they save then overrides them.
 *
 * Why this exists: the backend lives on the clinic LAN at an address that can change
 * (DHCP, a new router) and differs per clinic. Baking it into the build meant a fresh
 * EAS build every time it moved; now the vet just edits it in the app.
 */
export type AppSettings = AppConfig;

/** AsyncStorage keys. Namespaced so they can't collide with other libraries' keys. */
export const API_URL_KEY = 'vetscribe.apiUrl';
export const API_KEY_KEY = 'vetscribe.apiKey';

/**
 * The minimal async key-value surface we depend on — a subset of AsyncStorage. Keeping
 * it an interface lets the pure settings logic (and its tests) run in Node with a plain
 * in-memory fake, without pulling in the native AsyncStorage module.
 */
export interface SettingsStorage {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
}

/** Trim and drop any trailing slashes so path joins against the base URL stay clean. */
export function normalizeUrl(url: string): string {
  return url.trim().replace(/\/+$/, '');
}

/**
 * The build-time baked configuration, used as the defaults before the vet has saved
 * anything. A build with no URL baked in (the low-effort path, where the vet enters it
 * in Settings on first launch) yields blank defaults rather than crashing the app.
 */
export function defaultSettings(env: Record<string, string | undefined> = process.env): AppSettings {
  try {
    return loadConfig(env);
  } catch (error) {
    if (error instanceof ConfigError) {
      return { apiUrl: '', apiKey: '' };
    }
    throw error;
  }
}

/**
 * Load the effective settings: the vet's saved values when present, otherwise the
 * build-time defaults. A blank saved URL falls back to the default too, so clearing the
 * field never strands the app with no backend when one was baked in.
 */
export async function loadSettings(
  storage: SettingsStorage,
  defaults: AppSettings = defaultSettings(),
): Promise<AppSettings> {
  const [savedUrl, savedKey] = await Promise.all([
    storage.getItem(API_URL_KEY),
    storage.getItem(API_KEY_KEY),
  ]);
  const trimmedUrl = savedUrl?.trim();
  return {
    apiUrl: trimmedUrl ? normalizeUrl(trimmedUrl) : defaults.apiUrl,
    // A saved empty key is meaningful (an unauthenticated backend), so only fall back
    // to the default key when nothing has been saved at all.
    apiKey: savedKey ?? defaults.apiKey,
  };
}

/**
 * Persist the vet's settings and return the normalized values actually stored, so the
 * caller can apply exactly what's on disk (trailing slash stripped, whitespace trimmed).
 */
export async function saveSettings(
  storage: SettingsStorage,
  settings: AppSettings,
): Promise<AppSettings> {
  const normalized: AppSettings = {
    apiUrl: normalizeUrl(settings.apiUrl),
    apiKey: settings.apiKey.trim(),
  };
  await Promise.all([
    storage.setItem(API_URL_KEY, normalized.apiUrl),
    storage.setItem(API_KEY_KEY, normalized.apiKey),
  ]);
  return normalized;
}
