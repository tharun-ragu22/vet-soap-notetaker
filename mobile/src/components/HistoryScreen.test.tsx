import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import type { ApiClient } from '../services/api/ApiClient';
import type { Appointment, AppointmentExam } from '../services/api/types';
import { HistoryScreen } from './HistoryScreen';

function makeExam(overrides: Partial<AppointmentExam> = {}): AppointmentExam {
  return {
    id: 'exam-1',
    appointmentId: 'appt-1',
    createdAt: '2026-09-22T10:00:00Z',
    patientName: 'Rex',
    subjective: 'S',
    objective: 'O',
    assessment: 'A',
    plan: 'P',
    notePending: false,
    ...overrides,
  };
}

/** A one-animal appointment by default; `names` gives one exam per animal. */
function makeAppointment(
  overrides: Partial<Appointment> = {},
  names: (string | undefined)[] = ['Rex'],
): Appointment {
  return {
    id: 'appt-1',
    createdAt: '2026-09-22T10:00:00Z',
    transcript: 'vet: hello',
    notePending: false,
    exams: names.map((patientName, i) => makeExam({ id: `exam-${i + 1}`, patientName })),
    ...overrides,
  };
}

/** A fake exposing just the ApiClient surface HistoryScreen depends on. */
function makeApiClient(fetchAppointments: jest.Mock): Pick<ApiClient, 'fetchAppointments'> {
  return { fetchAppointments } as unknown as Pick<ApiClient, 'fetchAppointments'>;
}

describe('HistoryScreen', () => {
  it('loads and renders the synced exams newest-first', async () => {
    const exams = [
      makeAppointment({ id: 'appt-1' }, ['Rex']),
      makeAppointment({ id: 'appt-2' }, ['Bella']),
    ];
    const fetchAppointments = jest.fn(async () => exams);
    render(<HistoryScreen apiClient={makeApiClient(fetchAppointments)} />);

    await waitFor(() => expect(screen.getByText('Rex')).toBeTruthy());
    expect(screen.getByText('Bella')).toBeTruthy();
    expect(fetchAppointments).toHaveBeenCalledTimes(1);
  });

  it('shows an empty state when there are no exams', async () => {
    const fetchAppointments = jest.fn(async () => []);
    render(<HistoryScreen apiClient={makeApiClient(fetchAppointments)} />);

    await waitFor(() => expect(screen.getByText(/no appointments yet/i)).toBeTruthy());
  });

  it('shows an error with a retry that refetches', async () => {
    const fetchAppointments = jest
      .fn()
      .mockRejectedValueOnce(new Error('backend returned 502'))
      .mockResolvedValueOnce([makeAppointment()]);
    render(<HistoryScreen apiClient={makeApiClient(fetchAppointments)} />);

    await waitFor(() => expect(screen.getByText(/couldn't load/i)).toBeTruthy());

    fireEvent.press(screen.getByText(/retry/i));

    await waitFor(() => expect(screen.getByText('Rex')).toBeTruthy());
    expect(fetchAppointments).toHaveBeenCalledTimes(2);
  });

  it('refetches when the reload signal changes, so a deleted exam drops on return', async () => {
    const fetchAppointments = jest
      .fn()
      .mockResolvedValueOnce([
        makeAppointment({ id: 'appt-1' }, ['Rex']),
        makeAppointment({ id: 'appt-2' }, ['Bella']),
      ])
      .mockResolvedValueOnce([makeAppointment({ id: 'appt-1' }, ['Rex'])]);
    // One stable client across rerenders, like context's memoized instance; a new
    // object each render would change `load` and spuriously re-fire the mount load.
    const client = makeApiClient(fetchAppointments);
    const { rerender } = render(<HistoryScreen apiClient={client} reloadSignal={0} />);

    await waitFor(() => expect(screen.getByText('Bella')).toBeTruthy());
    // The initial mount loads once; a signal of 0 must NOT trigger a second fetch.
    expect(fetchAppointments).toHaveBeenCalledTimes(1);

    // Simulate the route re-focusing after a delete (reloadSignal bumped). This is
    // the fix's core contract: a focus change refetches, so the backend's now-shorter
    // list (sans the deleted exam) replaces the stale one the screen was showing.
    rerender(<HistoryScreen apiClient={client} reloadSignal={1} />);

    await waitFor(() => expect(fetchAppointments).toHaveBeenCalledTimes(2));
  });

  it('keeps the existing list when a background refresh fails', async () => {
    const fetchAppointments = jest
      .fn()
      .mockResolvedValueOnce([makeAppointment({ id: 'appt-1' }, ['Rex'])])
      .mockRejectedValueOnce(new Error('backend returned 502'));
    const client = makeApiClient(fetchAppointments);
    const { rerender } = render(<HistoryScreen apiClient={client} reloadSignal={0} />);

    await waitFor(() => expect(screen.getByText('Rex')).toBeTruthy());

    rerender(<HistoryScreen apiClient={client} reloadSignal={1} />);

    await waitFor(() => expect(fetchAppointments).toHaveBeenCalledTimes(2));
    // The failed quiet refresh must not blow the list away or show the error screen.
    expect(screen.getByText('Rex')).toBeTruthy();
    expect(screen.queryByText(/couldn't load/i)).toBeNull();
  });

  it('opens an appointment when its row is tapped', async () => {
    const fetchAppointments = jest.fn(async () => [makeAppointment({ id: 'appt-42' })]);
    const onOpenAppointment = jest.fn();
    render(
      <HistoryScreen
        apiClient={makeApiClient(fetchAppointments)}
        onOpenAppointment={onOpenAppointment}
      />,
    );

    await waitFor(() => expect(screen.getByText('Rex')).toBeTruthy());
    fireEvent.press(screen.getByTestId('appointment-row-appt-42'));

    expect(onOpenAppointment).toHaveBeenCalledWith('appt-42');
  });

  it('shows one row per appointment naming every animal in it', async () => {
    const fetchAppointments = jest.fn(async () => [
      makeAppointment({ id: 'appt-1' }, ['Bella', 'Max']),
    ]);
    render(<HistoryScreen apiClient={makeApiClient(fetchAppointments)} />);

    await waitFor(() => expect(screen.getByText('Bella, Max')).toBeTruthy());
    expect(screen.getByText(/2 animals/)).toBeTruthy();
    expect(screen.getAllByTestId(/appointment-row-/)).toHaveLength(1);
  });

  it('labels unnamed animals by position, and a lone unnamed one by date', async () => {
    const fetchAppointments = jest.fn(async () => [
      makeAppointment({ id: 'appt-2' }, ['Duke', undefined]),
      makeAppointment({ id: 'appt-1', createdAt: 'not-a-date' }, [undefined]),
    ]);
    render(<HistoryScreen apiClient={makeApiClient(fetchAppointments)} />);

    await waitFor(() => expect(screen.getByText('Duke, Patient 2')).toBeTruthy());
    expect(screen.getByText('not-a-date')).toBeTruthy();
  });

  it('marks an appointment whose notes are still generating', async () => {
    const fetchAppointments = jest.fn(async () => [
      makeAppointment({ notePending: true }, [undefined]),
    ]);
    render(<HistoryScreen apiClient={makeApiClient(fetchAppointments)} />);

    await waitFor(() => expect(screen.getByText(/notes pending/i)).toBeTruthy());
  });
});

describe('HistoryScreen search by pet name', () => {
  /** Rex, Bella, a Milo + Bella visit, and two visits with unnamed animals. */
  const appointments = () => [
    makeAppointment({ id: 'appt-rex' }, ['Rex']),
    makeAppointment({ id: 'appt-bella' }, ['Bella']),
    makeAppointment({ id: 'appt-milo-bella' }, ['Milo', 'Bella']),
    makeAppointment({ id: 'appt-duke' }, ['Duke', undefined]),
    makeAppointment({ id: 'appt-unnamed' }, [undefined]),
  ];

  /** The ids of the rows on screen, in order. */
  function shownRows(): string[] {
    return screen
      .queryAllByTestId(/appointment-row-/)
      .map((row) => String(row.props.testID).replace('appointment-row-', ''));
  }

  function search(text: string) {
    const field = screen.queryByPlaceholderText(/search by pet name/i);
    expect(field).not.toBeNull();
    fireEvent.changeText(field!, text);
  }

  async function renderLoaded(fetchAppointments = jest.fn(async () => appointments())) {
    const client = makeApiClient(fetchAppointments);
    const view = render(<HistoryScreen apiClient={client} reloadSignal={0} />);
    await waitFor(() => expect(screen.getByText('Rex')).toBeTruthy());
    return { ...view, client };
  }

  it('keeps only appointments with an animal whose name contains the search', async () => {
    await renderLoaded();

    search('bel');

    expect(shownRows()).toEqual(['appt-bella', 'appt-milo-bella']);
  });

  it('ignores case and surrounding spaces', async () => {
    await renderLoaded();

    search('  REX ');

    expect(shownRows()).toEqual(['appt-rex']);
  });

  it('says nothing matched and keeps the search field', async () => {
    await renderLoaded();

    search('zzz');

    expect(shownRows()).toEqual([]);
    expect(screen.queryByText('No appointments for "zzz".')).not.toBeNull();
    expect(screen.queryByPlaceholderText(/search by pet name/i)).not.toBeNull();
  });

  it('shows every appointment again once the search is cleared', async () => {
    await renderLoaded();

    search('rex');
    search('');

    expect(shownRows()).toEqual([
      'appt-rex',
      'appt-bella',
      'appt-milo-bella',
      'appt-duke',
      'appt-unnamed',
    ]);
  });

  it('never matches the "Patient N" label of an unnamed animal', async () => {
    await renderLoaded();

    search('patient');

    expect(shownRows()).toEqual([]);
  });

  it('keeps the search applied when the list refreshes on return', async () => {
    const fetchAppointments = jest
      .fn()
      .mockResolvedValueOnce(appointments())
      .mockResolvedValueOnce(appointments().filter((a) => a.id !== 'appt-bella'));
    const { rerender, client } = await renderLoaded(fetchAppointments);

    search('bel');
    rerender(<HistoryScreen apiClient={client} reloadSignal={1} />);

    await waitFor(() => expect(shownRows()).toEqual(['appt-milo-bella']));
    expect(screen.queryByDisplayValue('bel')).not.toBeNull();
  });
});
