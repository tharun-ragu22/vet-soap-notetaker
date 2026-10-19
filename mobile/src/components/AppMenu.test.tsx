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
  it('opens a menu with Notes and Settings, and no Outbox when nothing is waiting', () => {
    render(<AppMenu uploads={[]} onNavigate={jest.fn()} />);
    expect(screen.queryByText('Notes')).toBeNull();

    fireEvent.press(screen.getByLabelText('Menu'));

    expect(screen.getByText('Notes')).toBeTruthy();
    expect(screen.getByText('Settings')).toBeTruthy();
    expect(screen.queryByText('Outbox')).toBeNull();
    expect(screen.queryByText('History')).toBeNull();
    expect(screen.queryByText('Uploads')).toBeNull();
  });

  it('shows Outbox while a recording is waiting', () => {
    render(<AppMenu uploads={[audio('a')]} onNavigate={jest.fn()} />);

    fireEvent.press(screen.getByLabelText('Menu'));

    expect(screen.getByText('Notes')).toBeTruthy();
    expect(screen.getByText('Outbox')).toBeTruthy();
    expect(screen.getByText('Settings')).toBeTruthy();
  });

  it.each([
    ['Notes', '/history'],
    ['Settings', '/settings'],
  ])('tapping %s navigates to %s and closes the menu', (label, path) => {
    const onNavigate = jest.fn();
    render(<AppMenu uploads={[]} onNavigate={onNavigate} />);

    fireEvent.press(screen.getByLabelText('Menu'));
    fireEvent.press(screen.getByText(label));

    expect(onNavigate).toHaveBeenCalledWith(path);
    expect(screen.queryByText(label)).toBeNull();
  });

  it('tapping Outbox navigates to /uploads and closes the menu', () => {
    const onNavigate = jest.fn();
    render(<AppMenu uploads={[audio('a')]} onNavigate={onNavigate} />);

    fireEvent.press(screen.getByLabelText('Menu'));
    const outbox = screen.queryByText('Outbox');
    expect(outbox).not.toBeNull();
    fireEvent.press(outbox!);

    expect(onNavigate).toHaveBeenCalledWith('/uploads');
    expect(screen.queryByText('Outbox')).toBeNull();
  });

  it('badges Outbox with how many are waiting', () => {
    render(<AppMenu uploads={[audio('a'), audio('b')]} onNavigate={jest.fn()} />);

    fireEvent.press(screen.getByLabelText('Menu'));

    expect(screen.queryByText('Outbox')).not.toBeNull();
    expect(screen.getByTestId('menu-uploads-badge')).toHaveTextContent('2');
  });

  it('badges Outbox with how many failed, when any did', () => {
    render(<AppMenu uploads={[audio('a', { failed: true }), audio('b')]} onNavigate={jest.fn()} />);

    fireEvent.press(screen.getByLabelText('Menu'));

    expect(screen.getByTestId('menu-uploads-badge')).toHaveTextContent('1 failed');
  });

  it('keeps Outbox in the menu while only a failed recording is left', () => {
    render(<AppMenu uploads={[audio('a', { failed: true })]} onNavigate={jest.fn()} />);

    fireEvent.press(screen.getByLabelText('Menu'));

    expect(screen.queryByText('Outbox')).not.toBeNull();
    expect(screen.getByTestId('menu-uploads-badge')).toHaveTextContent('1 failed');
  });

  it('shows no Outbox item or badge when everything is uploaded', () => {
    render(<AppMenu uploads={[]} onNavigate={jest.fn()} />);

    fireEvent.press(screen.getByLabelText('Menu'));

    expect(screen.queryByText('Outbox')).toBeNull();
    expect(screen.queryByTestId('menu-uploads-badge')).toBeNull();
  });

  it('closes when tapping outside the menu', () => {
    render(<AppMenu uploads={[]} onNavigate={jest.fn()} />);

    fireEvent.press(screen.getByLabelText('Menu'));
    fireEvent.press(screen.getByTestId('menu-backdrop'));

    expect(screen.queryByText('Notes')).toBeNull();
  });
});
