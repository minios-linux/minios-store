import { describe, it, expect, beforeEach } from 'vitest';
import {
  parallelLimit,
  loadParallelSettings,
  saveParallelSettings,
} from './parallelTranslation';

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe('parallelLimit', () => {
  it('runs every task and preserves result order', async () => {
    const tasks = [1, 2, 3].map((n, i) => ({
      id: `t-${i}`,
      execute: async () => n * 10,
    }));
    const res = await parallelLimit(tasks, 2);
    expect(res.map((r) => r.result)).toEqual([10, 20, 30]);
    expect(res.every((r) => r.success)).toBe(true);
  });

  it('captures task errors without aborting siblings', async () => {
    const tasks = [
      { id: 'a-0', execute: async () => { throw new Error('boom'); } },
      { id: 'b-1', execute: async () => 'ok' },
    ];
    const res = await parallelLimit(tasks, 2);
    expect(res[0].success).toBe(false);
    expect(res[0].error?.message).toBe('boom');
    expect(res[1].success).toBe(true);
    expect(res[1].result).toBe('ok');
  });

  it('never exceeds the concurrency limit', async () => {
    let active = 0;
    let maxActive = 0;
    const tasks = Array.from({ length: 8 }, (_, i) => ({
      id: `t-${i}`,
      execute: async () => {
        active++;
        maxActive = Math.max(maxActive, active);
        await delay(10);
        active--;
        return i;
      },
    }));
    await parallelLimit(tasks, 3);
    expect(maxActive).toBeLessThanOrEqual(3);
  });

  it('stops launching tasks after cancellation', async () => {
    const executed: number[] = [];
    const cancelRef = { current: false };
    const tasks = Array.from({ length: 5 }, (_, i) => ({
      id: `t-${i}`,
      execute: async () => {
        executed.push(i);
        if (i === 1) cancelRef.current = true;
        return i;
      },
    }));
    await parallelLimit(tasks, 1, undefined, cancelRef);
    expect(executed).toEqual([0, 1]);
  });

  it('reports monotonically increasing completion counts', async () => {
    const seen: number[] = [];
    const tasks = [0, 1, 2].map((i) => ({ id: `t-${i}`, execute: async () => i }));
    await parallelLimit(tasks, 2, (completed) => seen.push(completed));
    expect(seen[seen.length - 1]).toBe(3);
    expect([...seen].sort((a, b) => a - b)).toEqual(seen);
  });

  it('waits while rate-limit pause is active', async () => {
    const pauseRef = { current: true };
    const tasks = [{ id: 't-0', execute: async () => 'done' }];
    const promise = parallelLimit(tasks, 1, undefined, undefined, pauseRef);

    // Release the pause shortly after starting.
    setTimeout(() => { pauseRef.current = false; }, 30);
    const res = await promise;
    expect(res[0].result).toBe('done');
  });
});

describe('parallel settings persistence', () => {
  beforeEach(() => localStorage.clear());

  it('returns defaults when nothing is stored', () => {
    expect(loadParallelSettings()).toEqual({
      mode: 'sequential',
      maxConcurrent: 3,
      requestDelay: 200,
    });
  });

  it('round-trips saved settings', () => {
    saveParallelSettings({ mode: 'full-parallel', maxConcurrent: 5, requestDelay: 0 });
    expect(loadParallelSettings()).toEqual({
      mode: 'full-parallel',
      maxConcurrent: 5,
      requestDelay: 0,
    });
  });

  it('persists partial updates', () => {
    saveParallelSettings({ maxConcurrent: 8 });
    expect(localStorage.getItem('ai-max-concurrent')).toBe('8');
    // Untouched keys keep their defaults on load
    expect(loadParallelSettings().mode).toBe('sequential');
  });
});
