/** The time, in seconds, under a touch `x` points along a scrubber `width` wide. */
export function timeAt(x: number, width: number, duration: number): number {
  if (width <= 0) return 0;
  return Math.min(Math.max(x / width, 0), 1) * duration;
}

/** `m:ss`, or `h:mm:ss` from an hour up. */
export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = String(total % 60).padStart(2, '0');
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${secs}` : `${minutes}:${secs}`;
}
