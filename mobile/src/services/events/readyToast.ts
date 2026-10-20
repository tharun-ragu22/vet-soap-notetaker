import type { ReadyNote } from './appointmentWatcher';

export interface ReadyToast {
  text: string;
  /** `warning` when any recording didn't produce its notes. */
  tone: 'success' | 'warning';
  /** Where tapping it goes: the appointment, or Notes for several. */
  target: string;
}

/** "Bella", "Bella and Max", "Bella, Max and Luna". */
function joinNames(names: string[]): string {
  if (names.length <= 1) return names.join('');
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

function succeeded(names: string[]): string {
  if (names.length === 0) return 'Note succeeded';
  return `${names.length === 1 ? 'Note' : 'Notes'} for ${joinNames(names)} succeeded`;
}

function warning(note: ReadyNote): string {
  return note.status === 'no_speech' ? 'No speech heard in the recording' : "Couldn't generate the note";
}

/** What the in-app toast says for the recordings that just finished processing. */
export function readyToast(notes: ReadyNote[]): ReadyToast | null {
  if (notes.length === 0) return null;
  if (notes.length === 1) {
    const [note] = notes;
    const ok = note.status === 'complete';
    return {
      text: ok ? succeeded(note.patientNames) : warning(note),
      tone: ok ? 'success' : 'warning',
      target: `/appointment/${note.appointmentId}`,
    };
  }
  const failed = notes.filter((n) => n.status !== 'complete').length;
  if (failed > 0) {
    return {
      text: `${notes.length} recordings finished — ${failed} ${failed === 1 ? 'needs' : 'need'} attention`,
      tone: 'warning',
      target: '/history',
    };
  }
  const names = notes.flatMap((n) => n.patientNames);
  return {
    text: names.length > 0 ? succeeded(names) : `${notes.length} notes succeeded`,
    tone: 'success',
    target: '/history',
  };
}
