import { router, Stack } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { RecorderScreen } from '../components/RecorderScreen';
import { useServices } from '../services/context';

/** Home route: one-tap exam capture, with History + Settings in the top nav bar. */
export default function RecorderRoute() {
  const { audioService, uploadRecording, settings } = useServices();

  return (
    <View style={styles.container}>
      {/* History and Settings live in the header so they're always one tap away at
          the top, rather than buried below the recorder. */}
      <Stack.Screen
        options={{
          title: '',
          headerLeft: () => (
            <Pressable
              accessibilityRole="button"
              hitSlop={8}
              style={styles.headerButton}
              onPress={() => router.push('/history')}
            >
              <Text style={styles.headerButtonText}>History</Text>
            </Pressable>
          ),
          headerRight: () => (
            <Pressable
              accessibilityRole="button"
              hitSlop={8}
              style={styles.headerButton}
              onPress={() => router.push('/settings')}
            >
              <Text style={styles.headerButtonText}>Settings</Text>
            </Pressable>
          ),
        }}
      />
      <RecorderScreen
        audioService={audioService}
        uploadRecording={uploadRecording}
        onRecorded={(exam) => router.push(`/exam/${exam.id}`)}
      />
      {/* Floated at the top as an overlay so it never shifts the recorder, which
          stays centered in the full screen whether or not this banner shows. */}
      {!settings.apiUrl ? (
        <View style={styles.banner} pointerEvents="none">
          <Text style={styles.notConfigured}>
            No backend set — open Settings to enter the clinic address.
          </Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  headerButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  headerButtonText: {
    color: '#1b3a5b',
    fontSize: 16,
    fontWeight: '600',
  },
  banner: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    paddingTop: 12,
    paddingHorizontal: 24,
  },
  notConfigured: {
    textAlign: 'center',
    color: '#c0392b',
    fontSize: 14,
  },
});
