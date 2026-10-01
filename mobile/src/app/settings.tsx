import { router } from 'expo-router';

import { SettingsScreen } from '../components/SettingsScreen';
import { useServices } from '../services/context';

/** Settings route: edit the backend connection and apply it live, then pop back. */
export default function SettingsRoute() {
  const { settings, updateSettings } = useServices();

  return (
    <SettingsScreen
      settings={settings}
      onSave={updateSettings}
      onSaved={() => {
        if (router.canGoBack()) router.back();
      }}
    />
  );
}
