import type { ExamDraft, PatientNote } from '../api/types';
import { mergeRegenerated } from './mergeRegenerated';

const fields = (plan: string) => ({ subjective: 's', objective: 'o', assessment: 'a', plan });

const draft = (id: string, patientName: string | undefined, plan = 'old'): ExamDraft => ({
  id,
  patientName,
  ...fields(plan),
});

const regenerated = (patientName: string | undefined, plan = 'new'): PatientNote => ({
  patientName,
  ...fields(plan),
});

describe('mergeRegenerated', () => {
  it('gives each animal its regenerated note, keeping its id, matched by name', () => {
    const merged = mergeRegenerated(
      [draft('e1', 'Bella'), draft('e2', 'Max')],
      [regenerated('Max', 'max new'), regenerated('Bella', 'bella new')],
    );

    expect(merged).toEqual([
      { id: 'e2', patientName: 'Max', ...fields('max new') },
      { id: 'e1', patientName: 'Bella', ...fields('bella new') },
    ]);
  });

  it('matches names ignoring case and surrounding spaces', () => {
    const merged = mergeRegenerated([draft('e1', ' bella ')], [regenerated('Bella'), regenerated('Max')]);

    expect(merged[0].id).toBe('e1');
    expect(merged[1].id).toBeUndefined();
  });

  it('adds a newly detected animal without an id, so saving creates it', () => {
    const merged = mergeRegenerated(
      [draft('e1', 'Bella')],
      [regenerated('Bella'), regenerated('Luna', 'luna plan')],
    );

    expect(merged[1]).toEqual({ id: undefined, patientName: 'Luna', ...fields('luna plan') });
  });

  it('keeps an animal the regenerate no longer finds, unchanged, rather than deleting it', () => {
    const merged = mergeRegenerated([draft('e1', 'Bella'), draft('e2', 'Max', 'max old')], [regenerated('Bella')]);

    expect(merged).toEqual([
      { id: 'e1', patientName: 'Bella', ...fields('new') },
      { id: 'e2', patientName: 'Max', ...fields('max old') },
    ]);
  });

  it('pairs a single leftover animal with a single leftover note whatever their names', () => {
    // One animal, now named by the AI (or renamed): still the same exam.
    const merged = mergeRegenerated([draft('e1', undefined)], [regenerated('Bella')]);

    expect(merged).toEqual([{ id: 'e1', patientName: 'Bella', ...fields('new') }]);
  });

  it("keeps a name the vet typed when the regenerated note's name doesn't match it", () => {
    const merged = mergeRegenerated([draft('e1', 'Luna')], [regenerated('Patient 1')]);

    expect(merged).toEqual([{ id: 'e1', patientName: 'Luna', ...fields('new') }]);
  });

  it('does not pair leftovers when there are several, adding and keeping them instead', () => {
    const merged = mergeRegenerated(
      [draft('e1', 'Patient 1'), draft('e2', 'Patient 2')],
      [regenerated('Bella'), regenerated('Max')],
    );

    expect(merged.map((e) => [e.id, e.patientName])).toEqual([
      [undefined, 'Bella'],
      [undefined, 'Max'],
      ['e1', 'Patient 1'],
      ['e2', 'Patient 2'],
    ]);
  });

  it('never matches two notes to the same animal', () => {
    const merged = mergeRegenerated([draft('e1', 'Bella')], [regenerated('Bella'), regenerated('bella')]);

    expect(merged.map((e) => e.id)).toEqual(['e1', undefined]);
  });
});
