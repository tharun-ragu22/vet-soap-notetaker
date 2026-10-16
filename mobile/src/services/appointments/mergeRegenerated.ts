import type { ExamDraft, PatientNote } from '../api/types';

function key(name: string | undefined): string {
  return (name ?? '').trim().toLowerCase();
}

/**
 * Fold a regenerate's notes into the animals currently on screen, as an unsaved
 * draft. Each regenerated note replaces the note of the animal with the same name
 * (ignoring case), keeping that exam's id so saving updates it rather than creating
 * a duplicate. If exactly one animal and one note are left unmatched, they're the
 * same animal (the AI named it, or the vet renamed it). Notes still unmatched are
 * new animals (no id, so saving creates them); animals still unmatched are kept
 * unchanged — the vet deletes one deliberately, never as a side effect.
 *
 * A name the vet gave an animal is kept over the regenerated one.
 */
export function mergeRegenerated(current: ExamDraft[], regenerated: PatientNote[]): ExamDraft[] {
  const unmatched = [...current];
  const matches: (ExamDraft | undefined)[] = regenerated.map((note) => {
    const name = key(note.patientName);
    if (!name) return undefined;
    const index = unmatched.findIndex((exam) => key(exam.patientName) === name);
    return index === -1 ? undefined : unmatched.splice(index, 1)[0];
  });

  const leftoverNotes = matches.filter((match) => match === undefined).length;
  if (leftoverNotes === 1 && unmatched.length === 1) {
    matches[matches.indexOf(undefined)] = unmatched.pop();
  }

  const merged = regenerated.map((note, index): ExamDraft => {
    const exam = matches[index];
    return {
      id: exam?.id,
      patientName: exam?.patientName || note.patientName,
      subjective: note.subjective,
      objective: note.objective,
      assessment: note.assessment,
      plan: note.plan,
    };
  });
  return [...merged, ...unmatched];
}
