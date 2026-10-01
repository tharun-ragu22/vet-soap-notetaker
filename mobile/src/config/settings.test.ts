import {
  API_KEY_KEY,
  API_URL_KEY,
  defaultSettings,
  loadSettings,
  normalizeUrl,
  saveSettings,
  type SettingsStorage,
} from './settings';

/** A trivial in-memory SettingsStorage so these tests touch no native module. */
class FakeStorage implements SettingsStorage {
  readonly store = new Map<string, string>();
  constructor(initial: Record<string, string> = {}) {
    for (const [k, v] of Object.entries(initial)) this.store.set(k, v);
  }
  async getItem(key: string): Promise<string | null> {
    return this.store.has(key) ? (this.store.get(key) as string) : null;
  }
  async setItem(key: string, value: string): Promise<void> {
    this.store.set(key, value);
  }
}

describe('normalizeUrl', () => {
  it('trims whitespace and strips trailing slashes', () => {
    expect(normalizeUrl('  http://host:8000/// ')).toBe('http://host:8000');
  });
});

describe('defaultSettings', () => {
  it('reads the baked-in build-time env values', () => {
    const defaults = defaultSettings({
      EXPO_PUBLIC_VETSCRIBE_API_URL: 'http://192.168.1.50:8000',
      EXPO_PUBLIC_VETSCRIBE_API_KEY: 'secret',
    });
    expect(defaults).toEqual({ apiUrl: 'http://192.168.1.50:8000', apiKey: 'secret' });
  });

  it('yields blank defaults when nothing was baked in (vet enters it in Settings)', () => {
    expect(defaultSettings({})).toEqual({ apiUrl: '', apiKey: '' });
  });
});

describe('loadSettings', () => {
  const defaults = { apiUrl: 'http://baked:8000', apiKey: 'baked-key' };

  it('prefers saved values over the defaults', async () => {
    const storage = new FakeStorage({
      [API_URL_KEY]: 'http://192.168.9.9:8443',
      [API_KEY_KEY]: 'saved-key',
    });
    await expect(loadSettings(storage, defaults)).resolves.toEqual({
      apiUrl: 'http://192.168.9.9:8443',
      apiKey: 'saved-key',
    });
  });

  it('falls back to the baked defaults when nothing is saved', async () => {
    await expect(loadSettings(new FakeStorage(), defaults)).resolves.toEqual(defaults);
  });

  it('normalizes a saved url with a trailing slash', async () => {
    const storage = new FakeStorage({ [API_URL_KEY]: 'http://host:8000/' });
    const settings = await loadSettings(storage, defaults);
    expect(settings.apiUrl).toBe('http://host:8000');
  });

  it('falls back to the default url when the saved url is blank', async () => {
    const storage = new FakeStorage({ [API_URL_KEY]: '   ' });
    const settings = await loadSettings(storage, defaults);
    expect(settings.apiUrl).toBe(defaults.apiUrl);
  });

  it('honors a saved empty key as a deliberate unauthenticated backend', async () => {
    const storage = new FakeStorage({ [API_KEY_KEY]: '' });
    const settings = await loadSettings(storage, defaults);
    expect(settings.apiKey).toBe('');
  });
});

describe('saveSettings', () => {
  it('persists normalized values and returns what was stored', async () => {
    const storage = new FakeStorage();
    const stored = await saveSettings(storage, {
      apiUrl: '  http://192.168.1.5:8443/ ',
      apiKey: '  tok  ',
    });
    expect(stored).toEqual({ apiUrl: 'http://192.168.1.5:8443', apiKey: 'tok' });
    expect(storage.store.get(API_URL_KEY)).toBe('http://192.168.1.5:8443');
    expect(storage.store.get(API_KEY_KEY)).toBe('tok');
  });

  it('round-trips through loadSettings', async () => {
    const storage = new FakeStorage();
    await saveSettings(storage, { apiUrl: 'http://192.168.1.5:8443', apiKey: 'tok' });
    await expect(loadSettings(storage, { apiUrl: '', apiKey: '' })).resolves.toEqual({
      apiUrl: 'http://192.168.1.5:8443',
      apiKey: 'tok',
    });
  });
});
