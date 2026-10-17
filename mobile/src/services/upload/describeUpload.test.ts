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

  it('says no speech was heard, rather than a backend error', () => {
    expect(
      describeUpload(audio({ attempts: 1, failed: true, lastErrorKind: 'backend', lastStatus: 422 }), null),
    ).toEqual({
      status: 'No speech heard in this recording',
      detail: "Check the microphone wasn't covered or muted, then Retry or Discard.",
    });
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

  describe('when it last tried', () => {
    const NOW = Date.parse('2026-10-17T12:00:00Z');
    const triedAgo = (ms: number) => new Date(NOW - ms).toISOString();

    it('says it tried just now, under a minute ago', () => {
      expect(
        describeUpload(audio({ lastErrorKind: 'unreachable', lastAttemptAt: triedAgo(30_000) }), null, NOW),
      ).toEqual({
        status: "Can't reach the backend — retrying automatically",
        detail: 'Check the address in Settings and that the computer is on. Last tried just now.',
      });
    });

    it.each([
      [90_000, '1 min ago'],
      [7 * 60_000, '7 min ago'],
      [125 * 60_000, '2 h ago'],
    ])('after %i ms says "%s"', (ago, text) => {
      const entry = audio({ lastErrorKind: 'unreachable', lastAttemptAt: triedAgo(ago) });
      expect(describeUpload(entry, null, NOW).detail).toMatch(new RegExp(`Last tried ${text}\\.$`));
    });

    it('shows on a recording waiting to retry and on a failed one', () => {
      const waiting = audio({ attempts: 2, lastErrorKind: 'backend', lastStatus: 502, lastAttemptAt: triedAgo(0) });
      const failed = audio({ ...waiting, attempts: 5, failed: true });

      expect(describeUpload(waiting, null, NOW).detail).toBe('Backend error (502). Last tried just now.');
      expect(describeUpload(failed, null, NOW).detail).toBe('Backend error (502). Last tried just now.');
    });

    it('stays just "Uploading…" while it is uploading', () => {
      const entry = audio({ lastErrorKind: 'unreachable', lastAttemptAt: triedAgo(60_000) });
      expect(describeUpload(entry, 'a', NOW)).toEqual({ status: 'Uploading…', detail: null });
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
