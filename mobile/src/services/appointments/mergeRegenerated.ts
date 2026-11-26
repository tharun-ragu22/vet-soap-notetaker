import type { ExamDraft, PatientNote } from '../api/types';

function key(name: string | undefined): string {
  return (name ?? '').trim().toLowerCase();
}

/**
 * Fold a regenerate's notes into the animals currently on screen, as an unsaved
 * draft. Each regenerated note replaces the note of the animal with the same name
 * (ignoring case), keeping that exam's id so saving updates it rather than creating
 * a duplicate. If exactly one animal and one note are left unmatched, they're the
 * same animal (the AI renamed it, or the vet renamed it in the transcript). Notes
 * still unmatched are new animals (no id, so saving creates them); animals still
 * unmatched are kept unchanged — the vet deletes one deliberately, never as a side
 * effect.
 *
 * Names: `typedNames` holds the positions (in `current`) of animals whose name the
 * vet typed into the name field; those are kept. Any other name follows the
 * regenerate — the transcript is what changed — unless the regenerate gives none,
 * or it's the same name in another case.
 */
export function mergeRegenerated<T extends ExamDraft>(
  current: T[],
  regenerated: PatientNote[],
  typedNames: ReadonlySet<number> = new Set(),
): (ExamDraft | T)[] {
  const unmatched = current.map((_, index) => index);
  const matches: (number | undefined)[] = regenerated.map((note) => {
    const name = key(note.patientName);
    if (!name) return undefined;
    const position = unmatched.findIndex((index) => key(current[index].patientName) === name);
    return position === -1 ? undefined : unmatched.splice(position, 1)[0];
  });

  const leftoverNotes = matches.filter((match) => match === undefined).length;
  if (leftoverNotes === 1 && unmatched.length === 1) {
    matches[matches.indexOf(undefined)] = unmatched.pop();
  }

  const nameFor = (note: PatientNote, index: number | undefined): string | undefined => {
    if (index === undefined) return note.patientName;
    const stored = current[index].patientName;
    if (!stored?.trim()) return note.patientName;
    if (typedNames.has(index) || !key(note.patientName)) return stored;
    if (key(note.patientName) === key(stored)) return stored;
    return note.patientName;
  };

  const merged = regenerated.map((note, i): ExamDraft => {
    const index = matches[i];
    return {
      id: index === undefined ? undefined : current[index].id,
      patientName: nameFor(note, index),
      subjective: note.subjective,
      objective: note.objective,
      assessment: note.assessment,
      plan: note.plan,
    };
  });
  return [...merged, ...unmatched.map((index) => current[index])];
}
