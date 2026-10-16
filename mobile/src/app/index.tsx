import { router, Stack } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { AppMenu } from '../components/AppMenu';
import { RecorderScreen } from '../components/RecorderScreen';
import { useServices } from '../services/context';
import { uploadBanner } from '../services/upload/uploadBanner';

/** Home route: one-tap exam capture, with History, Uploads and Settings in the ☰ menu. */
export default function RecorderRoute() {
  const { audioService, enqueueRecording, uploads, settings } = useServices();
  const banner = uploadBanner(uploads);

  return (
    <View style={styles.container}>
      {/* The menu lives in the header so History, Uploads and Settings are always one
          tap away at the top, rather than buried below the recorder. */}
      <Stack.Screen
        options={{
          title: '',
          headerLeft: () => <AppMenu uploads={uploads} onNavigate={(path) => router.push(path)} />,
        }}
      />
      <RecorderScreen
        audioService={audioService}
        enqueueRecording={enqueueRecording}
        onRecorded={(appointment) => router.push(`/appointment/${appointment.id}`)}
      />
      {/* Floated at the top as an overlay so it never shifts the recorder, which
          stays centered in the full screen whether or not this banner shows. */}
      {!settings.apiUrl ? (
        <View style={styles.banner} pointerEvents="none">
          <Text style={styles.notConfigured}>
            No backend set — open Settings to enter the clinic address.
          </Text>
        </View>
      ) : banner ? (
        <Pressable
          accessibilityRole="button"
          style={styles.banner}
          onPress={() => router.push('/uploads')}
        >
          <Text style={banner.failed ? styles.notConfigured : styles.pending}>{banner.text}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
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
  pending: {
    textAlign: 'center',
    color: '#8a6d1b',
    fontSize: 14,
  },
});
