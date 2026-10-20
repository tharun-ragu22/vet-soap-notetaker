import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import type { Appointment, AppointmentExam } from '../services/api/types';
import { AppointmentScreen, type AppointmentScreenProps } from './AppointmentScreen';

function makeExam(overrides: Partial<AppointmentExam> = {}): AppointmentExam {
  return {
    id: 'exam-1',
    appointmentId: 'appt-1',
    createdAt: '2026-10-16T10:00:00Z',
    patientName: 'Bella',
    subjective: 'S1',
    objective: 'O1',
    assessment: 'A1',
    plan: 'P1',
    notePending: false,
    ...overrides,
  };
}

function makeAppointment(overrides: Partial<Appointment> = {}): Appointment {
  return {
    id: 'appt-1',
    createdAt: '2026-10-16T10:00:00Z',
    transcript: 'vet: Bella and Max today',
    notePending: false,
    status: overrides.notePending ? 'note_pending' : 'complete',
    exams: [
      makeExam(),
      makeExam({ id: 'exam-2', patientName: 'Max', subjective: 'S2', objective: 'O2', assessment: 'A2', plan: 'P2' }),
    ],
    ...overrides,
  };
}

type Client = AppointmentScreenProps['apiClient'];

function makeClient(overrides: Partial<Record<keyof Client, jest.Mock>> = {}) {
  const client = {
    updateAppointment: jest.fn(async (_id: string, draft: { transcript: string; exams: object[] }) =>
      makeAppointment({
        transcript: draft.transcript,
        exams: draft.exams.map((e, i) =>
          makeExam({ ...(e as Partial<AppointmentExam>), id: (e as { id?: string }).id ?? `new-${i}` }),
        ),
      }),
    ),
    regenerateAppointment: jest.fn(),
    deleteAppointment: jest.fn(async () => {}),
    requestInjection: jest.fn(async (examId: string) => ({
      id: 'req-1', examId, createdAt: 'T', status: 'pending', outcome: null,
    })),
    completeAppointment: jest.fn(),
    getAppointment: jest.fn(),
    retryAppointment: jest.fn(),
    ...overrides,
  };
  return client as typeof client & Client;
}

function renderScreen(props: Partial<AppointmentScreenProps> = {}) {
  const apiClient = (props.apiClient as ReturnType<typeof makeClient>) ?? makeClient();
  const onDeleted = jest.fn();
  render(
    <AppointmentScreen
      appointment={makeAppointment()}
      apiClient={apiClient}
      onDeleted={onDeleted}
      pendingPollMs={0}
      {...props}
    />,
  );
  return { apiClient, onDeleted };
}

describe('AppointmentScreen', () => {
  it('shows the shared transcript once and a card per animal', () => {
    renderScreen();

    expect(screen.getByTestId('field-transcript').props.value).toBe('vet: Bella and Max today');
    expect(screen.getByTestId('name-0').props.value).toBe('Bella');
    expect(screen.getByTestId('name-1').props.value).toBe('Max');
    expect(screen.getByTestId('field-0-plan').props.value).toBe('P1');
    expect(screen.getByTestId('field-1-assessment').props.value).toBe('A2');
  });

  it('labels an unnamed animal by its position', () => {
    renderScreen({ appointment: makeAppointment({ exams: [makeExam({ patientName: undefined })] }) });

    expect(screen.getByText('Patient 1')).toBeTruthy();
  });

  it('saves the transcript and every animal in one request', async () => {
    const { apiClient } = renderScreen();

    fireEvent.changeText(screen.getByTestId('field-transcript'), 'corrected');
    fireEvent.changeText(screen.getByTestId('field-1-plan'), 'max plan');
    fireEvent.changeText(screen.getByTestId('name-0'), 'Bella Rose');
    fireEvent.press(screen.getByText('Save Changes'));

    await waitFor(() => expect(screen.getByText(/saved/i)).toBeTruthy());
    expect(apiClient.updateAppointment).toHaveBeenCalledWith('appt-1', {
      transcript: 'corrected',
      exams: [
        { id: 'exam-1', patientName: 'Bella Rose', subjective: 'S1', objective: 'O1', assessment: 'A1', plan: 'P1' },
        { id: 'exam-2', patientName: 'Max', subjective: 'S2', objective: 'O2', assessment: 'A2', plan: 'max plan' },
      ],
    });
  });

  it('surfaces a save failure', async () => {
    const apiClient = makeClient({
      updateAppointment: jest.fn(async () => {
        throw new Error('backend returned 500');
      }),
    });
    renderScreen({ apiClient });

    fireEvent.press(screen.getByText('Save Changes'));

    await waitFor(() => expect(screen.getByText(/save failed: backend returned 500/i)).toBeTruthy());
  });

  it('regenerates every animal from the edited transcript as an unsaved preview', async () => {
    const apiClient = makeClient({
      regenerateAppointment: jest.fn(async () => ({
        transcript: 'corrected',
        patients: [
          { patientName: 'Max', subjective: 's', objective: 'o', assessment: 'a', plan: 'max new' },
          { patientName: 'Bella', subjective: 's', objective: 'o', assessment: 'a', plan: 'bella new' },
          { patientName: 'Luna', subjective: 's', objective: 'o', assessment: 'a', plan: 'luna' },
        ],
      })),
    });
    renderScreen({ apiClient });

    fireEvent.changeText(screen.getByTestId('field-transcript'), 'corrected');
    fireEvent.press(screen.getByText('Regenerate from Transcript'));

    await waitFor(() => expect(screen.getByText(/review and save/i)).toBeTruthy());
    expect(apiClient.regenerateAppointment).toHaveBeenCalledWith('corrected', 'appt-1');
    expect(apiClient.updateAppointment).not.toHaveBeenCalled();
    expect(screen.getByTestId('name-0').props.value).toBe('Max');
    expect(screen.getByTestId('field-0-plan').props.value).toBe('max new');
    expect(screen.getByTestId('name-2').props.value).toBe('Luna');

    fireEvent.press(screen.getByText('Save Changes'));

    await waitFor(() => expect(apiClient.updateAppointment).toHaveBeenCalledTimes(1));
    const [, draft] = apiClient.updateAppointment.mock.calls[0];
    expect(draft.exams.map((e: { id?: string }) => e.id)).toEqual(['exam-2', 'exam-1', undefined]);
  });

  it('surfaces a regeneration failure and keeps the notes', async () => {
    const apiClient = makeClient({
      regenerateAppointment: jest.fn(async () => {
        throw new Error('backend returned 502');
      }),
    });
    renderScreen({ apiClient });

    fireEvent.press(screen.getByText('Regenerate from Transcript'));

    await waitFor(() => expect(screen.getByText(/regenerate failed/i)).toBeTruthy());
    expect(screen.getByTestId('field-0-plan').props.value).toBe('P1');
  });

  it("injects one animal's note without saving when nothing changed", async () => {
    const { apiClient } = renderScreen();

    fireEvent.press(screen.getByTestId('inject-1'));

    await waitFor(() => expect(screen.getByText(/sent to the desktop/i)).toBeTruthy());
    expect(apiClient.requestInjection).toHaveBeenCalledWith('exam-2');
    expect(apiClient.updateAppointment).not.toHaveBeenCalled();
  });

  it('saves edits before injecting, so the desktop pastes what the vet sees', async () => {
    const { apiClient } = renderScreen();

    fireEvent.changeText(screen.getByTestId('field-0-plan'), 'edited');
    fireEvent.press(screen.getByTestId('inject-0'));

    await waitFor(() => expect(apiClient.requestInjection).toHaveBeenCalledWith('exam-1'));
    expect(apiClient.updateAppointment).toHaveBeenCalledTimes(1);
    expect(apiClient.updateAppointment.mock.invocationCallOrder[0]).toBeLessThan(
      apiClient.requestInjection.mock.invocationCallOrder[0],
    );
  });

  it('injects a newly added animal by the id its save gave it', async () => {
    const apiClient = makeClient({
      regenerateAppointment: jest.fn(async () => ({
        transcript: 't',
        patients: [
          { patientName: 'Bella', subjective: 's', objective: 'o', assessment: 'a', plan: 'p' },
          { patientName: 'Max', subjective: 's', objective: 'o', assessment: 'a', plan: 'p' },
          { patientName: 'Luna', subjective: 's', objective: 'o', assessment: 'a', plan: 'p' },
        ],
      })),
    });
    renderScreen({ apiClient });
    fireEvent.press(screen.getByText('Regenerate from Transcript'));
    await waitFor(() => expect(screen.getByTestId('name-2')).toBeTruthy());

    fireEvent.press(screen.getByTestId('inject-2'));

    // The fake save hands the new animal the id "new-2".
    await waitFor(() => expect(apiClient.requestInjection).toHaveBeenCalledWith('new-2'));
  });

  it('does not inject when the save before it fails', async () => {
    const apiClient = makeClient({
      updateAppointment: jest.fn(async () => {
        throw new Error('backend returned 500');
      }),
    });
    renderScreen({ apiClient });

    fireEvent.changeText(screen.getByTestId('field-0-plan'), 'edited');
    fireEvent.press(screen.getByTestId('inject-0'));

    await waitFor(() => expect(screen.getByText(/injection request failed/i)).toBeTruthy());
    expect(apiClient.requestInjection).not.toHaveBeenCalled();
  });

  it('removes an animal from the draft after a confirming tap; Save deletes it', async () => {
    const { apiClient } = renderScreen();

    fireEvent.press(screen.getByTestId('remove-0'));
    expect(screen.getByTestId('name-0').props.value).toBe('Bella'); // armed, not removed
    fireEvent.press(screen.getByTestId('remove-0'));

    expect(screen.getByTestId('name-0').props.value).toBe('Max');
    expect(screen.queryByTestId('name-1')).toBeNull();
    expect(apiClient.updateAppointment).not.toHaveBeenCalled();

    fireEvent.press(screen.getByText('Save Changes'));
    await waitFor(() => expect(apiClient.updateAppointment).toHaveBeenCalledTimes(1));
    expect(apiClient.updateAppointment.mock.calls[0][1].exams.map((e: { id: string }) => e.id)).toEqual([
      'exam-2',
    ]);
  });

  it('cannot remove the last animal (delete the appointment instead)', () => {
    renderScreen({ appointment: makeAppointment({ exams: [makeExam()] }) });

    expect(screen.queryByTestId('remove-0')).toBeNull();
  });

  it('deletes the whole appointment only after a confirming second tap', async () => {
    const { apiClient, onDeleted } = renderScreen();

    fireEvent.press(screen.getByText('Delete Appointment'));
    expect(apiClient.deleteAppointment).not.toHaveBeenCalled();
    fireEvent.press(screen.getByText(/tap again to delete/i));

    await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
    expect(apiClient.deleteAppointment).toHaveBeenCalledWith('appt-1');
  });

  it('surfaces a delete failure and stays on the screen', async () => {
    const apiClient = makeClient({
      deleteAppointment: jest.fn(async () => {
        throw new Error('backend returned 500');
      }),
    });
    const { onDeleted } = renderScreen({ apiClient });

    fireEvent.press(screen.getByText('Delete Appointment'));
    fireEvent.press(screen.getByText(/tap again to delete/i));

    await waitFor(() => expect(screen.getByText(/delete failed/i)).toBeTruthy());
    expect(onDeleted).not.toHaveBeenCalled();
  });

  describe('an async upload the computer is still working on', () => {
    const placeholder = makeExam({ patientName: undefined, subjective: '', objective: '', assessment: '', plan: '', notePending: true });
    const processing = makeAppointment({ status: 'processing', notePending: true, transcript: '', exams: [placeholder] });

    it('says it is processing, with nothing to edit or generate yet', () => {
      renderScreen({ appointment: processing });

      expect(screen.getByText(/processing on the computer/i)).toBeTruthy();
      expect(screen.queryByText('Generate notes now')).toBeNull();
      expect(screen.queryByText('Save Changes')).toBeNull();
      expect(screen.getByText('Delete Appointment')).toBeTruthy();
    });

    it('shows the notes once they are done, while the screen is open', async () => {
      jest.useFakeTimers();
      try {
        const apiClient = makeClient({
          getAppointment: jest.fn().mockResolvedValueOnce(processing).mockResolvedValueOnce(makeAppointment()),
        });
        renderScreen({ appointment: processing, apiClient, pendingPollMs: 1000 });

        await act(async () => {
          await jest.advanceTimersByTimeAsync(2000);
        });

        expect(screen.getByTestId('name-1').props.value).toBe('Max');
      } finally {
        jest.useRealTimers();
      }
    });

    it('a failed recording offers Retry, which sends it back to processing', async () => {
      const failed = { ...processing, status: 'failed' as const };
      const apiClient = makeClient({ retryAppointment: jest.fn(async () => processing) });
      renderScreen({ appointment: failed, apiClient });

      expect(screen.getByText(/couldn't transcribe this recording/i)).toBeTruthy();
      fireEvent.press(screen.getByText('Retry'));

      await waitFor(() => expect(screen.getByText(/processing on the computer/i)).toBeTruthy());
      expect(apiClient.retryAppointment).toHaveBeenCalledWith('appt-1');
    });

    it('a failed Retry says so and stays failed', async () => {
      const failed = { ...processing, status: 'failed' as const };
      const apiClient = makeClient({
        retryAppointment: jest.fn(async () => {
          throw new Error('backend returned 409');
        }),
      });
      renderScreen({ appointment: failed, apiClient });

      fireEvent.press(screen.getByText('Retry'));

      await waitFor(() => expect(screen.getByText(/retry failed/i)).toBeTruthy());
      expect(screen.getByText(/couldn't transcribe this recording/i)).toBeTruthy();
    });

    it('a recording with no speech can only be deleted', () => {
      renderScreen({ appointment: { ...processing, status: 'no_speech' } });

      expect(screen.getByText(/no speech was heard/i)).toBeTruthy();
      expect(screen.queryByText('Retry')).toBeNull();
      expect(screen.getByText('Delete Appointment')).toBeTruthy();
    });
  });

  describe('while the notes are still generating', () => {
    const pending = makeAppointment({
      notePending: true,
      exams: [makeExam({ patientName: undefined, subjective: '', objective: '', assessment: '', plan: '', notePending: true })],
    });

    it('shows the transcript and a pending notice instead of editable notes', () => {
      renderScreen({ appointment: pending });

      expect(screen.getByText(/still being generated/i)).toBeTruthy();
      expect(screen.getByText('vet: Bella and Max today')).toBeTruthy();
      expect(screen.queryByTestId('field-0-plan')).toBeNull();
      expect(screen.queryByText('Save Changes')).toBeNull();
    });

    it('"Generate notes now" completes the appointment and shows every animal', async () => {
      const apiClient = makeClient({ completeAppointment: jest.fn(async () => makeAppointment()) });
      renderScreen({ appointment: pending, apiClient });

      fireEvent.press(screen.getByText('Generate notes now'));

      await waitFor(() => expect(screen.getByTestId('name-1').props.value).toBe('Max'));
      expect(apiClient.completeAppointment).toHaveBeenCalledWith('appt-1');
    });

    it('surfaces a failed generation and stays pending', async () => {
      const apiClient = makeClient({
        completeAppointment: jest.fn(async () => {
          throw new Error('backend returned 502');
        }),
      });
      renderScreen({ appointment: pending, apiClient });

      fireEvent.press(screen.getByText('Generate notes now'));

      await waitFor(() => expect(screen.getByText(/couldn't generate the notes/i)).toBeTruthy());
      expect(screen.getByText(/still being generated/i)).toBeTruthy();
    });

    it('picks up notes the background queue finished, by polling', async () => {
      jest.useFakeTimers();
      try {
        const apiClient = makeClient({
          getAppointment: jest
            .fn()
            .mockResolvedValueOnce(pending)
            .mockResolvedValueOnce(makeAppointment()),
        });
        renderScreen({ appointment: pending, apiClient, pendingPollMs: 1000 });

        await act(async () => {
          await jest.advanceTimersByTimeAsync(1000);
        });
        expect(screen.getByText(/still being generated/i)).toBeTruthy();
        await act(async () => {
          await jest.advanceTimersByTimeAsync(1000);
        });

        expect(screen.getByTestId('name-1').props.value).toBe('Max');
        expect(apiClient.getAppointment).toHaveBeenCalledWith('appt-1');
        // Done: no more polling.
        await act(async () => {
          await jest.advanceTimersByTimeAsync(5000);
        });
        expect(apiClient.getAppointment).toHaveBeenCalledTimes(2);
      } finally {
        jest.useRealTimers();
      }
    });
  });
});

describe('collapsing an animal card', () => {
  /** Presses a card's header toggle, failing on an assertion if there isn't one. */
  function toggle(index: number) {
    const header = screen.queryByTestId(`toggle-${index}`);
    expect(header).not.toBeNull();
    fireEvent.press(header!);
  }

  const fields = (index: number) => [
    `name-${index}`,
    ...['subjective', 'objective', 'assessment', 'plan'].map((f) => `field-${index}-${f}`),
  ];

  it('starts every card expanded', () => {
    renderScreen();

    expect(screen.queryByTestId('name-0')).not.toBeNull();
    expect(screen.queryByTestId('field-0-subjective')).not.toBeNull();
    expect(screen.queryByTestId('toggle-0')?.props.accessibilityState).toEqual(
      expect.objectContaining({ expanded: true }),
    );
  });

  it("tapping the header hides that animal's fields but keeps its name and Inject", () => {
    renderScreen();

    toggle(0);

    for (const id of fields(0)) expect(screen.queryByTestId(id)).toBeNull();
    expect(screen.getByText('Bella')).toBeTruthy();
    expect(screen.queryByTestId('inject-0')).not.toBeNull();
    for (const id of fields(1)) expect(screen.queryByTestId(id)).not.toBeNull();
    expect(screen.getByTestId('toggle-0').props.accessibilityState).toEqual(
      expect.objectContaining({ expanded: false }),
    );
    expect(screen.getByLabelText('Expand Bella')).toBeTruthy();
  });

  it('tapping it again shows the fields with their values', () => {
    renderScreen();

    toggle(0);
    toggle(0);

    expect(screen.getByTestId('field-0-subjective').props.value).toBe('S1');
    expect(screen.getByLabelText('Collapse Bella')).toBeTruthy();
  });

  it('keeps edits made before collapsing, and Save sends them', async () => {
    const { apiClient } = renderScreen();

    fireEvent.changeText(screen.getByTestId('field-0-subjective'), 'bella edited');
    toggle(0);
    fireEvent.press(screen.getByText('Save Changes'));

    await waitFor(() => expect(apiClient.updateAppointment).toHaveBeenCalledTimes(1));
    expect(apiClient.updateAppointment.mock.calls[0][1].exams[0].subjective).toBe('bella edited');
  });

  it('injects from a collapsed card', async () => {
    const { apiClient } = renderScreen();

    toggle(0);
    fireEvent.press(screen.getByTestId('inject-0'));

    await waitFor(() => expect(screen.getByText(/sent to the desktop/i)).toBeTruthy());
    expect(apiClient.requestInjection).toHaveBeenCalledWith('exam-1');
  });

  it('keeps a collapsed card collapsed when another animal is removed', () => {
    renderScreen();

    toggle(1);
    fireEvent.press(screen.getByTestId('remove-0'));
    fireEvent.press(screen.getByTestId('remove-0'));

    expect(screen.getByText('Max')).toBeTruthy();
    expect(screen.queryByTestId('field-0-subjective')).toBeNull();
  });
});
