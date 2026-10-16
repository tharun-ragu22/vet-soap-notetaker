import { describeUpload } from './describeUpload';
import type { AudioEntry, NoteEntry } from './types';

function audio(overrides: Partial<AudioEntry> = {}): AudioEntry {
  return {
    id: 'a',
    stage: 'audio',
    fileName: 'f.m4a',
    mimeType: 'audio/m4a',
    createdAt: '2026-10-16T15:50:00Z',
    durationMillis: 28_000,
    attempts: 0,
    ...overrides,
  };
}

function note(overrides: Partial<NoteEntry> = {}): NoteEntry {
  return { id: 'n', stage: 'note', appointmentId: 'appt', createdAt: 'T', attempts: 0, ...overrides };
}

describe('describeUpload', () => {
  it('says it is uploading while it is the active entry', () => {
    expect(describeUpload(audio(), 'a')).toEqual({ status: 'Uploading…', detail: null });
  });

  it('says it is waiting when it has never been tried', () => {
    expect(describeUpload(audio(), null)).toEqual({ status: 'Waiting to upload', detail: null });
  });

  it('says the backend is unreachable and that it keeps retrying', () => {
    expect(describeUpload(audio({ lastErrorKind: 'unreachable' }), null)).toEqual({
      status: "Can't reach the backend — retrying automatically",
      detail: 'Check the address in Settings and that the computer is on.',
    });
  });

  it('says it will retry after a backend error that has not used up its tries', () => {
    expect(describeUpload(audio({ attempts: 2, lastErrorKind: 'backend', lastStatus: 502 }), null)).toEqual({
      status: 'Waiting to retry (tried 2 times)',
      detail: 'Backend error (502)',
    });
  });

  it('says it failed, how many tries, and why, once automatic retries stop', () => {
    expect(
      describeUpload(audio({ attempts: 5, failed: true, lastErrorKind: 'backend', lastStatus: 502 }), null),
    ).toEqual({ status: 'Upload failed after 5 tries', detail: 'Backend error (502)' });
  });

  it('names a rejected API key', () => {
    expect(
      describeUpload(audio({ attempts: 5, failed: true, lastErrorKind: 'backend', lastStatus: 401 }), null).detail,
    ).toBe('API key rejected (401) — check Settings');
  });

  it('names an out-of-date backend', () => {
    expect(
      describeUpload(audio({ attempts: 5, failed: true, lastErrorKind: 'backend', lastStatus: 404 }), null).detail,
    ).toBe('Backend out of date (404) — update it on the computer');
  });

  it('names a problem on the phone itself', () => {
    expect(describeUpload(audio({ attempts: 5, failed: true, lastErrorKind: 'other' }), null).detail).toBe(
      "Couldn't read the recording on this phone",
    );
  });

  it('says the notes are still generating for an uploaded recording', () => {
    expect(describeUpload(note(), null)).toEqual({
      status: 'Uploaded — notes still generating',
      detail: 'The transcript is saved on the computer.',
    });
  });

  it('says note generation failed, keeping the reassurance', () => {
    expect(
      describeUpload(note({ attempts: 5, failed: true, lastErrorKind: 'backend', lastStatus: 502 }), null),
    ).toEqual({
      status: 'Notes failed after 5 tries',
      detail: 'Backend error (502). The transcript is saved on the computer.',
    });
  });

  it('never shows the raw error text, which can quote the backend', () => {
    const entry = audio({
      attempts: 5,
      failed: true,
      lastErrorKind: 'backend',
      lastStatus: 502,
      lastError: 'backend returned 502: {"error": "upstream provider returned 503"}',
    });

    const { status, detail } = describeUpload(entry, null);

    expect(`${status} ${detail}`).not.toMatch(/upstream|backend returned/);
  });
});
