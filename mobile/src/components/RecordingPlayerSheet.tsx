import { useRef, useState } from 'react';
import { type GestureResponderEvent, Pressable, StyleSheet, Text, View } from 'react-native';

import { formatClock, timeAt } from '../services/audio/scrub';
import type { Playback } from '../services/audio/types';

export interface RecordingPlayerSheetProps {
  /** When it was recorded. */
  title: string;
  /** The recorded length, shown until the player has loaded the real one. */
  durationMillis: number;
  /** Where the upload is up to (describeUpload's status). */
  statusText: string;
  /** The upload finished while the player was open; the player's copy still plays. */
  uploaded: boolean;
  /** The recording couldn't be opened. */
  error: boolean;
  playback: Playback;
}

/** VoiceOver's swipe up/down on the scrubber moves this far. */
const ADJUST_SECONDS = 15;
/** Close enough to the end that Play means "from the top". */
const END_SLACK_SECONDS = 0.25;

/**
 * The Outbox's player, shown as a sheet the vet swipes down to close: play/pause
 * and a scrubber to jump anywhere in the recording.
 */
export function RecordingPlayerSheet({
  title,
  durationMillis,
  statusText,
  uploaded,
  error,
  playback,
}: RecordingPlayerSheetProps) {
  const { status } = playback;
  const width = useRef(0);
  // Where the touch landed on the bar, and the finger's screen x then.
  const grab = useRef({ x: 0, pageX: 0 });
  // The seek still landing, so Play can wait for it.
  const seeking = useRef<Promise<void> | null>(null);
  // While a finger is on the scrubber the thumb follows it; the seek happens on release.
  const [dragTime, setDragTime] = useState<number | null>(null);
  // Where it was let go, shown until the player has got there.
  const [pendingTime, setPendingTime] = useState<number | null>(null);

  const duration = status.duration > 0 ? status.duration : durationMillis / 1000;
  const shown = Math.min(dragTime ?? pendingTime ?? status.currentTime, duration);
  const progress = duration > 0 ? shown / duration : 0;

  const seek = (seconds: number) => {
    setPendingTime(seconds);
    const landing = playback.seekTo(seconds);
    seeking.current = landing;
    void landing.finally(() => {
      if (seeking.current !== landing) return;
      seeking.current = null;
      setPendingTime(null);
    });
  };

  const toggle = () => {
    if (status.playing) {
      playback.pause();
      return;
    }
    const atEnd = shown >= duration - END_SLACK_SECONDS;
    const start = () => (atEnd ? playback.seekTo(0).then(() => playback.play()) : playback.play());
    if (seeking.current) void seeking.current.then(start);
    else void start();
  };

  // Measured from the finger's screen position, not locationX: iOS gives locationX
  // relative to whatever view is under the finger now, which jumps when it drifts off the bar.
  const timeUnder = (event: GestureResponderEvent) =>
    timeAt(grab.current.x + event.nativeEvent.pageX - grab.current.pageX, width.current, duration);

  const begin = (event: GestureResponderEvent) => {
    grab.current = { x: event.nativeEvent.locationX, pageX: event.nativeEvent.pageX };
    setDragTime(timeUnder(event));
  };

  const follow = (event: GestureResponderEvent) => setDragTime(timeUnder(event));

  const release = (event: GestureResponderEvent) => {
    setDragTime(null);
    seek(timeUnder(event));
  };

  const seekBy = (seconds: number) => seek(Math.min(Math.max(shown + seconds, 0), duration));

  return (
    <View style={styles.sheet}>
      <View style={styles.handle} />
      <Text style={styles.title}>{title}</Text>
      <Text style={[styles.status, uploaded && styles.uploaded]}>
        {uploaded ? "Uploaded — it's in Notes. You can keep listening until you close this." : statusText}
      </Text>

      {error ? (
        <Text style={styles.error}>This recording is no longer on the phone. If it uploaded, it&apos;s in Notes.</Text>
      ) : (
        <>
          <View
            testID="player-scrubber"
            style={styles.scrubber}
            accessible
            accessibilityRole="adjustable"
            accessibilityLabel="Position"
            accessibilityValue={{ text: `${formatClock(shown)} of ${formatClock(duration)}` }}
            accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
            onAccessibilityAction={(event) =>
              seekBy(event.nativeEvent.actionName === 'increment' ? ADJUST_SECONDS : -ADJUST_SECONDS)
            }
            onLayout={(event) => {
              width.current = event.nativeEvent.layout.width;
            }}
            onStartShouldSetResponder={() => true}
            onMoveShouldSetResponder={() => true}
            // Keep the drag rather than hand it to the sheet's swipe-down.
            onResponderTerminationRequest={() => false}
            onResponderGrant={begin}
            onResponderMove={follow}
            onResponderRelease={release}
          >
            {/* Not touchable, so locationX is always measured along the whole bar. */}
            <View pointerEvents="none" style={styles.track}>
              <View style={[styles.fill, { width: `${progress * 100}%` }]} />
            </View>
            <View pointerEvents="none" style={[styles.thumb, { left: `${progress * 100}%` }]} />
          </View>
          <View style={styles.times}>
            <Text testID="player-elapsed" style={styles.time}>
              {formatClock(shown)}
            </Text>
            <Text testID="player-total" style={styles.time}>
              {formatClock(duration)}
            </Text>
          </View>
          <Pressable
            testID="player-toggle"
            accessibilityRole="button"
            accessibilityLabel={status.playing ? 'Pause' : 'Play'}
            style={styles.toggle}
            onPress={toggle}
          >
            <Text style={styles.toggleText}>{status.playing ? '❚❚' : '▶'}</Text>
          </Pressable>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  sheet: {
    flex: 1,
    paddingHorizontal: 24,
    paddingTop: 12,
    backgroundColor: '#fff',
  },
  handle: {
    alignSelf: 'center',
    width: 40,
    height: 5,
    borderRadius: 3,
    backgroundColor: '#c7ccd1',
    marginBottom: 32,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: '#1b3a5b',
    textAlign: 'center',
  },
  status: {
    fontSize: 15,
    color: '#6b7480',
    textAlign: 'center',
    marginTop: 6,
  },
  uploaded: {
    color: '#1b7f4b',
  },
  error: {
    fontSize: 16,
    color: '#c0392b',
    textAlign: 'center',
    marginTop: 40,
  },
  scrubber: {
    height: 40,
    justifyContent: 'center',
    marginTop: 48,
  },
  track: {
    height: 4,
    borderRadius: 2,
    backgroundColor: '#dde2e7',
    overflow: 'hidden',
  },
  fill: {
    height: 4,
    backgroundColor: '#1b3a5b',
  },
  thumb: {
    position: 'absolute',
    width: 16,
    height: 16,
    marginLeft: -8,
    borderRadius: 8,
    backgroundColor: '#1b3a5b',
  },
  times: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  time: {
    fontSize: 13,
    color: '#6b7480',
    fontVariant: ['tabular-nums'],
  },
  toggle: {
    alignSelf: 'center',
    alignItems: 'center',
    justifyContent: 'center',
    width: 76,
    height: 76,
    borderRadius: 38,
    backgroundColor: '#1b3a5b',
    marginTop: 32,
  },
  toggleText: {
    color: '#fff',
    fontSize: 28,
  },
});
