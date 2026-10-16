import { ApiClient } from '../services/api/ApiClient';
import { mergeRegenerated } from '../services/appointments/mergeRegenerated';
import { FakeBackend } from './fakeBackend';

const note = (patient_name: string | null, plan: string) => ({
  patient_name,
  subjective: 'S',
  objective: 'O',
  assessment: 'A',
  plan,
});

const TWO_DOGS = { transcript: 'vet: Bella and Max today', patients: [note('Bella', 'P1'), note('Max', 'P2')] };

/**
 * One recording, several animals: the appointment holds the transcript once and an
 * exam per animal, and every device — phone or desktop — reads and writes the same one.
 */
describe('appointments (integration)', () => {
  function setup(options: ConstructorParameters<typeof FakeBackend>[0] = {}) {
    const backend = new FakeBackend({ notesForAudio: () => TWO_DOGS, ...options });
    const phone = new ApiClient({ baseUrl: 'http://clinic:8000', fetch: backend.fetch });
    const other = new ApiClient({ baseUrl: 'http://clinic:8000', fetch: backend.fetch });
    return { backend, phone, other };
  }

  it('a recording gives one exam per animal sharing one transcript, seen on every device', async () => {
    const { phone, other } = setup();

    const created = await phone.createAppointment(new Uint8Array([1]), 'audio/m4a');

    expect(created.transcript).toBe('vet: Bella and Max today');
    expect(created.exams.map((e) => [e.patientName, e.plan])).toEqual([
      ['Bella', 'P1'],
      ['Max', 'P2'],
    ]);
    const [synced] = await other.fetchAppointments();
    expect(synced).toEqual(created);
  });

  it('a pending appointment completes into every animal without a re-upload', async () => {
    const { backend, phone } = setup({ failNoteGeneration: true });

    const pending = await phone.createAppointment(new Uint8Array([1]), 'audio/m4a');
    expect(pending.notePending).toBe(true);
    expect(pending.exams).toHaveLength(1);
    await expect(phone.completeAppointment(pending.id)).rejects.toThrow(/502/);

    backend.failNoteGeneration = false;
    const completed = await phone.completeAppointment(pending.id);

    expect(completed.notePending).toBe(false);
    expect(completed.exams.map((e) => e.patientName)).toEqual(['Bella', 'Max']);
    expect(completed.exams[0].id).toBe(pending.exams[0].id);
    // Idempotent: completing again changes nothing.
    expect(await phone.completeAppointment(pending.id)).toEqual(completed);
  });

  it('saving edits the transcript and animals, adding and removing them', async () => {
    const { phone, other } = setup();
    const created = await phone.createAppointment(new Uint8Array([1]), 'audio/m4a');
    const [bella, max] = created.exams;

    const saved = await phone.updateAppointment(created.id, {
      transcript: 'corrected',
      exams: [
        { ...bella, plan: 'new plan' },
        { patientName: 'Luna', subjective: 's', objective: 'o', assessment: 'a', plan: 'luna' },
      ],
    });

    expect(saved.transcript).toBe('corrected');
    expect(saved.exams.map((e) => [e.patientName, e.plan])).toEqual([
      ['Bella', 'new plan'],
      ['Luna', 'luna'],
    ]);
    expect(saved.exams[0].id).toBe(bella.id);
    expect(await other.getAppointment(created.id)).toEqual(saved);
    await expect(other.getExam(max.id)).rejects.toThrow(/404/);
    expect((await other.getExam(bella.id)).transcript).toBe('corrected');
  });

  it('rejects saving an exam that belongs to another appointment', async () => {
    const { phone } = setup();
    const one = await phone.createAppointment(new Uint8Array([1]), 'audio/m4a');
    const two = await phone.createAppointment(new Uint8Array([2]), 'audio/m4a');

    await expect(
      phone.updateAppointment(one.id, { transcript: 't', exams: [two.exams[0]] }),
    ).rejects.toThrow(/400/);
  });

  it('regenerate, merged into the animals on screen, saves without duplicating them', async () => {
    const { phone } = setup();
    const created = await phone.createAppointment(new Uint8Array([1]), 'audio/m4a');

    const { transcript, patients } = await phone.regenerateAppointment('corrected', created.id);
    const saved = await phone.updateAppointment(created.id, {
      transcript,
      exams: mergeRegenerated(created.exams, patients),
    });

    expect(saved.exams.map((e) => e.id)).toEqual(created.exams.map((e) => e.id));
    expect(saved.transcript).toBe('corrected');
  });

  it('deleting the appointment removes every animal from history', async () => {
    const { phone, other } = setup();
    const created = await phone.createAppointment(new Uint8Array([1]), 'audio/m4a');

    await phone.deleteAppointment(created.id);

    expect(await other.fetchAppointments()).toEqual([]);
    expect(await other.fetchHistory()).toEqual([]);
  });

  it("the desktop's flat history lists each animal as its own exam with the transcript", async () => {
    const { phone, other } = setup();
    await phone.createAppointment(new Uint8Array([1]), 'audio/m4a');

    const history = await other.fetchHistory();

    expect(history.map((e) => [e.patientName, e.transcript])).toEqual([
      ['Bella', 'vet: Bella and Max today'],
      ['Max', 'vet: Bella and Max today'],
    ]);
  });

  it("each animal's note is injected into AVImark on its own", async () => {
    const { backend, phone } = setup();
    const created = await phone.createAppointment(new Uint8Array([1]), 'audio/m4a');

    await phone.requestInjection(created.exams[1].id);

    // What the desktop's poll sees.
    const res = await backend.fetch('http://clinic:8000/api/injections/pending');
    const { requests } = (await res.json()) as { requests: { exam: Record<string, unknown> }[] };
    expect(requests).toHaveLength(1);
    expect(requests[0].exam).toMatchObject({ patient_name: 'Max', plan: 'P2' });
  });
});
