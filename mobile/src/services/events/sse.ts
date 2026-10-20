import type { EventStreamTarget } from '../api/ApiClient';

/** One dispatched server-sent event. `event` is "message" when the server named none. */
export interface SseEvent {
  event: string;
  data: string;
}

/**
 * Incremental parser for the `text/event-stream` wire format: feed it chunks as they
 * arrive, in any split, and get back the events they complete. Handles LF, CRLF and
 * CR line endings (including a CRLF split between chunks), multi-line `data`, and
 * comment lines (the backend's keepalives), which are skipped.
 */
export class SseParser {
  private buffer = '';
  private event = '';
  private data: string[] = [];
  /** The last chunk ended in CR: a LF starting the next one belongs to that line ending. */
  private pendingCr = false;

  push(chunk: string): SseEvent[] {
    let text = chunk;
    if (this.pendingCr && text.startsWith('\n')) text = text.slice(1);
    this.pendingCr = text.endsWith('\r');
    this.buffer += text;

    const out: SseEvent[] = [];
    const lines = this.buffer.split(/\r\n|\r|\n/);
    // The last piece has no line ending yet: keep it for the next chunk.
    this.buffer = lines.pop() ?? '';
    for (const line of lines) {
      const event = this.line(line);
      if (event) out.push(event);
    }
    return out;
  }

  private line(line: string): SseEvent | null {
    if (line === '') {
      const event = this.data.length > 0 ? { event: this.event || 'message', data: this.data.join('\n') } : null;
      this.event = '';
      this.data = [];
      return event;
    }
    if (line.startsWith(':')) return null;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') this.event = value;
    else if (field === 'data') this.data.push(value);
    // id / retry / unknown fields: not used.
    return null;
  }
}

/** The streaming subset of fetch this needs — `expo/fetch` in the app, a fake in tests. */
export type StreamFetch = (
  url: string,
  init: { headers: Record<string, string>; signal: AbortSignal },
) => Promise<{ ok: boolean; status: number; body: ReadableStream<Uint8Array> | null }>;

/**
 * Open the stream and deliver its events until it ends (resolves) or fails (rejects).
 * Aborting `signal` closes it.
 */
export async function readEventStream(options: {
  target: EventStreamTarget;
  fetch: StreamFetch;
  signal: AbortSignal;
  onEvent: (event: SseEvent) => void;
}): Promise<void> {
  const { target, signal, onEvent } = options;
  const response = await options.fetch(target.url, { headers: target.headers, signal });
  if (!response.ok || !response.body) {
    throw new Error(`event stream refused: ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const event of parser.push(decoder.decode(value, { stream: true }))) onEvent(event);
    }
  } finally {
    reader.releaseLock();
  }
}
