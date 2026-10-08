import { useCallback, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { AudioService } from '../services/audio/AudioService';
import type { RecordingResult } from '../services/audio/types';
import type { Exam } from '../services/api/types';

export interface RecorderScreenProps {
  /** The capture state machine (idle → recording → processing → idle). */
  audioService: AudioService;
  /**
   * Durably queue the finished recording and attempt it immediately. Resolves to the
   * exam if it uploaded right away, or null if it's still queued for background retry.
   */
  enqueueRecording: (result: RecordingResult) => Promise<Exam | null>;
  /** Called once the backend has generated and stored the note. */
  onRecorded?: (exam: Exam) => void;
}

type Phase = 'idle' | 'recording' | 'processing';

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Feature A: one-tap exam audio capture. A single big control drives the whole
 * lifecycle — tap to start, tap to stop-and-upload — and every failure path returns
 * the button to idle so it can never become a silent no-op (the desktop Pipeline's
 * hard rule, mirrored here through AudioService).
 */
export function RecorderScreen({ audioService, enqueueRecording, onRecorded }: RecorderScreenProps) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const handleStart = useCallback(async () => {
    setError(null);
    setNotice(null);
    try {
      await audioService.start();
      setPhase('recording');
    } catch (e) {
      // A failed start (e.g. permission denied) leaves the machine idle.
      setError(messageOf(e));
      setPhase('idle');
    }
  }, [audioService]);

  const handleStop = useCallback(async () => {
    setPhase('processing');
    let result: RecordingResult;
    try {
      result = await audioService.stop();
    } catch (e) {
      // AudioService already reset itself to idle when stop() failed.
      setError(messageOf(e));
      setPhase('idle');
      return;
    }
    try {
      const exam = await enqueueRecording(result);
      if (exam) {
        onRecorded?.(exam);
      } else {
        // Saved durably but not uploaded yet — the queue will keep retrying.
        setNotice('Saved — uploading in the background.');
      }
    } catch (e) {
      // enqueue itself failed (couldn't even save the file to disk).
      setError(`Couldn't save recording: ${messageOf(e)}`);
    } finally {
      // Whether the upload succeeded or failed, return to idle for the next exam.
      audioService.reset();
      setPhase('idle');
    }
  }, [audioService, enqueueRecording, onRecorded]);

  const onPress = phase === 'recording' ? handleStop : handleStart;
  const isProcessing = phase === 'processing';
  const label =
    phase === 'idle'
      ? 'Start Exam Recording'
      : phase === 'recording'
        ? 'Stop & Save'
        : 'Processing…';

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Vet Soap Notetaker</Text>
      {phase === 'recording' ? (
        <Text accessibilityLabel="recording" style={styles.recording}>
          ● Recording…
        </Text>
      ) : null}
      <Pressable
        accessibilityRole="button"
        onPress={onPress}
        disabled={isProcessing}
        style={[
          styles.button,
          phase === 'recording' && styles.buttonRecording,
          isProcessing && styles.buttonDisabled,
        ]}
      >
        <Text style={styles.buttonText}>{label}</Text>
      </Pressable>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {notice ? <Text style={styles.notice}>{notice}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 20,
    backgroundColor: '#fff',
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: '#1b3a5b',
  },
  recording: {
    fontSize: 16,
    color: '#c0392b',
    fontWeight: '600',
  },
  button: {
    minWidth: 240,
    paddingVertical: 22,
    paddingHorizontal: 28,
    borderRadius: 16,
    backgroundColor: '#1b7f4b',
    alignItems: 'center',
  },
  buttonRecording: {
    backgroundColor: '#c0392b',
  },
  buttonDisabled: {
    backgroundColor: '#8a8f98',
  },
  buttonText: {
    color: '#fff',
    fontSize: 20,
    fontWeight: '700',
  },
  error: {
    color: '#c0392b',
    fontSize: 14,
    textAlign: 'center',
  },
  notice: {
    color: '#1b7f4b',
    fontSize: 14,
    textAlign: 'center',
  },
});
