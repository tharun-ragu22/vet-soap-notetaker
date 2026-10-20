import { act, fireEvent, render, screen } from '@testing-library/react-native';

import type { ReadyNote } from '../services/events/appointmentWatcher';
import { NoteToast } from './NoteToast';

const bella: ReadyNote = { appointmentId: 'a1', status: 'complete', patientNames: ['Bella'] };

describe('NoteToast', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('shows nothing with nothing ready', () => {
    render(<NoteToast notes={[]} currentPath="/" onOpen={jest.fn()} onDismiss={jest.fn()} />);
    expect(screen.toJSON()).toBeNull();
  });

  it('says which note succeeded, and tapping View opens it', () => {
    const onOpen = jest.fn();
    const onDismiss = jest.fn();
    render(<NoteToast notes={[bella]} currentPath="/" onOpen={onOpen} onDismiss={onDismiss} />);

    expect(screen.getByText('Note for Bella succeeded')).toBeTruthy();
    fireEvent.press(screen.getByRole('button', { name: /Note for Bella succeeded/ }));

    expect(onOpen).toHaveBeenCalledWith('/appointment/a1');
    expect(onDismiss).toHaveBeenCalled();
  });

  it('hides itself after a few seconds', () => {
    const onDismiss = jest.fn();
    render(<NoteToast notes={[bella]} currentPath="/" onOpen={jest.fn()} onDismiss={onDismiss} />);

    act(() => jest.advanceTimersByTime(5900));
    expect(onDismiss).not.toHaveBeenCalled();
    act(() => jest.advanceTimersByTime(200));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('a newer note restarts the countdown', () => {
    const onDismiss = jest.fn();
    const props = { currentPath: '/', onOpen: jest.fn(), onDismiss };
    const { rerender } = render(<NoteToast notes={[bella]} {...props} />);

    act(() => jest.advanceTimersByTime(5000));
    rerender(<NoteToast notes={[bella, { ...bella, appointmentId: 'a2', patientNames: ['Max'] }]} {...props} />);
    act(() => jest.advanceTimersByTime(5000));

    expect(onDismiss).not.toHaveBeenCalled();
    expect(screen.getByText('Notes for Bella and Max succeeded')).toBeTruthy();
  });

  it('is skipped when the vet is already looking at that appointment', () => {
    const onDismiss = jest.fn();
    render(
      <NoteToast notes={[bella]} currentPath="/appointment/a1" onOpen={jest.fn()} onDismiss={onDismiss} />,
    );

    expect(screen.queryByText(/Bella/)).toBeNull();
    expect(onDismiss).toHaveBeenCalled();
  });

  it('shows a failure as a warning', () => {
    render(
      <NoteToast
        notes={[{ appointmentId: 'a1', status: 'no_speech', patientNames: [] }]}
        currentPath="/"
        onOpen={jest.fn()}
        onDismiss={jest.fn()}
      />,
    );
    expect(screen.getByText('No speech heard in the recording')).toBeTruthy();
    expect(screen.getByTestId('note-toast').props.accessibilityHint).toMatch(/warning/i);
  });
});
