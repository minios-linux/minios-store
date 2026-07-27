import { describe, it, expect } from 'vitest';
import { COMPRESSION_TYPES, AVAILABLE_ICONS } from './types';
import { iconMap } from './icon-map';

describe('COMPRESSION_TYPES', () => {
  it('lists exactly the supported compressions', () => {
    expect(COMPRESSION_TYPES.map((c) => c.value)).toEqual([
      'zstd', 'xz', 'gzip', 'lzo', 'lz4',
    ]);
  });

  it('every compression has a human label', () => {
    for (const c of COMPRESSION_TYPES) {
      expect(c.label, c.value).toBeTruthy();
    }
  });
});

describe('AVAILABLE_ICONS', () => {
  it('every picker icon is registered in iconMap', () => {
    for (const name of AVAILABLE_ICONS) {
      expect(iconMap[name], name).toBeTruthy();
    }
  });

  it('contains no duplicates', () => {
    expect(new Set(AVAILABLE_ICONS).size).toBe(AVAILABLE_ICONS.length);
  });
});
