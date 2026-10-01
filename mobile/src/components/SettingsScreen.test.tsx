import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { SettingsScreen } from './SettingsScreen';

describe('SettingsScreen', () => {
  it('pre-fills the form with the current settings', () => {
    render(
      <SettingsScreen
        settings={{ apiUrl: 'http://192.168.1.50:8443', apiKey: 'tok' }}
        onSave={jest.fn(async () => {})}
      />,
    );
    expect(screen.getByTestId('field-apiUrl').props.value).toBe('http://192.168.1.50:8443');
    expect(screen.getByTestId('field-apiKey').props.value).toBe('tok');
  });

  it('saves edited settings and shows a confirmation', async () => {
    const onSave = jest.fn(async () => {});
    const onSaved = jest.fn();
    render(
      <SettingsScreen
        settings={{ apiUrl: 'http://old:8000', apiKey: '' }}
        onSave={onSave}
        onSaved={onSaved}
      />,
    );

    fireEvent.changeText(screen.getByTestId('field-apiUrl'), 'http://192.168.9.9:8443');
    fireEvent.changeText(screen.getByTestId('field-apiKey'), 'newkey');
    fireEvent.press(screen.getByText('Save'));

    await waitFor(() => expect(screen.getByText(/saved/i)).toBeTruthy());
    expect(onSave).toHaveBeenCalledWith({ apiUrl: 'http://192.168.9.9:8443', apiKey: 'newkey' });
    expect(onSaved).toHaveBeenCalledWith({ apiUrl: 'http://192.168.9.9:8443', apiKey: 'newkey' });
  });

  it('rejects a URL without an http(s) scheme before saving', async () => {
    const onSave = jest.fn(async () => {});
    render(<SettingsScreen settings={{ apiUrl: '', apiKey: '' }} onSave={onSave} />);

    fireEvent.changeText(screen.getByTestId('field-apiUrl'), '192.168.1.50:8443');
    fireEvent.press(screen.getByText('Save'));

    await waitFor(() => expect(screen.getByText(/must start with http/i)).toBeTruthy());
    expect(onSave).not.toHaveBeenCalled();
  });

  it('rejects an empty URL before saving', async () => {
    const onSave = jest.fn(async () => {});
    render(<SettingsScreen settings={{ apiUrl: '', apiKey: '' }} onSave={onSave} />);

    fireEvent.press(screen.getByText('Save'));

    await waitFor(() => expect(screen.getByText(/enter the backend address/i)).toBeTruthy());
    expect(onSave).not.toHaveBeenCalled();
  });

  it('surfaces a save failure instead of a false confirmation', async () => {
    const onSave = jest.fn(async () => {
      throw new Error('disk full');
    });
    render(
      <SettingsScreen settings={{ apiUrl: 'http://host:8000', apiKey: '' }} onSave={onSave} />,
    );

    fireEvent.press(screen.getByText('Save'));

    await waitFor(() => expect(screen.getByText(/disk full/i)).toBeTruthy());
    expect(screen.queryByText(/saved ✓/i)).toBeNull();
  });
});
