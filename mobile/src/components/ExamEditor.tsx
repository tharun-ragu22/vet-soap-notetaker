import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import type { ApiClient } from '../services/api/ApiClient';
import type { Exam, SoapNote } from '../services/api/types';

export interface ExamEditorProps {
  exam: Exam;
  /**
   * Editing writes through updateExam; Inject uses requestInjection; Delete uses deleteExam;
   * Regenerate uses regenerateNote to re-run note generation from the edited transcript.
   */
  apiClient: Pick<
    ApiClient,
    'updateExam' | 'requestInjection' | 'deleteExam' | 'regenerateNote'
  >;
  /** Called with the persisted exam after a successful save. */
  onSaved?: (exam: Exam) => void;
  /** Called after the exam is deleted from the backend (e.g. to navigate away). */
  onDeleted?: () => void;
}

const SECTIONS: ReadonlyArray<readonly [keyof SoapNote, string]> = [
  ['subjective', 'Subjective'],
  ['objective', 'Objective'],
  ['assessment', 'Assessment'],
  ['plan', 'Plan'],
  ['transcript', 'Transcript'],
];

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';
type InjectStatus = 'idle' | 'sending' | 'sent' | 'error';
// Regeneration re-runs note generation over the (hand-corrected) transcript. It's
// non-destructive: the fresh note lands as an unsaved edit until the vet taps Save,
// mirroring the desktop History window.
type RegenStatus = 'idle' | 'regenerating' | 'done' | 'error';
// Deleting is destructive and irreversible, so it takes a confirming second tap
// (mirrors the desktop History window's confirmation dialog).
type DeleteStatus = 'idle' | 'confirm' | 'deleting' | 'error';

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * The inline SOAP editor (feature B) plus the remote AVImark trigger (feature C).
 *
 * Save writes the edited note through to the backend, which is the authoritative
 * record. "Inject into AVImark" asks the backend to have this exam's note pasted into
 * AVImark on the exam-room PC — the phone never talks to the desktop directly; the
 * desktop tray app polls for the request and does the paste (or shows its Safety
 * Flyout). It's a fire-and-forget request that returns as soon as it's queued.
 */
export function ExamEditor({ exam, apiClient, onSaved, onDeleted }: ExamEditorProps) {
  const [note, setNote] = useState<SoapNote>({
    subjective: exam.subjective,
    objective: exam.objective,
    assessment: exam.assessment,
    plan: exam.plan,
    transcript: exam.transcript,
  });
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [injectStatus, setInjectStatus] = useState<InjectStatus>('idle');
  const [injectError, setInjectError] = useState<string | null>(null);
  const [deleteStatus, setDeleteStatus] = useState<DeleteStatus>('idle');
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [regenStatus, setRegenStatus] = useState<RegenStatus>('idle');
  const [regenError, setRegenError] = useState<string | null>(null);

  const setField = (key: keyof SoapNote, value: string) => {
    setNote((current) => ({ ...current, [key]: value }));
    // Any edit invalidates a prior "Saved"/"Regenerated" confirmation.
    setSaveStatus('idle');
    setRegenStatus('idle');
  };

  const handleSave = async () => {
    setSaveStatus('saving');
    setSaveError(null);
    try {
      const updated = await apiClient.updateExam(exam.id, note);
      setSaveStatus('saved');
      onSaved?.(updated);
    } catch (e) {
      setSaveError(messageOf(e));
      setSaveStatus('error');
    }
  };

  const isDirty =
    note.subjective !== exam.subjective ||
    note.objective !== exam.objective ||
    note.assessment !== exam.assessment ||
    note.plan !== exam.plan ||
    note.transcript !== exam.transcript;

  const handleInject = async () => {
    setInjectStatus('sending');
    setInjectError(null);
    try {
      // Persist the current edits first so the desktop injects what the vet sees,
      // not the last-saved note -- no Save-first step. The backend builds the
      // injection from the stored exam, so the save must land before we ask for
      // it; if it fails we don't request an injection (that would paste a stale
      // note). Skip the write when nothing changed.
      if (isDirty) {
        const updated = await apiClient.updateExam(exam.id, note);
        setSaveStatus('saved');
        onSaved?.(updated);
      }
      await apiClient.requestInjection(exam.id);
      setInjectStatus('sent');
    } catch (e) {
      setInjectError(messageOf(e));
      setInjectStatus('error');
    }
  };

  const handleRegenerate = async () => {
    setRegenStatus('regenerating');
    setRegenError(null);
    try {
      const fresh = await apiClient.regenerateNote(note.transcript);
      // Merge the fresh S/O/A/P over the current note. regenerateNote echoes the
      // transcript back, so spreading keeps the vet's edited transcript intact. This
      // is an *unsaved* edit — nothing is persisted until the vet taps Save Changes.
      setNote((current) => ({ ...current, ...fresh }));
      setSaveStatus('idle');
      setRegenStatus('done');
    } catch (e) {
      setRegenError(messageOf(e));
      setRegenStatus('error');
    }
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
      await apiClient.deleteExam(exam.id);
      onDeleted?.();
    } catch (e) {
      setDeleteError(messageOf(e));
      setDeleteStatus('error');
    }
  };

  const regenLabel =
    regenStatus === 'regenerating' ? 'Regenerating…' : 'Regenerate from Transcript';
  const saveLabel = saveStatus === 'saving' ? 'Saving…' : 'Save Changes';
  const injectLabel = injectStatus === 'sending' ? 'Sending…' : 'Inject into AVImark';
  const deleteLabel =
    deleteStatus === 'deleting'
      ? 'Deleting…'
      : deleteStatus === 'confirm'
        ? 'Tap again to delete'
        : 'Delete Exam';

  return (
    // The SOAP fields are multiline, so Return inserts a newline rather than
    // closing the keyboard. Give the vet two easy ways out instead: swipe the
    // form down to dismiss (keyboardDismissMode), and let taps on the action
    // buttons go through on the first touch while the keyboard is up
    // (keyboardShouldPersistTaps) rather than being swallowed just to dismiss it.
    <ScrollView
      contentContainerStyle={styles.container}
      keyboardDismissMode="on-drag"
      keyboardShouldPersistTaps="handled"
    >
      {exam.patientName ? <Text style={styles.patient}>{exam.patientName}</Text> : null}

      {SECTIONS.map(([key, label]) => (
        <View key={key} style={styles.field}>
          <Text style={styles.label}>{label}</Text>
          <TextInput
            testID={`field-${key}`}
            style={styles.input}
            value={note[key]}
            onChangeText={(value) => setField(key, value)}
            multiline
          />
        </View>
      ))}

      <Pressable
        accessibilityRole="button"
        style={[styles.button, styles.regen, regenStatus === 'regenerating' && styles.busy]}
        onPress={handleRegenerate}
        disabled={regenStatus === 'regenerating'}
      >
        <Text style={styles.buttonText}>{regenLabel}</Text>
      </Pressable>
      {regenStatus === 'done' ? (
        <Text style={styles.ok}>Regenerated — review and Save to keep it.</Text>
      ) : null}
      {regenStatus === 'error' ? (
        <Text style={styles.error}>Regenerate failed: {regenError}</Text>
      ) : null}

      <Pressable
        accessibilityRole="button"
        style={[styles.button, styles.save, saveStatus === 'saving' && styles.busy]}
        onPress={handleSave}
        disabled={saveStatus === 'saving'}
      >
        <Text style={styles.buttonText}>{saveLabel}</Text>
      </Pressable>
      {saveStatus === 'saved' ? <Text style={styles.ok}>Saved ✓</Text> : null}
      {saveStatus === 'error' ? (
        <Text style={styles.error}>Save failed: {saveError}</Text>
      ) : null}

      <Pressable
        accessibilityRole="button"
        style={[styles.button, styles.inject, injectStatus === 'sending' && styles.busy]}
        onPress={handleInject}
        disabled={injectStatus === 'sending'}
      >
        <Text style={styles.buttonText}>{injectLabel}</Text>
      </Pressable>
      {injectStatus === 'sent' ? (
        <Text style={styles.ok}>Sent to the desktop — it will paste into AVImark.</Text>
      ) : null}
      {injectStatus === 'error' ? (
        <Text style={styles.error}>Injection request failed: {injectError}</Text>
      ) : null}

      <Pressable
        accessibilityRole="button"
        style={[styles.button, styles.delete, deleteStatus === 'deleting' && styles.busy]}
        onPress={handleDelete}
        disabled={deleteStatus === 'deleting'}
      >
        <Text style={styles.buttonText}>{deleteLabel}</Text>
      </Pressable>
      {deleteStatus === 'error' ? (
        <Text style={styles.error}>Delete failed: {deleteError}</Text>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: 16,
    gap: 14,
    backgroundColor: '#fff',
  },
  patient: {
    fontSize: 22,
    fontWeight: '700',
    color: '#1b3a5b',
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
    textAlignVertical: 'top',
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
