import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import type { ApiClient } from "../services/api/ApiClient";
import type { Appointment } from "../services/api/types";

export interface HistoryScreenProps {
  /** Only the read surface is needed here; the backend is the source of truth. */
  apiClient: Pick<ApiClient, "fetchAppointments">;
  /** Called with the appointment id when a row is tapped (route pushes its screen). */
  onOpenAppointment?: (id: string) => void;
  /**
   * Bumped by the route each time the screen regains focus. A change triggers a
   * quiet background refetch, so an appointment deleted on its screen disappears
   * the moment the user returns here. The list stays mounted under the pushed
   * editor, so a plain mount effect would never re-run on the way back and the
   * stale (deleted) row would linger until the screen was left entirely. Left
   * undefined in unit tests, which render this screen with no navigator.
   */
  reloadSignal?: number;
}

type Status = "loading" | "ready" | "error";

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

/** The animals in an appointment, unnamed ones labelled by position ("Bella, Patient 2"). */
function animalNames(appointment: Appointment): string {
  return appointment.exams
    .map((exam, i) => exam.patientName || `Patient ${i + 1}`)
    .join(", ");
}

function hasNames(appointment: Appointment): boolean {
  return (
    appointment.exams.length > 1 || Boolean(appointment.exams[0]?.patientName)
  );
}

/**
 * Whether any animal in the appointment has a name containing the search, ignoring
 * case and surrounding spaces. An empty search matches everything; unnamed animals
 * ("Patient 2") have no name to match.
 */
function matchesPetName(appointment: Appointment, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return appointment.exams.some((exam) =>
    exam.patientName?.toLowerCase().includes(needle),
  );
}

function snippetOf(appointment: Appointment): string {
  if (appointment.notePending) return "Notes pending — still generating";
  const first = appointment.exams[0];
  return first?.assessment || first?.subjective || "No note yet";
}

/**
 * Feature B: the appointment history feed, synced across mobile and desktop via the
 * backend. One row per recording, naming every animal seen in it.
 * Loads on mount and exposes explicit loading / empty / error (with retry) states so a
 * transient backend hiccup never leaves a blank screen with no way forward.
 */
export function HistoryScreen({
  apiClient,
  onOpenAppointment,
  reloadSignal,
}: HistoryScreenProps) {
  const [status, setStatus] = useState<Status>("loading");
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  // Kept across the quiet refetch on return, so the filter still applies to the new list.
  const [query, setQuery] = useState("");

  useEffect(() => {
    // No list yet to fall back to, so a failed initial load must still show
    // the error screen. Inlined (rather than calling a shared async helper)
    // because react-hooks/set-state-in-effect flags *any* call in an effect
    // body to a named async function that eventually sets state, even from a
    // deferred .then()/.catch() -- an inline promise chain is the shape it
    // recognizes as deferred and leaves alone.
    let active = true;
    apiClient.fetchAppointments().then(
      (result) => {
        if (!active) return;
        setAppointments(result);
        setStatus("ready");
      },
      () => {
        if (active) setStatus("error");
      },
    );
    return () => {
      active = false;
    };
  }, [apiClient]);

  // Refetch quietly whenever the route reports the screen was re-focused (e.g. the
  // user came back after deleting an appointment). Skip the first run: the mount effect
  // above already did the initial load, so firing here too would double-fetch.
  const firstFocus = useRef(true);
  useEffect(() => {
    if (reloadSignal === undefined) return;
    if (firstFocus.current) {
      firstFocus.current = false;
      return;
    }
    let active = true;
    apiClient.fetchAppointments().then(
      (result) => {
        if (!active) return;
        setAppointments(result);
        setStatus("ready");
      },
      () => {
        // Don't let a failed background refresh wipe out a list we already have;
        // only surface the error screen when there's nothing to fall back to.
      },
    );
    return () => {
      active = false;
    };
  }, [reloadSignal, apiClient]);

  const retry = useCallback(() => {
    setStatus("loading");
    apiClient.fetchAppointments().then(
      (result) => {
        setAppointments(result);
        setStatus("ready");
      },
      () => setStatus("error"),
    );
  }, [apiClient]);

  if (status === "loading") {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
        <Text style={styles.muted}>Loading…</Text>
      </View>
    );
  }

  if (status === "error") {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>Couldn&apos;t load appointments.</Text>
        <Pressable
          accessibilityRole="button"
          style={styles.retry}
          onPress={retry}
        >
          <Text style={styles.retryText}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  if (appointments.length === 0) {
    return (
      <View style={styles.center}>
        <Text style={styles.muted}>No appointments yet.</Text>
      </View>
    );
  }

  return (
    <View style={styles.screen}>
      <TextInput
        style={styles.search}
        placeholder="Search by pet name"
        accessibilityLabel="Search by pet name"
        value={query}
        onChangeText={setQuery}
        autoCorrect={false}
        autoCapitalize="none"
        clearButtonMode="while-editing"
      />
      <FlatList
        data={appointments.filter((appointment) =>
          matchesPetName(appointment, query),
        )}
        keyExtractor={(appointment) => appointment.id}
        contentContainerStyle={styles.list}
        keyboardShouldPersistTaps="handled"
        ListEmptyComponent={
          <Text style={[styles.muted, styles.noMatches]}>
            No appointments for &quot;{query.trim()}&quot;.
          </Text>
        }
        renderItem={({ item }) => (
          <Pressable
            testID={`appointment-row-${item.id}`}
            accessibilityRole="button"
            style={styles.row}
            onPress={() => onOpenAppointment?.(item.id)}
          >
            {/* A lone animal with no name falls back to the creation date as the
              heading rather than a useless "Patient 1". */}
            <Text style={styles.patient}>
              {hasNames(item) ? animalNames(item) : formatDate(item.createdAt)}
            </Text>
            {/* Only show the date as a subtitle when it isn't already the heading. */}
            {hasNames(item) ? (
              <Text style={styles.date}>
                {formatDate(item.createdAt)}
                {item.exams.length > 1 ? ` · ${item.exams.length} animals` : ""}
              </Text>
            ) : null}
            <Text style={styles.snippet} numberOfLines={2}>
              {snippetOf(item)}
            </Text>
          </Pressable>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: "#fff",
  },
  search: {
    marginHorizontal: 12,
    marginTop: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 10,
    backgroundColor: "#f2f5f8",
    fontSize: 16,
    color: "#1b3a5b",
  },
  noMatches: {
    textAlign: "center",
    marginTop: 24,
  },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    padding: 24,
    backgroundColor: "#fff",
  },
  list: {
    padding: 12,
    gap: 10,
  },
  row: {
    padding: 16,
    borderRadius: 12,
    backgroundColor: "#f2f5f8",
    gap: 4,
  },
  patient: {
    fontSize: 18,
    fontWeight: "700",
    color: "#1b3a5b",
  },
  date: {
    fontSize: 12,
    color: "#6b7480",
  },
  snippet: {
    fontSize: 14,
    color: "#333",
  },
  muted: {
    fontSize: 16,
    color: "#6b7480",
  },
  error: {
    fontSize: 16,
    color: "#c0392b",
    textAlign: "center",
  },
  retry: {
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderRadius: 10,
    backgroundColor: "#1b7f4b",
  },
  retryText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "700",
  },
});
