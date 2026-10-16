import type { AudioEntry } from './types';
import { uploadBanner } from './uploadBanner';

function audio(id: string, overrides: Partial<AudioEntry> = {}): AudioEntry {
  return {
    id,
    stage: 'audio',
    fileName: `${id}.m4a`,
    mimeType: 'audio/m4a',
    createdAt: 'T',
    durationMillis: 1,
    attempts: 0,
    ...overrides,
  };
}

describe('uploadBanner', () => {
  it('shows nothing when every recording is uploaded', () => {
    expect(uploadBanner([])).toBeNull();
  });

  it('counts recordings waiting to upload', () => {
    expect(uploadBanner([audio('a')])).toEqual({ text: '1 recording waiting to upload…', failed: false });
    expect(uploadBanner([audio('a'), audio('b')])).toEqual({
      text: '2 recordings waiting to upload…',
      failed: false,
    });
  });

  it('calls out failed recordings, which need the vet', () => {
    expect(uploadBanner([audio('a', { failed: true }), audio('b')])).toEqual({
      text: '1 recording failed to upload — tap to review',
      failed: true,
    });
    expect(uploadBanner([audio('a', { failed: true }), audio('b', { failed: true })])).toEqual({
      text: '2 recordings failed to upload — tap to review',
      failed: true,
    });
  });
});
