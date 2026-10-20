import { readyToast } from './readyToast';
import type { ReadyNote } from './appointmentWatcher';

const done = (id: string, ...patientNames: string[]): ReadyNote => ({ appointmentId: id, status: 'complete', patientNames });

describe('readyToast', () => {
  it.each([
    [[], 'Note succeeded'],
    [['Bella'], 'Note for Bella succeeded'],
    [['Bella', 'Max'], 'Notes for Bella and Max succeeded'],
    [['Bella', 'Max', 'Luna'], 'Notes for Bella, Max and Luna succeeded'],
  ])('names the animals of one finished recording: %j', (names, text) => {
    expect(readyToast([done('a1', ...names)])).toEqual({
      text,
      tone: 'success',
      target: '/appointment/a1',
    });
  });

  it.each([
    ['failed', "Couldn't generate the note"],
    ['note_pending', "Couldn't generate the note"],
    ['no_speech', 'No speech heard in the recording'],
  ] as const)('warns about one %s recording', (status, text) => {
    expect(readyToast([{ appointmentId: 'a1', status, patientNames: [] }])).toEqual({
      text,
      tone: 'warning',
      target: '/appointment/a1',
    });
  });

  it('combines several finished recordings and opens Notes', () => {
    expect(readyToast([done('a1', 'Bella'), done('a2', 'Max', 'Luna')])).toEqual({
      text: 'Notes for Bella, Max and Luna succeeded',
      tone: 'success',
      target: '/history',
    });
    expect(readyToast([done('a1'), done('a2')])?.text).toBe('2 notes succeeded');
  });

  it('flags how many of several need attention', () => {
    const failed: ReadyNote = { appointmentId: 'a2', status: 'failed', patientNames: [] };
    expect(readyToast([done('a1', 'Bella'), failed])).toEqual({
      text: '2 recordings finished — 1 needs attention',
      tone: 'warning',
      target: '/history',
    });
    expect(readyToast([failed, { ...failed, appointmentId: 'a3' }])?.text).toBe(
      '2 recordings finished — 2 need attention',
    );
  });

  it('is null with nothing to show', () => {
    expect(readyToast([])).toBeNull();
  });
});
