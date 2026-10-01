import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import type { AppSettings } from '../config/settings';

export interface SettingsScreenProps {
  /** The settings currently in effect, used to pre-fill the form. */
  settings: AppSettings;
  /** Persists and live-applies the edited settings; rejects to surface a save error. */
  onSave: (next: AppSettings) => Promise<void>;
  /** Called after a successful save (e.g. to navigate back to the recorder). */
  onSaved?: (next: AppSettings) => void;
}

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** The backend must be an http(s) URL; anything else can't be reached by the client. */
function validateUrl(url: string): string | null {
  const trimmed = url.trim();
  if (!trimmed) return 'Enter the backend address.';
  if (!/^https?:\/\/.+/i.test(trimmed)) {
    return 'Address must start with http:// or https://';
  }
  return null;
}

/**
 * Lets the vet point the app at the clinic's VetScribe backend without a rebuild — the
 * mobile analogue of the desktop Settings window's endpoint field. The backend URL and
 * optional bearer key are persisted on-device and applied live, so a changed clinic IP
 * is a 10-second edit rather than a fresh EAS build.
 */
export function SettingsScreen({ settings, onSave, onSaved }: SettingsScreenProps) {
  const [apiUrl, setApiUrl] = useState(settings.apiUrl);
  const [apiKey, setApiKey] = useState(settings.apiKey);
  const [status, setStatus] = useState<SaveStatus>('idle');
  const [error, setError] = useState<string | null>(null);

  const markDirty = () => {
    // Any edit invalidates a prior "Saved" confirmation.
    if (status !== 'saving') setStatus('idle');
  };

  const handleSave = async () => {
    const urlError = validateUrl(apiUrl);
    if (urlError) {
      setError(urlError);
      setStatus('error');
      return;
    }
    setStatus('saving');
    setError(null);
    const next: AppSettings = { apiUrl, apiKey };
    try {
      await onSave(next);
      setStatus('saved');
      onSaved?.(next);
    } catch (e) {
      setError(messageOf(e));
      setStatus('error');
    }
  };

  const saveLabel = status === 'saving' ? 'Saving…' : 'Save';

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.title}>Backend connection</Text>
      <Text style={styles.help}>
        Point VetScribe at the clinic&apos;s backend. Use the server computer&apos;s address on the
        clinic Wi-Fi — for example http://192.168.1.50:8443
      </Text>

      <View style={styles.field}>
        <Text style={styles.label}>Backend URL</Text>
        <TextInput
          testID="field-apiUrl"
          style={styles.input}
          value={apiUrl}
          onChangeText={(value) => {
            setApiUrl(value);
            markDirty();
          }}
          placeholder="http://192.168.1.50:8443"
          placeholderTextColor="#9aa3ad"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          inputMode="url"
        />
      </View>

      <View style={styles.field}>
        <Text style={styles.label}>API key (optional)</Text>
        <TextInput
          testID="field-apiKey"
          style={styles.input}
          value={apiKey}
          onChangeText={(value) => {
            setApiKey(value);
            markDirty();
          }}
          placeholder="Leave blank if the backend is unauthenticated"
          placeholderTextColor="#9aa3ad"
          autoCapitalize="none"
          autoCorrect={false}
          secureTextEntry
        />
      </View>

      <Pressable
        accessibilityRole="button"
        style={[styles.button, status === 'saving' && styles.busy]}
        onPress={handleSave}
        disabled={status === 'saving'}
      >
        <Text style={styles.buttonText}>{saveLabel}</Text>
      </Pressable>
      {status === 'saved' ? <Text style={styles.ok}>Saved ✓</Text> : null}
      {status === 'error' ? <Text style={styles.error}>{error}</Text> : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: 16,
    gap: 14,
    backgroundColor: '#fff',
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: '#1b3a5b',
  },
  help: {
    fontSize: 14,
    color: '#6b7480',
    lineHeight: 20,
  },
  field: {
    gap: 4,
  },
  label: {
    fontSize: 13,
    fontWeight: '700',
    color: '#6b7480',
    textTransform: 'uppercase',
  },
  input: {
    minHeight: 44,
    borderWidth: 1,
    borderColor: '#ccd4dc',
    borderRadius: 8,
    padding: 10,
    fontSize: 15,
    color: '#1a1a1a',
  },
  button: {
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
    backgroundColor: '#1b3a5b',
  },
  busy: {
    opacity: 0.6,
  },
  buttonText: {
    color: '#fff',
    fontSize: 17,
    fontWeight: '700',
  },
  ok: {
    color: '#1b7f4b',
    fontSize: 14,
    fontWeight: '600',
    textAlign: 'center',
  },
  error: {
    color: '#c0392b',
    fontSize: 14,
    textAlign: 'center',
  },
});
