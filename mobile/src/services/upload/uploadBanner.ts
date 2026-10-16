import type { QueueEntry } from './types';

function recordings(count: number): string {
  return count === 1 ? '1 recording' : `${count} recordings`;
}

/**
 * The home screen's queue banner: null when nothing is waiting. Failed recordings
 * (automatic retries stopped) take priority, since they need the vet to act.
 */
export function uploadBanner(entries: QueueEntry[]): { text: string; failed: boolean } | null {
  if (entries.length === 0) return null;
  const failed = entries.filter((e) => e.failed).length;
  if (failed > 0) {
    return { text: `${recordings(failed)} failed to upload — tap to review`, failed: true };
  }
  return { text: `${recordings(entries.length)} waiting to upload…`, failed: false };
}
