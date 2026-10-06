import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import type { ApiClient } from '../services/api/ApiClient';
import type { Exam } from '../services/api/types';
import { ExamEditor } from './ExamEditor';

function makeExam(overrides: Partial<Exam> = {}): Exam {
  return {
    id: 'exam-1',
    createdAt: '2026-09-22T10:00:00Z',
    patientName: 'Rex',
    subjective: 'S',
    objective: 'O',
    assessment: 'A',
    plan: 'P',
    transcript: 'vet: hello',
    ...overrides,
  };
}

type EditorApi = Pick<
  ApiClient,
  'updateExam' | 'requestInjection' | 'deleteExam' | 'regenerateNote'
>;

function makeApiClient(overrides: Partial<EditorApi> = {}): EditorApi {
  return {
    updateExam: jest.fn(async (_id: string, note) => makeExam(note)),
    requestInjection: jest.fn(async () => ({
      id: 'req-1',
      examId: 'exam-1',
      createdAt: '2026-09-22T10:05:00Z',
      status: 'pending',
      outcome: null,
    })),
    deleteExam: jest.fn(async () => {}),
    regenerateNote: jest.fn(async (transcript: string) => ({
      subjective: 'S2',
      objective: 'O2',
      assessment: 'A2',
      plan: 'P2',
      transcript,
    })),
    ...overrides,
  } as unknown as EditorApi;
}

describe('ExamEditor', () => {
  it('pre-fills the SOAP fields from the exam', () => {
    render(<ExamEditor exam={makeExam()} apiClient={makeApiClient()} />);

    expect(screen.getByTestId('field-subjective').props.value).toBe('S');
    expect(screen.getByTestId('field-objective').props.value).toBe('O');
    expect(screen.getByTestId('field-assessment').props.value).toBe('A');
    expect(screen.getByTestId('field-plan').props.value).toBe('P');
  });

  it('saves edited fields back to the backend and confirms', async () => {
    const apiClient = makeApiClient();
    const onSaved = jest.fn();
    render(<ExamEditor exam={makeExam()} apiClient={apiClient} onSaved={onSaved} />);

    fireEvent.changeText(screen.getByTestId('field-assessment'), 'kennel cough');
    fireEvent.press(screen.getByText(/save changes/i));

    await waitFor(() => expect(screen.getByText(/saved/i)).toBeTruthy());
    expect(apiClient.updateExam).toHaveBeenCalledWith('exam-1', {
      subjective: 'S',
      objective: 'O',
      assessment: 'kennel cough',
      plan: 'P',
      transcript: 'vet: hello',
    });
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it('surfaces a save failure', async () => {
    const apiClient = makeApiClient({
      updateExam: jest.fn(async () => {
        throw new Error('backend returned 502');
      }),
    });
    render(<ExamEditor exam={makeExam()} apiClient={apiClient} />);

    fireEvent.press(screen.getByText(/save changes/i));

    await waitFor(() => expect(screen.getByText(/502/)).toBeTruthy());
  });

  it('regenerates the note from the edited transcript and updates the SOAP fields', async () => {
    const apiClient = makeApiClient();
    render(<ExamEditor exam={makeExam()} apiClient={apiClient} />);

    // The vet hand-corrects the transcript, then regenerates from it.
    fireEvent.changeText(screen.getByTestId('field-transcript'), 'vet: corrected words');
    fireEvent.press(screen.getByText(/regenerate from transcript/i));

    await waitFor(() => expect(screen.getByText(/regenerated/i)).toBeTruthy());
    expect(apiClient.regenerateNote).toHaveBeenCalledWith('vet: corrected words');
    expect(screen.getByTestId('field-subjective').props.value).toBe('S2');
    expect(screen.getByTestId('field-objective').props.value).toBe('O2');
    expect(screen.getByTestId('field-assessment').props.value).toBe('A2');
    expect(screen.getByTestId('field-plan').props.value).toBe('P2');
    // The edited transcript is preserved, not overwritten.
    expect(screen.getByTestId('field-transcript').props.value).toBe('vet: corrected words');
  });

  it('regeneration is non-destructive — it does not save until the vet taps Save', async () => {
    const apiClient = makeApiClient();
    render(<ExamEditor exam={makeExam()} apiClient={apiClient} />);

    fireEvent.press(screen.getByText(/regenerate from transcript/i));

    await waitFor(() => expect(screen.getByText(/regenerated/i)).toBeTruthy());
    // Nothing persisted by the regenerate itself.
    expect(apiClient.updateExam).not.toHaveBeenCalled();

    // Saving afterwards persists the regenerated fields.
    fireEvent.press(screen.getByText(/save changes/i));
    await waitFor(() => expect(apiClient.updateExam).toHaveBeenCalledTimes(1));
    expect(apiClient.updateExam).toHaveBeenCalledWith('exam-1', {
      subjective: 'S2',
      objective: 'O2',
      assessment: 'A2',
      plan: 'P2',
      transcript: 'vet: hello',
    });
  });

  it('surfaces a regeneration failure', async () => {
    const apiClient = makeApiClient({
      regenerateNote: jest.fn(async () => {
        throw new Error('backend returned 502');
      }),
    });
    render(<ExamEditor exam={makeExam()} apiClient={apiClient} />);

    fireEvent.press(screen.getByText(/regenerate from transcript/i));

    await waitFor(() => expect(screen.getByText(/502/)).toBeTruthy());
    expect(apiClient.updateExam).not.toHaveBeenCalled();
  });

  it('requests a remote AVImark injection for this exam and confirms it was sent', async () => {
    const apiClient = makeApiClient();
    render(<ExamEditor exam={makeExam({ id: 'exam-77' })} apiClient={apiClient} />);

    fireEvent.press(screen.getByText(/inject into avimark/i));

    await waitFor(() => expect(screen.getByText(/sent to the desktop/i)).toBeTruthy());
    expect(apiClient.requestInjection).toHaveBeenCalledWith('exam-77');
  });

  it('saves the current edits before injecting so the desktop gets what the vet sees', async () => {
    const apiClient = makeApiClient();
    const onSaved = jest.fn();
    render(
      <ExamEditor exam={makeExam({ id: 'exam-77' })} apiClient={apiClient} onSaved={onSaved} />,
    );

    // The vet edits a field, then taps Inject *without* tapping Save Changes first.
    fireEvent.changeText(screen.getByTestId('field-assessment'), 'kennel cough');
    fireEvent.press(screen.getByText(/inject into avimark/i));

    await waitFor(() => expect(screen.getByText(/sent to the desktop/i)).toBeTruthy());
    // The edit is persisted as part of injecting...
    expect(apiClient.updateExam).toHaveBeenCalledWith('exam-77', {
      subjective: 'S',
      objective: 'O',
      assessment: 'kennel cough',
      plan: 'P',
      transcript: 'vet: hello',
    });
    expect(onSaved).toHaveBeenCalledTimes(1);
    // ...and the save lands *before* the injection is requested, so the backend
    // builds the injection from the fresh note, not the stale stored one.
    const saveOrder = (apiClient.updateExam as jest.Mock).mock.invocationCallOrder[0];
    const injectOrder = (apiClient.requestInjection as jest.Mock).mock.invocationCallOrder[0];
    expect(saveOrder).toBeLessThan(injectOrder);
  });

  it('does not re-save when nothing was edited, but still injects', async () => {
    const apiClient = makeApiClient();
    render(<ExamEditor exam={makeExam({ id: 'exam-77' })} apiClient={apiClient} />);

    fireEvent.press(screen.getByText(/inject into avimark/i));

    await waitFor(() => expect(screen.getByText(/sent to the desktop/i)).toBeTruthy());
    // Nothing changed, so there's no redundant backend write...
    expect(apiClient.updateExam).not.toHaveBeenCalled();
    // ...but the injection is still requested.
    expect(apiClient.requestInjection).toHaveBeenCalledWith('exam-77');
  });

  it('does not inject when saving the edit fails, to avoid injecting a stale note', async () => {
    const apiClient = makeApiClient({
      updateExam: jest.fn(async () => {
        throw new Error('backend returned 502');
      }),
    });
    render(<ExamEditor exam={makeExam()} apiClient={apiClient} />);

    fireEvent.changeText(screen.getByTestId('field-assessment'), 'kennel cough');
    fireEvent.press(screen.getByText(/inject into avimark/i));

    await waitFor(() => expect(screen.getByText(/502/)).toBeTruthy());
    // The save didn't land, so the backend still holds the old note -- we must
    // not ask it to inject that.
    expect(apiClient.requestInjection).not.toHaveBeenCalled();
  });

  it('surfaces an injection request failure', async () => {
    const apiClient = makeApiClient({
      requestInjection: jest.fn(async () => {
        throw new Error('backend returned 404');
      }),
    });
    render(<ExamEditor exam={makeExam()} apiClient={apiClient} />);

    fireEvent.press(screen.getByText(/inject into avimark/i));

    await waitFor(() => expect(screen.getByText(/404/)).toBeTruthy());
  });

  it('requires a confirming second tap before deleting, then removes it', async () => {
    const apiClient = makeApiClient();
    const onDeleted = jest.fn();
    render(
      <ExamEditor exam={makeExam({ id: 'exam-9' })} apiClient={apiClient} onDeleted={onDeleted} />,
    );

    // First tap only arms the confirmation — nothing is deleted yet.
    fireEvent.press(screen.getByText(/^delete exam$/i));
    expect(apiClient.deleteExam).not.toHaveBeenCalled();
    expect(screen.getByText(/tap again/i)).toBeTruthy();

    // Second tap performs the delete and notifies the caller.
    fireEvent.press(screen.getByText(/tap again/i));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
    expect(apiClient.deleteExam).toHaveBeenCalledWith('exam-9');
  });

  it('surfaces a delete failure and does not notify the caller', async () => {
    const apiClient = makeApiClient({
      deleteExam: jest.fn(async () => {
        throw new Error('backend returned 500');
      }),
    });
    const onDeleted = jest.fn();
    render(<ExamEditor exam={makeExam()} apiClient={apiClient} onDeleted={onDeleted} />);

    fireEvent.press(screen.getByText(/^delete exam$/i));
    fireEvent.press(screen.getByText(/tap again/i));

    await waitFor(() => expect(screen.getByText(/500/)).toBeTruthy());
    expect(onDeleted).not.toHaveBeenCalled();
  });
});
