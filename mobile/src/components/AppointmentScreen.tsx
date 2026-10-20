import { useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import type { ApiClient } from '../services/api/ApiClient';
import type { Appointment, AppointmentDraft, ExamDraft, SoapFields } from '../services/api/types';
import { mergeRegenerated } from '../services/appointments/mergeRegenerated';

/** How often a pending appointment is re-fetched, to pick up notes the upload queue finished. */
export const DEFAULT_PENDING_POLL_MS = 15_000;

export interface AppointmentScreenProps {
  appointment: Appointment;
  apiClient: Pick<
    ApiClient,
    | 'updateAppointment'
    | 'regenerateAppointment'
    | 'deleteAppointment'
    | 'requestInjection'
    | 'completeAppointment'
    | 'getAppointment'
    | 'retryAppointment'
  >;
  /** Called after the appointment is deleted from the backend (e.g. to navigate away). */
  onDeleted?: () => void;
  /** Re-fetch interval while the notes are pending; 0 turns polling off. */
  pendingPollMs?: number;
}

/** One animal being edited. `key` is stable across edits; `id` is unset for an unsaved animal. */
type Card = ExamDraft & { key: string };

const SECTIONS: readonly (readonly [keyof SoapFields, string])[] = [
  ['subjective', 'Subjective'],
  ['objective', 'Objective'],
  ['assessment', 'Assessment'],
  ['plan', 'Plan'],
];

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';
// Regeneration re-runs note generation over the (hand-corrected) transcript. It's
// non-destructive: the fresh notes land as unsaved edits until the vet taps Save.
type RegenStatus = 'idle' | 'regenerating' | 'done' | 'error';
// Deleting is destructive and irreversible, so it takes a confirming second tap.
type DeleteStatus = 'idle' | 'confirm' | 'deleting' | 'error';
type GenerateStatus = 'idle' | 'generating' | 'error';
type RetryStatus = 'idle' | 'retrying' | 'error';
interface InjectState {
  index: number;
  status: 'sending' | 'sent' | 'error';
  error?: string;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function cardsOf(appointment: Appointment): Card[] {
  return appointment.exams.map((exam) => ({
    key: exam.id,
    id: exam.id,
    patientName: exam.patientName,
    subjective: exam.subjective,
    objective: exam.objective,
    assessment: exam.assessment,
    plan: exam.plan,
  }));
}

function draftOf(transcript: string, cards: Card[]): AppointmentDraft {
  return {
    transcript,
    exams: cards.map(({ id, patientName, subjective, objective, assessment, plan }) => ({
      id,
      patientName: patientName?.trim() || undefined,
      subjective,
      objective,
      assessment,
      plan,
    })),
  };
}

/**
 * One appointment (recording): the shared transcript and a card per animal, each
 * injectable into its own AVImark chart.
 *
 * Every edit — the transcript, a note, a name, removing an animal, a regenerate — is
 * a local draft until Save, which writes the whole appointment back in one request.
 * "Inject into AVImark" on an animal's card saves the draft first when it's changed,
 * so the desktop pastes exactly what the vet sees; the phone never talks to the
 * desktop directly — the backend queues the request and the tray app does the paste.
 *
 * While the notes are still generating (the upload got a 202), there's nothing to
 * edit yet: the screen shows the transcript, offers "Generate notes now", and polls
 * for the notes the background upload queue may finish first. Editing is held back
 * until then, because saving a draft while the backend adds the animals would
 * delete them.
 */
export function AppointmentScreen({
  appointment,
  apiClient,
  onDeleted,
  pendingPollMs = DEFAULT_PENDING_POLL_MS,
}: AppointmentScreenProps) {
  const [saved, setSaved] = useState(appointment);
  const [transcript, setTranscript] = useState(appointment.transcript);
  const [cards, setCards] = useState<Card[]>(() => cardsOf(appointment));
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [regenStatus, setRegenStatus] = useState<RegenStatus>('idle');
  const [regenError, setRegenError] = useState<string | null>(null);
  const [deleteStatus, setDeleteStatus] = useState<DeleteStatus>('idle');
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [generateStatus, setGenerateStatus] = useState<GenerateStatus>('idle');
  const [retryStatus, setRetryStatus] = useState<RetryStatus>('idle');
  const [retryError, setRetryError] = useState<string | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [inject, setInject] = useState<InjectState | null>(null);
  const [removeArmed, setRemoveArmed] = useState<string | null>(null);
  // Collapsed cards, by stable card key so the state follows the animal when another
  // is removed. Collapsing only hides the fields: the draft and Inject are unaffected.
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set());
  const newKeys = useRef(0);

  const load = (next: Appointment) => {
    setSaved(next);
    setTranscript(next.transcript);
    setCards(cardsOf(next));
  };

  // Poll a pending appointment until its notes exist (the upload queue keeps
  // retrying in the background, and the desktop or another phone may finish it).
  // (A processing async upload holds a note-pending placeholder too, so it's polled
  // the same way while this screen is open.)
  const pending = saved.notePending;
  useEffect(() => {
    if (!pending || pendingPollMs <= 0) return;
    let active = true;
    let inFlight = false;
    const timer = setInterval(() => {
      if (inFlight) return;
      inFlight = true;
      apiClient.getAppointment(saved.id).then(
        (next) => {
          inFlight = false;
          if (active && !next.notePending) load(next);
        },
        () => {
          // Transient: try again on the next tick.
          inFlight = false;
        },
      );
    }, pendingPollMs);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [pending, pendingPollMs, apiClient, saved.id]);

  const draft = draftOf(transcript, cards);
  const isDirty =
    JSON.stringify(draft) !== JSON.stringify(draftOf(saved.transcript, cardsOf(saved)));

  const edited = () => {
    // Any edit invalidates a prior "Saved"/"Regenerated" confirmation.
    setSaveStatus('idle');
    setRegenStatus('idle');
  };

  const setCardField = (index: number, field: keyof SoapFields | 'patientName', value: string) => {
    setCards((current) => current.map((card, i) => (i === index ? { ...card, [field]: value } : card)));
    edited();
  };

  const save = async (): Promise<Appointment> => {
    const updated = await apiClient.updateAppointment(saved.id, draft);
    load(updated);
    return updated;
  };

  const handleSave = async () => {
    setSaveStatus('saving');
    setSaveError(null);
    try {
      await save();
      setSaveStatus('saved');
    } catch (e) {
      setSaveError(messageOf(e));
      setSaveStatus('error');
    }
  };

  const handleRegenerate = async () => {
    setRegenStatus('regenerating');
    setRegenError(null);
    try {
      const { patients } = await apiClient.regenerateAppointment(transcript, saved.id);
      setCards((current) =>
        mergeRegenerated(current, patients).map((exam) => ({
          ...exam,
          key: (exam as Partial<Card>).key ?? exam.id ?? `new-${(newKeys.current += 1)}`,
        })),
      );
      setSaveStatus('idle');
      setRegenStatus('done');
    } catch (e) {
      setRegenError(messageOf(e));
      setRegenStatus('error');
    }
  };

  const handleInject = async (index: number) => {
    setInject({ index, status: 'sending' });
    try {
      let examId = cards[index].id;
      // Persist the draft first so the desktop injects what the vet sees (the
      // backend builds the paste from the stored exam). An animal that's never been
      // saved has no id until then. If the save fails, don't inject a stale note.
      if (isDirty || !examId) {
        const updated = await save();
        setSaveStatus('saved');
        examId = updated.exams[index].id;
      }
      await apiClient.requestInjection(examId);
      setInject({ index, status: 'sent' });
    } catch (e) {
      setInject({ index, status: 'error', error: messageOf(e) });
    }
  };

  const toggleCollapsed = (key: string) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  };

  const handleRemove = (card: Card) => {
    if (removeArmed !== card.key) {
      setRemoveArmed(card.key);
      return;
    }
    setRemoveArmed(null);
    setInject(null);
    setCards((current) => current.filter((c) => c.key !== card.key));
    edited();
  };

  const handleDelete = async () => {
    // First tap arms the confirmation; the second tap actually deletes.
    if (deleteStatus === 'idle' || deleteStatus === 'error') {
      setDeleteError(null);
      setDeleteStatus('confirm');
      return;
    }
    if (deleteStatus !== 'confirm') return;
    setDeleteStatus('deleting');
    try {
      await apiClient.deleteAppointment(saved.id);
      onDeleted?.();
    } catch (e) {
      setDeleteError(messageOf(e));
      setDeleteStatus('error');
    }
  };

  const handleRetry = async () => {
    setRetryStatus('retrying');
    setRetryError(null);
    try {
      load(await apiClient.retryAppointment(saved.id));
      setRetryStatus('idle');
    } catch (e) {
      setRetryError(messageOf(e));
      setRetryStatus('error');
    }
  };

  const handleGenerate = async () => {
    setGenerateStatus('generating');
    setGenerateError(null);
    try {
      load(await apiClient.completeAppointment(saved.id));
      setGenerateStatus('idle');
    } catch (e) {
      setGenerateError(messageOf(e));
      setGenerateStatus('error');
    }
  };

  const deleteLabel =
    deleteStatus === 'deleting'
      ? 'Deleting…'
      : deleteStatus === 'confirm'
        ? 'Tap again to delete'
        : 'Delete Appointment';
  const deleteButton = (
    <>
      <Pressable
        accessibilityRole="button"
        style={[styles.button, styles.delete, deleteStatus === 'deleting' && styles.busy]}
        onPress={handleDelete}
        disabled={deleteStatus === 'deleting'}
      >
        <Text style={styles.buttonText}>{deleteLabel}</Text>
      </Pressable>
      {deleteStatus === 'error' ? <Text style={styles.error}>Delete failed: {deleteError}</Text> : null}
    </>
  );

  // An async upload with no transcript yet: nothing to show but where it's up to.
  if (saved.status === 'processing' || saved.status === 'failed' || saved.status === 'no_speech') {
    return (
      <ScrollView contentContainerStyle={styles.container}>
        {saved.status === 'processing' ? (
          <Text style={styles.notice}>
            Processing on the computer — the notes will appear here when they&apos;re ready.
          </Text>
        ) : saved.status === 'no_speech' ? (
          <Text style={styles.notice}>
            No speech was heard in this recording. Check the microphone wasn&apos;t covered or muted.
          </Text>
        ) : (
          <>
            <Text style={styles.notice}>
              Couldn&apos;t transcribe this recording. The audio is saved on the computer, so it can be
              tried again.
            </Text>
            <Pressable
              accessibilityRole="button"
              style={[styles.button, styles.regen, retryStatus === 'retrying' && styles.busy]}
              onPress={handleRetry}
              disabled={retryStatus === 'retrying'}
            >
              <Text style={styles.buttonText}>{retryStatus === 'retrying' ? 'Retrying…' : 'Retry'}</Text>
            </Pressable>
            {retryStatus === 'error' ? <Text style={styles.error}>Retry failed: {retryError}</Text> : null}
          </>
        )}
        {deleteButton}
      </ScrollView>
    );
  }

  if (pending) {
    return (
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.notice}>
          The notes are still being generated. They&apos;ll appear here when they&apos;re ready.
        </Text>
        <Pressable
          accessibilityRole="button"
          style={[styles.button, styles.regen, generateStatus === 'generating' && styles.busy]}
          onPress={handleGenerate}
          disabled={generateStatus === 'generating'}
        >
          <Text style={styles.buttonText}>
            {generateStatus === 'generating' ? 'Generating…' : 'Generate notes now'}
          </Text>
        </Pressable>
        {generateStatus === 'error' ? (
          <Text style={styles.error}>Couldn&apos;t generate the notes: {generateError}</Text>
        ) : null}
        <View style={styles.field}>
          <Text style={styles.label}>Transcript</Text>
          <Text style={styles.readOnly}>{saved.transcript}</Text>
        </View>
        {deleteButton}
      </ScrollView>
    );
  }

  return (
    // The fields are multiline, so Return inserts a newline rather than closing the
    // keyboard. Swipe the form down to dismiss it (keyboardDismissMode), and taps on
    // buttons go through on the first touch while it's up (keyboardShouldPersistTaps).
    <ScrollView
      contentContainerStyle={styles.container}
      keyboardDismissMode="on-drag"
      keyboardShouldPersistTaps="handled"
    >
      {cards.map((card, index) => {
        const label = card.patientName?.trim() || `Patient ${index + 1}`;
        const expanded = !collapsed.has(card.key);
        return (
          <View key={card.key} style={styles.card}>
            <View style={styles.cardHeader}>
              <Pressable
                testID={`toggle-${index}`}
                accessibilityRole="button"
                accessibilityState={{ expanded }}
                accessibilityLabel={`${expanded ? 'Collapse' : 'Expand'} ${label}`}
                style={styles.toggle}
                onPress={() => toggleCollapsed(card.key)}
              >
                <Text style={styles.patient}>{label}</Text>
                <Text style={styles.chevron}>{expanded ? '▾' : '▸'}</Text>
              </Pressable>
              {cards.length > 1 ? (
                <Pressable
                  testID={`remove-${index}`}
                  accessibilityRole="button"
                  accessibilityLabel={`Remove ${card.patientName || `Patient ${index + 1}`}`}
                  onPress={() => handleRemove(card)}
                >
                  <Text style={styles.remove}>
                    {removeArmed === card.key ? 'Tap again to remove' : 'Remove'}
                  </Text>
                </Pressable>
              ) : null}
            </View>
            {expanded ? (
              <>
                <View style={styles.field}>
                  <Text style={styles.label}>Patient name</Text>
                  <TextInput
                    testID={`name-${index}`}
                    style={styles.input}
                    value={card.patientName ?? ''}
                    placeholder={`Patient ${index + 1}`}
                    onChangeText={(value) => setCardField(index, 'patientName', value)}
                  />
                </View>
                {SECTIONS.map(([field, label]) => (
                  <View key={field} style={styles.field}>
                    <Text style={styles.label}>{label}</Text>
                    <TextInput
                      testID={`field-${index}-${field}`}
                      style={styles.input}
                      value={card[field]}
                      onChangeText={(value) => setCardField(index, field, value)}
                      multiline
                    />
                  </View>
                ))}
              </>
            ) : null}
            <Pressable
              testID={`inject-${index}`}
              accessibilityRole="button"
              style={[
                styles.button,
                styles.inject,
                inject?.index === index && inject.status === 'sending' && styles.busy,
              ]}
              onPress={() => handleInject(index)}
              disabled={inject?.status === 'sending'}
            >
              <Text style={styles.buttonText}>
                {inject?.index === index && inject.status === 'sending' ? 'Sending…' : 'Inject into AVImark'}
              </Text>
            </Pressable>
            {inject?.index === index && inject.status === 'sent' ? (
              <Text style={styles.ok}>Sent to the desktop — it will paste into AVImark.</Text>
            ) : null}
            {inject?.index === index && inject.status === 'error' ? (
              <Text style={styles.error}>Injection request failed: {inject.error}</Text>
            ) : null}
          </View>
        );
      })}

      <View style={styles.field}>
        <Text style={styles.label}>Transcript (shared by every animal)</Text>
        <TextInput
          testID="field-transcript"
          style={styles.input}
          value={transcript}
          onChangeText={(value) => {
            setTranscript(value);
            edited();
          }}
          multiline
        />
      </View>

      <Pressable
        accessibilityRole="button"
        style={[styles.button, styles.regen, regenStatus === 'regenerating' && styles.busy]}
        onPress={handleRegenerate}
        disabled={regenStatus === 'regenerating'}
      >
        <Text style={styles.buttonText}>
          {regenStatus === 'regenerating' ? 'Regenerating…' : 'Regenerate from Transcript'}
        </Text>
      </Pressable>
      {regenStatus === 'done' ? (
        <Text style={styles.ok}>Regenerated — review and Save to keep it.</Text>
      ) : null}
      {regenStatus === 'error' ? <Text style={styles.error}>Regenerate failed: {regenError}</Text> : null}

      <Pressable
        accessibilityRole="button"
        style={[styles.button, styles.save, saveStatus === 'saving' && styles.busy]}
        onPress={handleSave}
        disabled={saveStatus === 'saving'}
      >
        <Text style={styles.buttonText}>{saveStatus === 'saving' ? 'Saving…' : 'Save Changes'}</Text>
      </Pressable>
      {saveStatus === 'saved' ? <Text style={styles.ok}>Saved ✓</Text> : null}
      {saveStatus === 'error' ? <Text style={styles.error}>Save failed: {saveError}</Text> : null}

      {deleteButton}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: 16,
    gap: 14,
    backgroundColor: '#fff',
  },
  card: {
    gap: 10,
    padding: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#dde3ea',
    backgroundColor: '#f7f9fb',
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  toggle: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flexShrink: 1,
  },
  chevron: {
    fontSize: 18,
    color: '#6b7480',
  },
  patient: {
    fontSize: 22,
    fontWeight: '700',
    color: '#1b3a5b',
    flexShrink: 1,
  },
  remove: {
    color: '#c0392b',
    fontSize: 14,
    fontWeight: '600',
    padding: 8,
  },
  field: {
    gap: 4,
  },
  label: {
    fontSize: 13,
    fontWeight: '700',
    color: '#6b7480',
    textTransform: 'uppercase',
  },
  input: {
    minHeight: 44,
    borderWidth: 1,
    borderColor: '#ccd4dc',
    borderRadius: 8,
    padding: 10,
    fontSize: 15,
    color: '#1a1a1a',
    backgroundColor: '#fff',
    textAlignVertical: 'top',
  },
  readOnly: {
    fontSize: 15,
    color: '#1a1a1a',
  },
  notice: {
    fontSize: 16,
    color: '#1b3a5b',
    textAlign: 'center',
  },
  button: {
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  regen: {
    backgroundColor: '#5b3a8c',
  },
  save: {
    backgroundColor: '#1b3a5b',
  },
  inject: {
    backgroundColor: '#1b7f4b',
  },
  delete: {
    backgroundColor: '#c0392b',
  },
  busy: {
    opacity: 0.6,
  },
  buttonText: {
    color: '#fff',
    fontSize: 17,
    fontWeight: '700',
  },
  ok: {
    color: '#1b7f4b',
    fontSize: 14,
    fontWeight: '600',
    textAlign: 'center',
  },
  error: {
    color: '#c0392b',
    fontSize: 14,
    textAlign: 'center',
  },
});
