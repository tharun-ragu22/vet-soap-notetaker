import { fetch } from 'expo/fetch';

import type { StreamFetch } from './sse';

/**
 * The real {@link StreamFetch}: `expo/fetch`, whose `response.body` streams (React
 * Native's own fetch buffers the whole response, so it can't read an endless
 * event stream). Kept in its own module so the pure stream code tests in Node.
 */
export const expoStreamFetch: StreamFetch = async (url, init) => {
  const response = await fetch(url, { headers: init.headers, signal: init.signal });
  return { ok: response.ok, status: response.status, body: response.body };
};
