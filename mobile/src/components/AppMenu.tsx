import { useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import type { QueueEntry } from '../services/upload/types';

export type MenuPath = '/history' | '/uploads' | '/settings';

export interface AppMenuProps {
  /** The upload queue, for the Uploads badge. */
  uploads: QueueEntry[];
  onNavigate: (path: MenuPath) => void;
}

const ITEMS: { label: string; path: MenuPath }[] = [
  { label: 'History', path: '/history' },
  { label: 'Uploads', path: '/uploads' },
  { label: 'Settings', path: '/settings' },
];

/**
 * The ☰ header button and the menu it opens: History, Uploads and Settings. A plain
 * Modal rather than a swipe drawer, so it needs no extra native modules.
 */
export function AppMenu({ uploads, onNavigate }: AppMenuProps) {
  const [open, setOpen] = useState(false);
  const failed = uploads.filter((e) => e.failed).length;
  const badge = failed > 0 ? `${failed} failed` : uploads.length > 0 ? String(uploads.length) : null;

  const go = (path: MenuPath) => {
    setOpen(false);
    onNavigate(path);
  };

  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Menu"
        hitSlop={8}
        style={styles.button}
        onPress={() => setOpen(true)}
      >
        <Text style={styles.icon}>☰</Text>
        {failed > 0 ? <View style={styles.dot} /> : null}
      </Pressable>
      {open ? (
        <Modal transparent animationType="fade" visible onRequestClose={() => setOpen(false)}>
          <Pressable testID="menu-backdrop" style={styles.backdrop} onPress={() => setOpen(false)}>
            <View style={styles.panel}>
              {ITEMS.map(({ label, path }) => (
                <Pressable
                  key={path}
                  accessibilityRole="button"
                  style={styles.item}
                  onPress={() => go(path)}
                >
                  <Text style={styles.itemText}>{label}</Text>
                  {path === '/uploads' && badge ? (
                    <Text
                      testID="menu-uploads-badge"
                      style={[styles.badge, failed > 0 && styles.badgeFailed]}
                    >
                      {badge}
                    </Text>
                  ) : null}
                </Pressable>
              ))}
            </View>
          </Pressable>
        </Modal>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  button: {
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  icon: {
    color: '#1b3a5b',
    fontSize: 22,
    fontWeight: '600',
  },
  dot: {
    position: 'absolute',
    top: 4,
    right: 6,
    width: 9,
    height: 9,
    borderRadius: 5,
    backgroundColor: '#c0392b',
  },
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.25)',
  },
  panel: {
    marginTop: 96,
    marginLeft: 12,
    width: 220,
    paddingVertical: 6,
    borderRadius: 12,
    backgroundColor: '#fff',
  },
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 14,
    paddingHorizontal: 18,
  },
  itemText: {
    color: '#1b3a5b',
    fontSize: 17,
    fontWeight: '600',
  },
  badge: {
    overflow: 'hidden',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
    color: '#8a6d1b',
    backgroundColor: '#fbf1d6',
    fontSize: 13,
    fontWeight: '700',
  },
  badgeFailed: {
    color: '#fff',
    backgroundColor: '#c0392b',
  },
});
