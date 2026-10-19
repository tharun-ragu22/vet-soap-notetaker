import { formatClock, timeAt } from './scrub';

describe('timeAt', () => {
  it('maps a touch halfway along the bar to halfway through the recording', () => {
    expect(timeAt(150, 300, 1200)).toBe(600);
  });

  it('clamps touches before the start and past the end', () => {
    expect(timeAt(-20, 300, 1200)).toBe(0);
    expect(timeAt(340, 300, 1200)).toBe(1200);
  });

  it('is 0 before the bar has been measured', () => {
    expect(timeAt(150, 0, 1200)).toBe(0);
  });
});

describe('formatClock', () => {
  it.each([
    [0, '0:00'],
    [9.6, '0:09'],
    [192, '3:12'],
    [1200, '20:00'],
    [3725, '1:02:05'],
  ])('formats %p seconds as %p', (seconds, expected) => {
    expect(formatClock(seconds)).toBe(expected);
  });
});
