import { renderHook } from '@testing-library/react-native';
import { useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';

import { useExpoPlayback } from './useExpoPlayback';

jest.mock('expo-audio', () => ({
  useAudioPlayer: jest.fn(),
  useAudioPlayerStatus: jest.fn(),
  setAudioModeAsync: jest.fn(async () => {}),
}));

const player = { play: jest.fn(), pause: jest.fn() };

function status(overrides: Partial<ReturnType<typeof useAudioPlayerStatus>> = {}) {
  jest.mocked(useAudioPlayerStatus).mockReturnValue({
    isLoaded: true,
    playing: false,
    didJustFinish: false,
    ...overrides,
  } as ReturnType<typeof useAudioPlayerStatus>);
}

beforeEach(() => {
  jest.mocked(useAudioPlayer).mockReturnValue(player as unknown as ReturnType<typeof useAudioPlayer>);
  status();
});

describe('useExpoPlayback', () => {
  it('reports when the recording has played to the end', () => {
    status({ didJustFinish: true });

    const { result } = renderHook(() => useExpoPlayback('file:///x.m4a'));

    expect(result.current.status).toEqual({ loaded: true, playing: false, finished: true });
  });

  it('stops the sound when it goes away', () => {
    const { unmount } = renderHook(() => useExpoPlayback('file:///x.m4a'));

    unmount();

    expect(player.pause).toHaveBeenCalled();
  });
});
