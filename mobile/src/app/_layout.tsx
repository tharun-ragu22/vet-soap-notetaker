import { router, Stack, usePathname } from 'expo-router';
import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context';

import { NoteToast } from '../components/NoteToast';
import { ServicesProvider, useServices } from '../services/context';

/** The "note ready" toast, over whichever screen is open. */
function NoteToastHost() {
  const { readyNotes, dismissReady } = useServices();
  const pathname = usePathname();
  const insets = useSafeAreaInsets();
  return (
    <NoteToast
      notes={readyNotes}
      currentPath={pathname}
      onOpen={(target) => router.push(target)}
      onDismiss={dismissReady}
      topInset={insets.top}
    />
  );
}

/**
 * Root navigator. Wraps the whole app in the ServicesProvider (so every screen can
 * reach the wired ApiClient/AudioService) and a Stack for push navigation between the
 * recorder, the history feed, and an appointment's notes. Routes are auto-discovered from the
 * files in this directory. The note toast sits above the Stack, so it shows on any screen.
 */
export default function RootLayout() {
  return (
    <ServicesProvider>
      <SafeAreaProvider>
        <Stack />
        <NoteToastHost />
      </SafeAreaProvider>
    </ServicesProvider>
  );
}
