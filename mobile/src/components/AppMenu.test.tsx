import { fireEvent, render, screen } from '@testing-library/react-native';

import type { AudioEntry } from '../services/upload/types';
import { AppMenu } from './AppMenu';

function audio(id: string, overrides: Partial<AudioEntry> = {}): AudioEntry {
  return {
    id,
    stage: 'audio',
    fileName: `${id}.m4a`,
    mimeType: 'audio/m4a',
    createdAt: 'T',
    durationMillis: 1,
    attempts: 0,
    ...overrides,
  };
}

describe('AppMenu', () => {
  it('opens a menu with History, Uploads and Settings', () => {
    render(<AppMenu uploads={[]} onNavigate={jest.fn()} />);
    expect(screen.queryByText('History')).toBeNull();

    fireEvent.press(screen.getByLabelText('Menu'));

    expect(screen.getByText('History')).toBeTruthy();
    expect(screen.getByText('Uploads')).toBeTruthy();
    expect(screen.getByText('Settings')).toBeTruthy();
  });

  it.each([
    ['History', '/history'],
    ['Uploads', '/uploads'],
    ['Settings', '/settings'],
  ])('tapping %s navigates to %s and closes the menu', (label, path) => {
    const onNavigate = jest.fn();
    render(<AppMenu uploads={[]} onNavigate={onNavigate} />);

    fireEvent.press(screen.getByLabelText('Menu'));
    fireEvent.press(screen.getByText(label));

    expect(onNavigate).toHaveBeenCalledWith(path);
    expect(screen.queryByText(label)).toBeNull();
  });

  it('badges Uploads with how many are waiting', () => {
    render(<AppMenu uploads={[audio('a'), audio('b')]} onNavigate={jest.fn()} />);

    fireEvent.press(screen.getByLabelText('Menu'));

    expect(screen.getByTestId('menu-uploads-badge')).toHaveTextContent('2');
  });

  it('badges Uploads with how many failed, when any did', () => {
    render(<AppMenu uploads={[audio('a', { failed: true }), audio('b')]} onNavigate={jest.fn()} />);

    fireEvent.press(screen.getByLabelText('Menu'));

    expect(screen.getByTestId('menu-uploads-badge')).toHaveTextContent('1 failed');
  });

  it('shows no badge when everything is uploaded', () => {
    render(<AppMenu uploads={[]} onNavigate={jest.fn()} />);

    fireEvent.press(screen.getByLabelText('Menu'));

    expect(screen.queryByTestId('menu-uploads-badge')).toBeNull();
  });

  it('closes when tapping outside the menu', () => {
    render(<AppMenu uploads={[]} onNavigate={jest.fn()} />);

    fireEvent.press(screen.getByLabelText('Menu'));
    fireEvent.press(screen.getByTestId('menu-backdrop'));

    expect(screen.queryByText('History')).toBeNull();
  });
});
