import { useEffect, useMemo } from 'react';
import { Pressable, StyleSheet, Text } from 'react-native';

import type { ReadyNote } from '../services/events/appointmentWatcher';
import { readyToast } from '../services/events/readyToast';

export interface NoteToastProps {
  /** Recordings that finished processing since the toast was last dismissed. */
  notes: ReadyNote[];
  /** The route on screen now: a note for the appointment being viewed isn't announced. */
  currentPath: string;
  /** Go to the toast's target (the appointment, or Notes for several). */
  onOpen: (target: string) => void;
  onDismiss: () => void;
  /** Space to leave for the status bar / notch. */
  topInset?: number;
  autoHideMs?: number;
}

/**
 * The in-app "note ready" message, rendered once at the root so it shows over
 * whatever screen is open. Tapping it opens the note; it hides itself after a few
 * seconds (the note stays in Notes either way). The app uses this instead of push
 * notifications, so nothing leaves the clinic network.
 */
export function NoteToast({
  notes,
  currentPath,
  onOpen,
  onDismiss,
  topInset = 0,
  autoHideMs = 6000,
}: NoteToastProps) {
  const shown = useMemo(
    () => notes.filter((n) => currentPath !== `/appointment/${n.appointmentId}`),
    [notes, currentPath],
  );
  const toast = readyToast(shown);

  // Everything ready is already on screen: nothing to announce.
  const allOnScreen = notes.length > 0 && shown.length === 0;
  useEffect(() => {
    if (allOnScreen) onDismiss();
  }, [allOnScreen, onDismiss]);

  // Restarts whenever another recording finishes, so the newest gets its full time.
  useEffect(() => {
    if (shown.length === 0) return;
    const timer = setTimeout(onDismiss, autoHideMs);
    return () => clearTimeout(timer);
  }, [shown, autoHideMs, onDismiss]);

  if (!toast) return null;
  const warning = toast.tone === 'warning';
  return (
    <Pressable
      testID="note-toast"
      accessibilityRole="button"
      accessibilityLabel={`${toast.text}. View`}
      accessibilityHint={warning ? 'Warning — opens the recording' : 'Opens the note'}
      accessibilityLiveRegion="polite"
      onPress={() => {
        onOpen(toast.target);
        onDismiss();
      }}
      style={[styles.toast, { top: topInset + 8 }, warning ? styles.warning : styles.success]}
    >
      <Text style={styles.icon}>{warning ? '!' : '✓'}</Text>
      <Text style={styles.text}>{toast.text}</Text>
      <Text style={styles.view}>View ›</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  toast: {
    position: 'absolute',
    left: 16,
    right: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
    shadowColor: '#000',
    shadowOpacity: 0.15,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 4,
  },
  success: {
    backgroundColor: '#1f6f43',
  },
  warning: {
    backgroundColor: '#a5512a',
  },
  icon: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  text: {
    flex: 1,
    color: '#fff',
    fontSize: 15,
    fontWeight: '600',
  },
  view: {
    color: '#fff',
    fontSize: 15,
  },
});
