import { ApiClient, ApiClientError } from '../services/api/ApiClient';
import { FakeBackend } from './fakeBackend';

/**
 * The remote AVImark injection bridge, end to end across the contract: the phone posts
 * a request, and the desktop tray app (simulated here by reading pending + acking
 * against the same backend) picks it up. Verifies the two behaviours the desktop relies
 * on: the note is resolved fresh at poll time (so post-request edits are pasted), and an
 * acked request drops out of the pending list.
 */
describe('remote injection bridge (integration)', () => {
  async function desktopPoll(backend: FakeBackend) {
    const res = await backend.fetch('http://clinic:8000/api/injections/pending');
    return (await res.json()) as { requests: Record<string, any>[] };
  }

  async function desktopAck(backend: FakeBackend, id: string, outcome: string) {
    return backend.fetch(`http://clinic:8000/api/injections/${id}/ack`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ outcome }),
    });
  }

  it('a phone request becomes a pending job the desktop can see, carrying the note', async () => {
    const backend = new FakeBackend();
    const phone = new ApiClient({ baseUrl: 'http://clinic:8000', fetch: backend.fetch });
    const exam = await phone.generateNote(new Uint8Array([1, 2, 3]), 'audio/m4a');

    const req = await phone.requestInjection(exam.id);
    expect(req.status).toBe('pending');
    expect(req.examId).toBe(exam.id);

    const { requests } = await desktopPoll(backend);
    expect(requests).toHaveLength(1);
    expect(requests[0].id).toBe(req.id);
    // The desktop pastes what the exam.note carries.
    expect(requests[0].exam.assessment).toBe(exam.assessment);
  });

  it('resolves the note fresh at poll time so post-request edits are pasted', async () => {
    const backend = new FakeBackend();
    const phone = new ApiClient({ baseUrl: 'http://clinic:8000', fetch: backend.fetch });
    const exam = await phone.generateNote(new Uint8Array([1]), 'audio/m4a');

    await phone.requestInjection(exam.id);
    // Vet corrects the note *after* tapping Inject.
    await phone.updateExam(exam.id, {
      subjective: exam.subjective,
      objective: exam.objective,
      assessment: 'Corrected assessment',
      plan: exam.plan,
      transcript: exam.transcript,
    });

    const { requests } = await desktopPoll(backend);
    expect(requests[0].exam.assessment).toBe('Corrected assessment');
  });

  it('an acked request drops out of the pending list', async () => {
    const backend = new FakeBackend();
    const phone = new ApiClient({ baseUrl: 'http://clinic:8000', fetch: backend.fetch });
    const exam = await phone.generateNote(new Uint8Array([1]), 'audio/m4a');
    const req = await phone.requestInjection(exam.id);

    const before = await desktopPoll(backend);
    expect(before.requests).toHaveLength(1);

    const ack = await desktopAck(backend, req.id, 'delivered');
    expect(ack.status).toBe(200);
    expect(((await ack.json()) as { status: string }).status).toBe('done');

    const after = await desktopPoll(backend);
    expect(after.requests).toHaveLength(0);
  });

  it('rejects an injection request for an unknown exam', async () => {
    const backend = new FakeBackend();
    const phone = new ApiClient({ baseUrl: 'http://clinic:8000', fetch: backend.fetch });

    await expect(phone.requestInjection('nope')).rejects.toBeInstanceOf(ApiClientError);
    await expect(phone.requestInjection('nope')).rejects.toThrow(/404/);
  });
});
