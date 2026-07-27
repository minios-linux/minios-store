import { describe, it, expect } from 'vitest';
import { iconMap, FallbackIcon } from './icon-map';

describe('iconMap', () => {
  it('contains the store-critical icons', () => {
    for (const name of [
      'Globe', 'Video', 'Palette', 'Code', 'Gamepad2',
      'Wrench', 'Shield', 'Package', 'FileText', 'Music',
    ]) {
      expect(iconMap[name], name).toBeTruthy();
    }
  });

  it('every entry is a defined component', () => {
    for (const [name, comp] of Object.entries(iconMap)) {
      expect(comp, name).toBeTruthy();
    }
  });

  it('has a reasonable number of icons', () => {
    expect(Object.keys(iconMap).length).toBeGreaterThan(30);
  });

  it('exports a fallback icon', () => {
    expect(FallbackIcon).toBeTruthy();
  });
});
