export class ConfigError extends Error {}

export interface AppConfig {
  /** Base URL of the Vet Soap Notetaker backend, without a trailing slash. */
  apiUrl: string;
  /** Shared bearer secret; empty string means the backend is unauthenticated. */
  apiKey: string;
}

type Env = Record<string, string | undefined>;

/**
 * Reads configuration from a local `.env` file (via Expo's EXPO_PUBLIC_* inlining) —
 * no host OS environment variables required. Pass an explicit env in tests.
 */
export function loadConfig(env: Env = process.env as Env): AppConfig {
  const apiUrl = env.EXPO_PUBLIC_VETSCRIBE_API_URL?.trim();
  if (!apiUrl) {
    throw new ConfigError(
      'EXPO_PUBLIC_VETSCRIBE_API_URL is not set — copy .env.example to .env and fill it in.',
    );
  }
  return {
    apiUrl: apiUrl.replace(/\/+$/, ''),
    apiKey: env.EXPO_PUBLIC_VETSCRIBE_API_KEY?.trim() ?? '',
  };
}
