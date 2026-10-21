/**
 * Which finished notes the vet is looking at on `path`: all of them in Notes (where
 * the toast also sends a tap for several), or the one appointment that's open. Used
 * to clear the recorder's "Uploaded — you'll see a notice…" once its note was seen.
 * A note that hasn't finished yet can't have been seen.
 */
export function notesSeenAt(path: string, finished: ReadonlySet<string>): string[] {
  if (path === '/history') return [...finished];
  const match = /^\/appointment\/([^/]+)$/.exec(path);
  return match && finished.has(match[1]) ? [match[1]] : [];
}
