import { readEventStream, SseParser, type StreamFetch } from './sse';

describe('SseParser', () => {
  it('parses a whole event', () => {
    expect(new SseParser().push('event: appointment\ndata: {"id":"a1"}\n\n')).toEqual([
      { event: 'appointment', data: '{"id":"a1"}' },
    ]);
  });

  it('assembles an event split across chunks, even mid-line', () => {
    const parser = new SseParser();
    expect(parser.push('event: appo')).toEqual([]);
    expect(parser.push('intment\ndata: {"id"')).toEqual([]);
    expect(parser.push(':"a1"}\n')).toEqual([]);
    expect(parser.push('\n')).toEqual([{ event: 'appointment', data: '{"id":"a1"}' }]);
  });

  it('joins multi-line data with newlines', () => {
    expect(new SseParser().push('data: one\ndata: two\n\n')).toEqual([
      { event: 'message', data: 'one\ntwo' },
    ]);
  });

  it('skips comments (keepalives) and fields it does not know', () => {
    expect(new SseParser().push(': ping\n\nid: 7\nretry: 100\nevent: ready\ndata: {}\n\n')).toEqual([
      { event: 'ready', data: '{}' },
    ]);
  });

  it('accepts CRLF and CR line endings', () => {
    expect(new SseParser().push('event: a\r\ndata: 1\r\n\r\nevent: b\rdata: 2\r\r')).toEqual([
      { event: 'a', data: '1' },
      { event: 'b', data: '2' },
    ]);
  });

  it('keeps a CRLF split between chunks as one line ending', () => {
    const parser = new SseParser();
    expect(parser.push('data: 1\r')).toEqual([]);
    expect(parser.push('\n\r\n')).toEqual([{ event: 'message', data: '1' }]);
  });

  it('strips only one leading space from a value', () => {
    expect(new SseParser().push('data:  indented\ndata:tight\n\n')).toEqual([
      { event: 'message', data: ' indented\ntight' },
    ]);
  });

  it('dispatches nothing for an event with no data', () => {
    expect(new SseParser().push('event: lonely\n\n')).toEqual([]);
  });
});

/** A ReadableStream that yields the given chunks, then ends. */
function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) controller.enqueue(encoder.encode(chunks[i++]));
      else controller.close();
    },
  });
}

describe('readEventStream', () => {
  const target = { url: 'http://clinic/api/events', headers: { Authorization: 'Bearer k' } };

  it('requests the stream and delivers every event until it ends', async () => {
    const calls: { url: string; headers: Record<string, string> }[] = [];
    const fetchFn: StreamFetch = async (url, init) => {
      calls.push({ url, headers: init.headers });
      return { ok: true, status: 200, body: streamOf(['event: ready\ndata: {}\n\nevent: appo', 'intment\ndata: {"id":"a1"}\n\n']) };
    };
    const events: unknown[] = [];

    await readEventStream({ target, fetch: fetchFn, signal: new AbortController().signal, onEvent: (e) => events.push(e) });

    expect(calls).toEqual([{ url: 'http://clinic/api/events', headers: { Authorization: 'Bearer k' } }]);
    expect(events).toEqual([
      { event: 'ready', data: '{}' },
      { event: 'appointment', data: '{"id":"a1"}' },
    ]);
  });

  it('decodes a multi-byte character split across chunks', async () => {
    const bytes = new TextEncoder().encode('data: Bélla\n\n');
    const split = bytes.indexOf(0xc3) + 1; // between the two bytes of "é"
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, split));
        controller.enqueue(bytes.slice(split));
        controller.close();
      },
    });
    const events: { data: string }[] = [];

    await readEventStream({
      target,
      fetch: async () => ({ ok: true, status: 200, body }),
      signal: new AbortController().signal,
      onEvent: (e) => events.push(e),
    });

    expect(events.map((e) => e.data)).toEqual(['Bélla']);
  });

  it('rejects with the status when the backend refuses the stream', async () => {
    await expect(
      readEventStream({
        target,
        fetch: async () => ({ ok: false, status: 401, body: null }),
        signal: new AbortController().signal,
        onEvent: () => undefined,
      }),
    ).rejects.toThrow('401');
  });

  it('passes the signal so closing the stream aborts the request', async () => {
    const controller = new AbortController();
    let seen: AbortSignal | undefined;
    await readEventStream({
      target,
      fetch: async (_url, init) => {
        seen = init.signal;
        return { ok: true, status: 200, body: streamOf([]) };
      },
      signal: controller.signal,
      onEvent: () => undefined,
    });
    expect(seen).toBe(controller.signal);
  });
});
