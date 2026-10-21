import { notesSeenAt } from './seenNotes';

describe('notesSeenAt', () => {
  const finished = new Set(['a1', 'a2']);

  it('counts every finished note as seen in Notes', () => {
    expect(notesSeenAt('/history', finished)).toEqual(['a1', 'a2']);
  });

  it('counts only the open appointment, once it has finished', () => {
    expect(notesSeenAt('/appointment/a2', finished)).toEqual(['a2']);
    expect(notesSeenAt('/appointment/a3', finished)).toEqual([]);
  });

  it('sees nothing anywhere else', () => {
    expect(notesSeenAt('/', finished)).toEqual([]);
    expect(notesSeenAt('/uploads', finished)).toEqual([]);
    expect(notesSeenAt('/settings', finished)).toEqual([]);
  });

  it('sees nothing before any note has finished', () => {
    expect(notesSeenAt('/history', new Set())).toEqual([]);
  });
});
