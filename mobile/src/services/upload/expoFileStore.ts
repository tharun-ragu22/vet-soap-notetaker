import { Directory, File, Paths } from 'expo-file-system';

import type { AudioBody } from '../api/types';
import type { PlaybackFiles } from '../audio/types';
import type { FileStore } from './types';

/**
 * The real, on-device {@link FileStore}. Audio recordings are copied out of the
 * evictable cache (where expo-audio writes them) into a persistent `uploads/`
 * directory under the document directory, so a queued recording survives app
 * restarts and low-storage cache eviction until it has been uploaded.
 *
 * This is the thin, untested native edge (expo-file-system), like readRecording:
 * the decision logic lives in the pure UploadQueue, which is exercised in Node.
 */
const UPLOADS_DIR = 'uploads';

function uploadsDirectory(): Directory {
  const dir = new Directory(Paths.document, UPLOADS_DIR);
  if (!dir.exists) {
    dir.create({ intermediates: true });
  }
  return dir;
}

export const expoFileStore: FileStore = {
  async save(uri: string): Promise<string> {
    const dir = uploadsDirectory();
    const name = `${Date.now()}-${Math.random().toString(36).slice(2)}.m4a`;
    const destination = new File(dir, name);
    await new File(uri).copy(destination);
    return name;
  },

  async read(fileName: string): Promise<AudioBody> {
    return new File(uploadsDirectory(), fileName).arrayBuffer();
  },

  async delete(fileName: string): Promise<void> {
    const file = new File(uploadsDirectory(), fileName);
    if (file.exists) {
      file.delete();
    }
  },
};

const PLAYBACK_DIR = 'playback';

/**
 * The Outbox player's {@link PlaybackFiles}: it plays a copy in the cache, so the
 * queue can upload and delete the original while the vet is still listening.
 * Holding clears any copies a crash left behind (one player is open at a time).
 */
export const expoPlaybackFiles: PlaybackFiles = {
  async hold(fileName: string): Promise<string> {
    const dir = new Directory(Paths.cache, PLAYBACK_DIR);
    if (dir.exists) {
      dir.delete();
    }
    dir.create({ intermediates: true });
    const copy = new File(dir, fileName);
    await new File(uploadsDirectory(), fileName).copy(copy);
    return copy.uri;
  },

  async release(uri: string): Promise<void> {
    const file = new File(uri);
    if (file.exists) {
      file.delete();
    }
  },
};
