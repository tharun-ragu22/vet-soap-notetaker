import { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { AudioService } from '../services/audio/AudioService';
import { expoKeepAwake } from '../services/audio/expoKeepAwake';
import type { KeepAwake, RecordingResult } from '../services/audio/types';
import type { Appointment } from '../services/api/types';

export interface RecorderScreenProps {
  /** The capture state machine (idle → recording → processing → idle). */
  audioService: AudioService;
  /**
   * Durably queue the finished recording and attempt it immediately. Resolves to the
   * appointment if it uploaded right away — finished (an older, synchronous backend)
   * or still `processing` on the backend (async: the outcome is announced later) —
   * or null if it's still queued for background retry.
   */
  enqueueRecording: (result: RecordingResult) => Promise<Appointment | null>;
  /**
   * Called when the upload came back with the notes already generated (an older,
   * synchronous backend). An async upload's notes are announced by the app's toast.
   */
  onRecorded?: (appointment: Appointment) => void;
  /**
   * Holds the display awake while recording. Injectable for tests; defaults to the
   * real expo-keep-awake wrapper.
   */
  keepAwake?: KeepAwake;
  /**
   * Whether any recording is still waiting on the phone. The "uploading in the
   * background" notice only shows while one is. Defaults to true.
   */
  hasPendingUploads?: boolean;
}

type Phase = 'idle' | 'recording' | 'processing';

/** `queued`: still on the phone, cleared once nothing is; `uploaded`: on the backend. */
type Notice = { kind: 'queued' | 'uploaded'; text: string };

const UPLOADED = "Uploaded — you'll see a notice here when the note is ready.";

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Feature A: one-tap exam audio capture. A single big control drives the whole
 * lifecycle — tap to start, tap to stop-and-upload — and every failure path returns
 * the button to idle so it can never become a silent no-op (the desktop Pipeline's
 * hard rule, mirrored here through AudioService).
 */
export function RecorderScreen({
  audioService,
  enqueueRecording,
  onRecorded,
  keepAwake = expoKeepAwake,
  hasPendingUploads = true,
}: RecorderScreenProps) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  // The queued notice says a recording is waiting; once none is (it uploaded later,
  // or the vet discarded it, even mid-upload before this Stop returned), clear it.
  // Done during render, React's pattern for state that follows a prop.
  if (notice?.kind === 'queued' && !hasPendingUploads) setNotice(null);

  // Keep the display on only while actively recording (not idle, and not during the
  // brief upload — the durable queue survives a sleep/lock, so there's no reason to
  // burn battery then). The cleanup releases the lock on Stop and on unmount, so
  // navigating away mid-recording can't leave the screen stuck awake.
  useEffect(() => {
    if (phase !== 'recording') return;
    keepAwake.activate();
    return () => keepAwake.deactivate();
  }, [phase, keepAwake]);

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
      const appointment = await enqueueRecording(result);
      if (appointment?.status === 'complete' || appointment?.status === 'note_pending') {
        onRecorded?.(appointment);
      } else if (appointment) {
        // The backend has it and is processing it; the toast says when it's done.
        setNotice({ kind: 'uploaded', text: UPLOADED });
      } else {
        // Saved durably but not uploaded yet — the queue will keep retrying.
        setNotice({ kind: 'queued', text: 'Saved — uploading in the background.' });
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
      {notice ? <Text style={styles.notice}>{notice.text}</Text> : null}
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
