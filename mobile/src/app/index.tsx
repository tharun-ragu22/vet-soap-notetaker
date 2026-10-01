import { router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { RecorderScreen } from '../components/RecorderScreen';
import { useServices } from '../services/context';

/** Home route: one-tap exam capture, with a link into the synced history feed. */
export default function RecorderRoute() {
  const { audioService, uploadRecording, settings } = useServices();

  return (
    <View style={styles.container}>
      <RecorderScreen
        audioService={audioService}
        uploadRecording={uploadRecording}
        onRecorded={(exam) => router.push(`/exam/${exam.id}`)}
      />
      {!settings.apiUrl ? (
        <Text style={styles.notConfigured}>
          No backend set — open Settings to enter the clinic address.
        </Text>
      ) : null}
      <Pressable
        accessibilityRole="button"
        style={styles.link}
        onPress={() => router.push('/history')}
      >
        <Text style={styles.linkText}>View Exam History</Text>
      </Pressable>
      <Pressable
        accessibilityRole="button"
        style={styles.link}
        onPress={() => router.push('/settings')}
      >
        <Text style={styles.linkText}>Settings</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  notConfigured: {
    textAlign: 'center',
    color: '#c0392b',
    fontSize: 14,
    paddingHorizontal: 24,
    paddingTop: 8,
  },
  link: {
    alignItems: 'center',
    paddingVertical: 14,
  },
  linkText: {
    color: '#1b3a5b',
    fontSize: 16,
    fontWeight: '600',
  },
});
