import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { ExamEditor } from '../../components/ExamEditor';
import type { Exam } from '../../services/api/types';
import { useServices } from '../../services/context';

/**
 * Exam route: fetches the exam by id from the synced backend and hands it to the
 * editor. The editor owns the save + remote-inject behaviour; this route is just the
 * loader seam.
 */
export default function ExamRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { apiClient } = useServices();
  // Keyed by id rather than reset imperatively: a result for a stale id (e.g.
  // navigating straight from one exam to another) is treated as still loading
  // instead of being flashed on screen, with no synchronous setState in the
  // effect body to reset exam/error on every id change.
  const [result, setResult] = useState<{ id: string; exam: Exam | null; error: string | null } | null>(
    null,
  );

  useEffect(() => {
    let active = true;
    apiClient
      .getExam(id)
      .then((loaded) => {
        if (active) setResult({ id, exam: loaded, error: null });
      })
      .catch(() => {
        if (active) setResult({ id, exam: null, error: "Couldn't load this exam." });
      });
    return () => {
      active = false;
    };
  }, [apiClient, id]);

  const current = result?.id === id ? result : null;
  const exam = current?.exam ?? null;
  const error = current?.error ?? null;

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>{error}</Text>
      </View>
    );
  }

  if (!exam) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  // After deletion the exam no longer exists, so leave this screen.
  return <ExamEditor exam={exam} apiClient={apiClient} onDeleted={() => router.back()} />;
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
