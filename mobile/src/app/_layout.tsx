import { Stack } from 'expo-router';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ServicesProvider } from '../services/context';

/**
 * Root navigator. Wraps the whole app in the ServicesProvider (so every screen can
 * reach the wired ApiClient/AudioService) and a Stack for push navigation between the
 * recorder, the history feed, and an appointment's notes. Routes are auto-discovered from the
 * files in this directory.
 */
export default function RootLayout() {
  return (
    <ServicesProvider>
      <SafeAreaProvider>
        <Stack>
          {/* The Outbox player: a sheet the vet swipes down to close. */}
          <Stack.Screen name="player" options={{ presentation: 'modal', headerShown: false }} />
        </Stack>
      </SafeAreaProvider>
    </ServicesProvider>
  );
}
