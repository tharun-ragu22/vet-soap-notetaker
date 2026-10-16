import type { QueueEntry } from './types';

export interface UploadDescription {
  /** One line: where this recording is up to. */
  status: string;
  /** Why it's there, or what to do about it; null when there's nothing to add. */
  detail: string | null;
}

const TRANSCRIPT_SAFE = 'The transcript is saved on the computer.';

/**
 * Plain-words status for a queued recording on the Uploads screen. Built only from
 * the entry's error *kind* and HTTP status, never its raw `lastError`, which can
 * quote the backend's response body.
 */
export function describeUpload(entry: QueueEntry, activeId: string | null): UploadDescription {
  if (entry.id === activeId) return { status: 'Uploading…', detail: null };

  if (entry.lastErrorKind === 'unreachable' && !entry.failed) {
    return {
      status: "Can't reach the backend — retrying automatically",
      detail: 'Check the address in Settings and that the computer is on.',
    };
  }

  const reason = failureReason(entry);
  const tries = `${entry.attempts} ${entry.attempts === 1 ? 'try' : 'tries'}`;

  if (entry.stage === 'note') {
    if (entry.failed) {
      return {
        status: `Notes failed after ${tries}`,
        detail: reason ? `${reason}. ${TRANSCRIPT_SAFE}` : TRANSCRIPT_SAFE,
      };
    }
    return { status: 'Uploaded — notes still generating', detail: TRANSCRIPT_SAFE };
  }

  if (entry.failed) return { status: `Upload failed after ${tries}`, detail: reason };
  if (entry.attempts > 0) {
    return {
      status: `Waiting to retry (tried ${entry.attempts} ${entry.attempts === 1 ? 'time' : 'times'})`,
      detail: reason,
    };
  }
  return { status: 'Waiting to upload', detail: null };
}

function failureReason(entry: QueueEntry): string | null {
  if (entry.lastErrorKind === 'other') return "Couldn't read the recording on this phone";
  if (entry.lastErrorKind !== 'backend') return null;
  const status = entry.lastStatus;
  if (status === 401 || status === 403) return `API key rejected (${status}) — check Settings`;
  if (status === 404) return `Backend out of date (${status}) — update it on the computer`;
  return status === undefined ? 'Backend error' : `Backend error (${status})`;
}
