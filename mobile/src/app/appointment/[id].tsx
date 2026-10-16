import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { AppointmentScreen } from '../../components/AppointmentScreen';
import type { Appointment } from '../../services/api/types';
import { useServices } from '../../services/context';

/**
 * Appointment route: fetches the appointment by id from the synced backend and hands
 * it to the screen, which owns editing, regenerating, injecting and deleting; this
 * route is just the loader seam.
 */
export default function AppointmentRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { apiClient } = useServices();
  // Keyed by id rather than reset imperatively: a result for a stale id (e.g.
  // navigating straight from one appointment to another) is treated as still
  // loading instead of being flashed on screen, with no synchronous setState in the
  // effect body to reset it on every id change.
  const [result, setResult] = useState<{
    id: string;
    appointment: Appointment | null;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    let active = true;
    apiClient
      .getAppointment(id)
      .then((loaded) => {
        if (active) setResult({ id, appointment: loaded, error: null });
      })
      .catch(() => {
        if (active) setResult({ id, appointment: null, error: "Couldn't load this appointment." });
      });
    return () => {
      active = false;
    };
  }, [apiClient, id]);

  const current = result?.id === id ? result : null;
  const appointment = current?.appointment ?? null;
  const error = current?.error ?? null;

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>{error}</Text>
      </View>
    );
  }

  if (!appointment) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <>
      <Stack.Screen options={{ title: 'Appointment' }} />
      {/* Keyed so a different appointment starts from fresh draft state. After
          deletion the appointment no longer exists, so leave this screen. */}
      <AppointmentScreen
        key={appointment.id}
        appointment={appointment}
        apiClient={apiClient}
        onDeleted={() => router.back()}
      />
    </>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    backgroundColor: '#fff',
  },
  error: {
    color: '#c0392b',
    fontSize: 16,
    textAlign: 'center',
  },
});
