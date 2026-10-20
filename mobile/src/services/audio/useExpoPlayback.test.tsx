import { act, renderHook } from '@testing-library/react-native';
import { useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';

import { useExpoPlayback } from './useExpoPlayback';

jest.mock('expo-audio', () => ({
  useAudioPlayer: jest.fn(),
  useAudioPlayerStatus: jest.fn(),
  setAudioModeAsync: jest.fn(async () => {}),
}));

const player = { play: jest.fn(), pause: jest.fn(), seekTo: jest.fn(async () => {}) };

beforeEach(() => {
  jest.mocked(useAudioPlayer).mockReturnValue(player as unknown as ReturnType<typeof useAudioPlayer>);
  jest.mocked(useAudioPlayerStatus).mockReturnValue({
    isLoaded: true,
    playing: false,
    currentTime: 0,
    duration: 1200,
  } as ReturnType<typeof useAudioPlayerStatus>);
});

describe('useExpoPlayback', () => {
  it('seeks exactly, not to wherever iOS finds convenient', async () => {
    const { result } = renderHook(() => useExpoPlayback('file:///x.m4a'));

    await act(() => result.current.seekTo(600));

    // expo-audio's iOS default tolerance is infinite either way.
    expect(player.seekTo).toHaveBeenCalledWith(600, 0, 0);
  });

  it('reports the position often enough for a smooth scrubber', () => {
    renderHook(() => useExpoPlayback('file:///x.m4a'));

    expect(useAudioPlayer).toHaveBeenCalledWith({ uri: 'file:///x.m4a' }, { updateInterval: 250 });
  });
});
