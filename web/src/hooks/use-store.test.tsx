import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

// use-store.ts imports the language context at module load (used by useRecipes).
// Mock it so the hook module can be imported without pulling in i18next.
vi.mock('@/contexts/LanguageContext', () => ({
  useTranslation: () => ({ language: 'en', t: (k: string) => k, setLanguage: () => {} }),
}));

// Controllable WebSocket handlers, shared with the mocked singleton below.
const wsMock = vi.hoisted(() => ({
  messageHandlers: new Set<(m: unknown) => void>(),
  statusHandlers: new Set<(s: string) => void>(),
  connect: undefined as unknown,
  send: undefined as unknown,
}));

vi.mock('@/lib/websocket', () => {
  wsMock.connect = vi.fn();
  wsMock.send = vi.fn(() => true);
  return {
    storeWs: {
      status: 'disconnected',
      connect: wsMock.connect,
      send: wsMock.send,
      onMessage: (h: (m: unknown) => void) => {
        wsMock.messageHandlers.add(h);
        return () => wsMock.messageHandlers.delete(h);
      },
      onStatusChange: (h: (s: string) => void) => {
        wsMock.statusHandlers.add(h);
        return () => wsMock.statusHandlers.delete(h);
      },
    },
    installViaUriScheme: vi.fn(),
  };
});

import {
  useCart,
  useStoreFilter,
  loadRecipeDetail,
  useWebSocket,
  useRecipes,
  useCategories,
} from './use-store';
import { storeWs } from '@/lib/websocket';
import type { Recipe } from '@/lib/types';

const recipe = (over: Partial<Recipe>): Recipe => ({
  id: 'x',
  name: 'X',
  description: '',
  categoryId: 'system',
  icon: 'Package',
  method: 'apt',
  level: 'auto',
  compression: 'zstd',
  ...over,
});

// ---------------------------------------------------------------------------
// useCart
// ---------------------------------------------------------------------------

describe('useCart', () => {
  const recipes: Recipe[] = [
    recipe({ id: 'vlc', method: 'apt' }),
    recipe({ id: 'gimp', method: 'apt' }),
    recipe({ id: 'deb1', method: 'deb' }),
    recipe({ id: 'scr', method: 'script' }),
  ];

  beforeEach(() => localStorage.clear());

  it('adds and removes an item', () => {
    const { result } = renderHook(() => useCart(recipes));
    act(() => { result.current.addItem('vlc'); });
    expect(result.current.isInCart('vlc')).toBe(true);
    act(() => { result.current.removeItem('vlc'); });
    expect(result.current.isInCart('vlc')).toBe(false);
  });

  it('ignores unknown recipes', () => {
    const { result } = renderHook(() => useCart(recipes));
    act(() => { result.current.addItem('nope'); });
    expect(result.current.items).toHaveLength(0);
  });

  it('does not add duplicates', () => {
    const { result } = renderHook(() => useCart(recipes));
    act(() => { result.current.addItem('vlc'); });
    act(() => { result.current.addItem('vlc'); });
    expect(result.current.items).toHaveLength(1);
  });

  it('allows combining apt and deb', () => {
    const { result } = renderHook(() => useCart(recipes));
    act(() => { result.current.addItem('vlc'); });
    act(() => { result.current.addItem('deb1'); });
    expect(result.current.items.map((i) => i.recipeId).sort()).toEqual(['deb1', 'vlc']);
  });

  it('refuses to add a script alongside other items', () => {
    const { result } = renderHook(() => useCart(recipes));
    act(() => { result.current.addItem('vlc'); });
    act(() => { result.current.addItem('scr'); });
    expect(result.current.isInCart('scr')).toBe(false);
    expect(result.current.items).toHaveLength(1);
  });

  it('refuses to add anything once a script is present', () => {
    const { result } = renderHook(() => useCart(recipes));
    act(() => { result.current.addItem('scr'); });
    act(() => { result.current.addItem('vlc'); });
    expect(result.current.isInCart('vlc')).toBe(false);
    expect(result.current.items).toHaveLength(1);
  });

  it('toggles items on and off', () => {
    const { result } = renderHook(() => useCart(recipes));
    act(() => { result.current.toggleItem('vlc'); });
    expect(result.current.isInCart('vlc')).toBe(true);
    act(() => { result.current.toggleItem('vlc'); });
    expect(result.current.isInCart('vlc')).toBe(false);
  });

  it('clears the whole cart', () => {
    const { result } = renderHook(() => useCart(recipes));
    act(() => { result.current.addItem('vlc'); });
    act(() => { result.current.addItem('gimp'); });
    act(() => { result.current.clearCart(); });
    expect(result.current.items).toHaveLength(0);
  });

  it('persists the cart to localStorage', () => {
    const { result } = renderHook(() => useCart(recipes));
    act(() => { result.current.addItem('vlc'); });
    const raw = localStorage.getItem('minios-store-cart');
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw as string).items).toEqual([{ recipeId: 'vlc' }]);
  });

  it('restores an existing cart from localStorage', () => {
    localStorage.setItem(
      'minios-store-cart',
      JSON.stringify({ items: [{ recipeId: 'gimp' }], updatedAt: 1 }),
    );
    const { result } = renderHook(() => useCart(recipes));
    expect(result.current.isInCart('gimp')).toBe(true);
  });

  it('exposes install mode / packaging setters', () => {
    const { result } = renderHook(() => useCart(recipes));
    act(() => { result.current.setInstallMode('system'); });
    act(() => { result.current.setPackaging('separate'); });
    act(() => { result.current.setModuleName('bundle'); });
    expect(result.current.installMode).toBe('system');
    expect(result.current.packaging).toBe('separate');
    expect(result.current.moduleName).toBe('bundle');
  });
});

// ---------------------------------------------------------------------------
// useStoreFilter
// ---------------------------------------------------------------------------

describe('useStoreFilter', () => {
  const recipes: Recipe[] = [
    recipe({ id: 'vlc', name: 'VLC', categoryId: 'multimedia', description: 'media player', tags: ['video'], order: 2 }),
    recipe({ id: 'firefox', name: 'Firefox', categoryId: 'internet', description: 'web browser', packages: ['firefox'], order: 1 }),
    recipe({ id: 'gimp', name: 'GIMP', categoryId: 'graphics', description: 'image editor', enabled: false }),
    recipe({ id: 'code', name: 'VS Code', categoryId: 'development', description: 'editor', order: 3 }),
  ];
  const categories = [
    { id: 'internet', nameKey: '', name: 'Internet', icon: '', order: 1 },
    { id: 'multimedia', nameKey: '', name: 'Multimedia', icon: '', order: 2 },
    { id: 'graphics', nameKey: '', name: 'Graphics', icon: '', order: 3 },
    { id: 'development', nameKey: '', name: 'Dev', icon: '', order: 4 },
  ];

  it('excludes disabled recipes', () => {
    const { result } = renderHook(() => useStoreFilter(recipes, categories));
    expect(result.current.filteredRecipes.map((r) => r.id)).not.toContain('gimp');
  });

  it('sorts by order then name', () => {
    const { result } = renderHook(() => useStoreFilter(recipes, categories));
    expect(result.current.filteredRecipes.map((r) => r.name)).toEqual([
      'Firefox', 'VLC', 'VS Code',
    ]);
  });

  it('searches across name, description, tags and packages', () => {
    const { result } = renderHook(() => useStoreFilter(recipes, categories));

    act(() => result.current.setSearch('browser'));
    expect(result.current.filteredRecipes.map((r) => r.id)).toEqual(['firefox']);

    act(() => result.current.setSearch('video'));
    expect(result.current.filteredRecipes.map((r) => r.id)).toEqual(['vlc']);

    act(() => result.current.setSearch('firefox'));
    expect(result.current.filteredRecipes.map((r) => r.id)).toEqual(['firefox']);
  });

  it('filters by category', () => {
    const { result } = renderHook(() => useStoreFilter(recipes, categories));
    act(() => result.current.setCategory('internet'));
    expect(result.current.filteredRecipes.map((r) => r.id)).toEqual(['firefox']);
  });

  it('filters by distribution include list', () => {
    const distroRecipes: Recipe[] = [
      recipe({ id: 'a', distributions: { include: [{ name: 'bookworm', architectures: ['amd64'] }] } }),
      recipe({ id: 'b', distributions: { include: [{ name: 'trixie' }] } }),
      recipe({ id: 'c' }),
    ];
    const { result } = renderHook(() => useStoreFilter(distroRecipes, [], 'bookworm', 'amd64'));
    expect(result.current.filteredRecipes.map((r) => r.id).sort()).toEqual(['a', 'c']);
  });

  it('excludes recipes whose arch does not match the include entry', () => {
    const distroRecipes: Recipe[] = [
      recipe({ id: 'a', distributions: { include: [{ name: 'bookworm', architectures: ['i386'] }] } }),
    ];
    const { result } = renderHook(() => useStoreFilter(distroRecipes, [], 'bookworm', 'amd64'));
    expect(result.current.filteredRecipes.map((r) => r.id)).toEqual([]);
  });

  it('applies the exclude list', () => {
    const distroRecipes: Recipe[] = [
      recipe({ id: 'a', distributions: { exclude: [{ name: 'bookworm' }] } }),
      recipe({ id: 'b' }),
    ];
    const { result } = renderHook(() => useStoreFilter(distroRecipes, [], 'bookworm', 'amd64'));
    expect(result.current.filteredRecipes.map((r) => r.id)).toEqual(['b']);
  });

  it('changes sort mode to category', () => {
    const { result } = renderHook(() => useStoreFilter(recipes, categories));
    act(() => result.current.setSortBy('category'));
    expect(result.current.filter.sortBy).toBe('category');
  });
});

// ---------------------------------------------------------------------------
// loadRecipeDetail
// ---------------------------------------------------------------------------

describe('loadRecipeDetail', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('fetches and returns the detail payload', async () => {
    const detail = { longDescription: 'Long', script: 'echo hi', screenshots: ['/s.png'] };
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => detail })));
    const res = await loadRecipeDetail('detail-unique-1');
    expect(res.longDescription).toBe('Long');
    expect(res.script).toBe('echo hi');
  });

  it('returns an empty object when the request fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network'); }));
    const res = await loadRecipeDetail('detail-unique-2');
    expect(res).toEqual({});
  });

  it('overlays a non-English translation over the base detail', async () => {
    const base = { longDescription: 'English', script: 'echo' };
    const tr = { longDescription: 'Traducido' };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => base })
      .mockResolvedValueOnce({ ok: true, json: async () => tr });
    vi.stubGlobal('fetch', fetchMock);

    const res = await loadRecipeDetail('detail-unique-3', 'ru');
    expect(res.longDescription).toBe('Traducido');
    expect(res.script).toBe('echo');
  });

  it('caches results so repeated calls skip the network', async () => {
    const detail = { longDescription: 'Cached' };
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => detail }));
    vi.stubGlobal('fetch', fetchMock);

    await loadRecipeDetail('detail-unique-4');
    const callsAfterFirst = fetchMock.mock.calls.length;
    await loadRecipeDetail('detail-unique-4');
    expect(fetchMock.mock.calls.length).toBe(callsAfterFirst);
  });
});

// ---------------------------------------------------------------------------
// useWebSocket
// ---------------------------------------------------------------------------

describe('useWebSocket', () => {
  beforeEach(() => {
    wsMock.messageHandlers.clear();
    wsMock.statusHandlers.clear();
    vi.clearAllMocks();
  });

  it('connects on mount', () => {
    renderHook(() => useWebSocket());
    expect(storeWs.connect).toHaveBeenCalled();
  });

  it('captures system_info separately from other messages', () => {
    const { result } = renderHook(() => useWebSocket());

    act(() => {
      wsMock.messageHandlers.forEach((h) =>
        h({
          type: 'system_info',
          codename: 'trixie',
          id: 'minios',
          name: 'MiniOS',
          version_id: '5',
          arch: 'amd64',
          is_native: false,
        }),
      );
    });
    expect(result.current.systemInfo?.codename).toBe('trixie');
    expect(result.current.lastMessage).toBeNull();

    act(() => {
      wsMock.messageHandlers.forEach((h) => h({ type: 'pong' }));
    });
    expect(result.current.lastMessage).toEqual({ type: 'pong' });
  });

  it('reflects status changes', () => {
    const { result } = renderHook(() => useWebSocket());
    act(() => {
      wsMock.statusHandlers.forEach((h) => h('connected'));
    });
    expect(result.current.status).toBe('connected');
  });

  it('sendInstall includes packaging only for module mode', () => {
    const { result } = renderHook(() => useWebSocket());
    const recipes = [{ id: 'vlc', name: 'VLC', method: 'apt', level: 'auto', compression: 'zstd' }];

    act(() => { result.current.sendInstall(recipes as never, 'module', 'single'); });
    expect(storeWs.send).toHaveBeenCalledWith({
      type: 'install', recipes, mode: 'module', packaging: 'single',
    });

    act(() => { result.current.sendInstall(recipes as never, 'system', 'single'); });
    expect(storeWs.send).toHaveBeenCalledWith({
      type: 'install', recipes, mode: 'system',
    });
  });

  it('sendCancel emits a cancel message', () => {
    const { result } = renderHook(() => useWebSocket());
    act(() => { result.current.sendCancel(); });
    expect(storeWs.send).toHaveBeenCalledWith({ type: 'cancel' });
  });
});

// ---------------------------------------------------------------------------
// useRecipes / useCategories (async loaders, mocked fetch)
// ---------------------------------------------------------------------------

describe('useRecipes', () => {
  beforeEach(() => vi.unstubAllGlobals());

  it('loads the recipe index', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => [recipe({ id: 'vlc', name: 'VLC' })],
    })));
    const { result } = renderHook(() => useRecipes());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.recipes.map((r) => r.id)).toEqual(['vlc']);
  });

  it('accepts a wrapped { recipes: [...] } payload', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => ({ recipes: [recipe({ id: 'gimp', name: 'GIMP' })] }),
    })));
    const { result } = renderHook(() => useRecipes());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.recipes.map((r) => r.id)).toEqual(['gimp']);
  });

  it('ends loading with an empty list when all fetches fail', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false })));
    const { result } = renderHook(() => useRecipes());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.recipes).toEqual([]);
  });
});

describe('useCategories', () => {
  beforeEach(() => vi.unstubAllGlobals());

  it('loads categories from the endpoint', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => [{ id: 'custom', nameKey: '', name: 'Custom', icon: '', order: 1 }],
    })));
    const { result } = renderHook(() => useCategories());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.categories.map((c) => c.id)).toContain('custom');
  });

  it('keeps default categories when loading fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network'); }));
    const { result } = renderHook(() => useCategories());
    await waitFor(() => expect(result.current.loading).toBe(false));
    // Falls back to the built-in defaults
    expect(result.current.categories.length).toBeGreaterThan(0);
    expect(result.current.categories.map((c) => c.id)).toContain('internet');
  });
});
