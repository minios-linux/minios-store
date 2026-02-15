/**
 * Utility for parallel translation with configurable concurrency and rate limit handling
 */

export type ParallelMode = 'sequential' | 'parallel-langs' | 'parallel-chunks' | 'full-parallel';

export interface ParallelTranslationSettings {
  mode: ParallelMode;
  maxConcurrent: number;
  requestDelay: number;
}

export interface ParallelTranslationTask<T> {
  id: string;
  execute: () => Promise<T>;
}

export interface ParallelProgressInfo {
  lang?: string;
  chunk?: number;
  total?: number;
}

/**
 * Execute tasks in parallel with configurable concurrency limit
 */
export async function parallelLimit<T>(
  tasks: ParallelTranslationTask<T>[],
  limit: number,
  onProgress?: (completed: number, active: ParallelProgressInfo[]) => void,
  cancelRef?: { current: boolean },
  rateLimitPauseRef?: { current: boolean },
  requestDelay = 0
): Promise<Array<{ success: boolean; result?: T; error?: Error }>> {
  const results: Array<{ success: boolean; result?: T; error?: Error }> = [];
  const executing: Array<{ promise: Promise<void>; info: ParallelProgressInfo }> = [];
  let completedCount = 0;

  for (let i = 0; i < tasks.length; i++) {
    // Check for cancellation
    if (cancelRef?.current) {
      console.log('[parallelLimit] Cancelled by user');
      break;
    }

    const task = tasks[i];
    
    // Delay before starting this task
    if (requestDelay > 0 && i > 0) {
      await new Promise(resolve => setTimeout(resolve, requestDelay));
    }

    const promise = (async () => {
      // Wait if rate limited
      while (rateLimitPauseRef?.current) {
        await new Promise(resolve => setTimeout(resolve, 100));
      }

      try {
        const result = await task.execute();
        results[i] = { success: true, result };
      } catch (error) {
        console.error(`[parallelLimit] Task ${task.id} failed:`, error);
        results[i] = { success: false, error: error as Error };
      } finally {
        completedCount++;
        // Remove this task from executing array
        const idx = executing.findIndex(e => e.promise === promise);
        if (idx >= 0) executing.splice(idx, 1);
        
        // Report progress
        if (onProgress) {
          const activeInfo = executing.map(e => e.info);
          onProgress(completedCount, activeInfo);
        }
      }
    })();

    // Extract info from task id (format: "lang-chunk" or "lang")
    const info: ParallelProgressInfo = {};
    const parts = task.id.split('-');
    if (parts.length >= 1) info.lang = parts[0];
    if (parts.length >= 2 && !isNaN(parseInt(parts[1]))) {
      info.chunk = parseInt(parts[1]) + 1; // +1 for display (0-indexed -> 1-indexed)
    }

    executing.push({ promise, info });

    // Wait if we've hit the concurrency limit
    if (executing.length >= limit) {
      await Promise.race(executing.map(e => e.promise));
    }
  }

  // Wait for remaining tasks
  await Promise.all(executing.map(e => e.promise));

  return results;
}

/**
 * Load parallelization settings from localStorage
 */
export function loadParallelSettings(): ParallelTranslationSettings {
  const mode = (localStorage.getItem('ai-parallel-mode') as ParallelMode) || 'sequential';
  const maxConcurrent = parseInt(localStorage.getItem('ai-max-concurrent') || '3', 10);
  const requestDelay = parseInt(localStorage.getItem('ai-request-delay') || '200', 10);
  
  return { mode, maxConcurrent, requestDelay };
}

/**
 * Save parallelization settings to localStorage
 */
export function saveParallelSettings(settings: Partial<ParallelTranslationSettings>): void {
  if (settings.mode) localStorage.setItem('ai-parallel-mode', settings.mode);
  if (settings.maxConcurrent !== undefined) {
    localStorage.setItem('ai-max-concurrent', String(settings.maxConcurrent));
  }
  if (settings.requestDelay !== undefined) {
    localStorage.setItem('ai-request-delay', String(settings.requestDelay));
  }
}
