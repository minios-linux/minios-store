import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// Unmount React trees rendered via Testing Library after every test.
afterEach(() => {
  cleanup();
});
