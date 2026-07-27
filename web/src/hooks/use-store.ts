/**
 * Store hooks for state management.
 *
 * useWebSocket  - Connection to backend
 * useRecipes    - Load & filter recipes
 * useCart       - Cart state with localStorage persistence
 * useCategories - Category list
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useTranslation } from '@/contexts/LanguageContext';
import { storeWs } from '@/lib/websocket';
import type {
  Recipe,
  Category,
  CartItem,
  CartState,
  ConnectionStatus,
  ServerMessage,
  SystemInfo,
  InstallRecipe,
  InstallMethod,
  PackagingMode,
  InstallMode,
} from '@/lib/types';

// ============================================
// useWebSocket
// ============================================

export function useWebSocket() {
  const [status, setStatus] = useState<ConnectionStatus>(storeWs.status);
  const [lastMessage, setLastMessage] = useState<ServerMessage | null>(null);
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);

  useEffect(() => {
    const unsubStatus = storeWs.onStatusChange(setStatus);
    const unsubMessage = storeWs.onMessage((msg) => {
      console.log('[useWebSocket] Message received:', msg.type);
      // Intercept system_info and store it separately
      if (msg.type === 'system_info') {
        setSystemInfo({
          codename: msg.codename,
          id: msg.id,
          name: msg.name,
          version_id: msg.version_id,
          arch: msg.arch,
          is_native: msg.is_native,
        });
      } else {
        console.log('[useWebSocket] Setting lastMessage to:', msg.type);
        setLastMessage(msg);
      }
    });
    storeWs.connect();

    return () => {
      unsubStatus();
      unsubMessage();
    };
  }, []);

  const sendInstall = useCallback((recipes: InstallRecipe[], mode: InstallMode, packaging: PackagingMode) => {
    console.log('[useWebSocket] Sending install request:', { recipes, mode, packaging });
    // packaging only applies to module mode
    if (mode === 'module') {
      return storeWs.send({ type: 'install', recipes, mode, packaging });
    }
    return storeWs.send({ type: 'install', recipes, mode });
  }, []);

  const sendCancel = useCallback(() => {
    return storeWs.send({ type: 'cancel' });
  }, []);

  return { status, lastMessage, systemInfo, sendInstall, sendCancel };
}

// ============================================
// useCart (localStorage persisted)
// ============================================

const CART_KEY = 'minios-store-cart';

function loadCart(): CartItem[] {
  try {
    const raw = localStorage.getItem(CART_KEY);
    if (raw) {
      const state = JSON.parse(raw) as CartState;
      return state.items || [];
    }
  } catch {
    // Corrupted, reset
  }
  return [];
}

function saveCart(items: CartItem[]): void {
  const state: CartState = { items, updatedAt: Date.now() };
  localStorage.setItem(CART_KEY, JSON.stringify(state));
}

/** Result of attempting to add an item to the cart */
export interface CartAddResult {
  success: boolean;
  /** Translation key for the error reason (only set when success=false) */
  reason?: string;
}

/**
 * Check if a recipe method can be added to a cart that already contains items with known methods.
 *
 * Rules (based on MiniOS tools apt2sb / script2sb):
 * - apt + apt → OK (multiple packages in one apt2sb call)
 * - apt + deb → OK (deb is just an argument to apt2sb)
 * - deb + deb → OK
 * - script → ALWAYS alone. Cannot combine with anything.
 */
function checkCartCompatibility(
  existingMethods: InstallMethod[],
  newMethod: InstallMethod,
): CartAddResult {
  // Empty cart — anything goes
  if (existingMethods.length === 0) {
    return { success: true };
  }

  // Scripts can never be combined
  if (newMethod === 'script') {
    return { success: false, reason: 'Scripts cannot be combined with other items' };
  }

  // Cart already has a script — nothing else can be added
  if (existingMethods.includes('script')) {
    return { success: false, reason: 'Cannot add items when a script is in the cart' };
  }

  // apt + apt, apt + deb, deb + deb — all OK
  return { success: true };
}

export function useCart(recipes: Recipe[]) {
  const [items, setItems] = useState<CartItem[]>(() => loadCart());
  const [installMode, setInstallMode] = useState<InstallMode>('module');
  const [packaging, setPackaging] = useState<PackagingMode>('single');
  const [moduleName, setModuleName] = useState<string>('');

  // Build a lookup map for recipe methods
  const recipeMap = useMemo(() => {
    const map = new Map<string, Recipe>();
    for (const r of recipes) {
      map.set(r.id, r);
    }
    return map;
  }, [recipes]);

  // Persist on change
  useEffect(() => {
    saveCart(items);
  }, [items]);

  /** Get install methods of current cart items */
  const getCartMethods = useCallback((currentItems: CartItem[]): InstallMethod[] => {
    return currentItems
      .map(item => recipeMap.get(item.recipeId)?.method)
      .filter((m): m is InstallMethod => m !== undefined);
  }, [recipeMap]);

  const addItem = useCallback((recipeId: string): CartAddResult => {
    const recipe = recipeMap.get(recipeId);
    if (!recipe) {
      return { success: false, reason: 'Recipe not found' };
    }

    // Use a ref-like pattern: read current state synchronously via setState callback
    let result: CartAddResult = { success: true };

    setItems(prev => {
      if (prev.some(item => item.recipeId === recipeId)) return prev;

      const existingMethods = getCartMethods(prev);
      const check = checkCartCompatibility(existingMethods, recipe.method);
      if (!check.success) {
        result = check;
        return prev; // Don't modify
      }

      return [...prev, { recipeId }];
    });

    return result;
  }, [recipeMap, getCartMethods]);

  const removeItem = useCallback((recipeId: string) => {
    setItems(prev => prev.filter(item => item.recipeId !== recipeId));
  }, []);

  const clearCart = useCallback(() => {
    setItems([]);
  }, []);

  const isInCart = useCallback((recipeId: string) => {
    return items.some(item => item.recipeId === recipeId);
  }, [items]);

  const toggleItem = useCallback((recipeId: string): CartAddResult => {
    const recipe = recipeMap.get(recipeId);
    if (!recipe) {
      return { success: false, reason: 'Recipe not found' };
    }

    let result: CartAddResult = { success: true };

    setItems(prev => {
      // If already in cart — remove (always succeeds)
      if (prev.some(item => item.recipeId === recipeId)) {
        return prev.filter(item => item.recipeId !== recipeId);
      }

      // Adding — check compatibility
      const existingMethods = getCartMethods(prev);
      const check = checkCartCompatibility(existingMethods, recipe.method);
      if (!check.success) {
        result = check;
        return prev;
      }

      return [...prev, { recipeId }];
    });

    return result;
  }, [recipeMap, getCartMethods]);

  return {
    items, addItem, removeItem, clearCart, isInCart, toggleItem,
    installMode, setInstallMode,
    packaging, setPackaging,
    moduleName, setModuleName,
  };
}

// ============================================
// useRecipes (loads lightweight index from /data/recipes-index.json)
// ============================================

// Get base URL for assets
const getBaseUrl = () => import.meta.env.BASE_URL || '/';

/** Recipe translation fields (matches recipe-translations/{lang}/{id}.json) */
interface RecipeTranslation {
  name?: string;
  description?: string;
  longDescription?: string;
}

/** Recipe detail fields loaded on demand */
interface RecipeDetail {
  longDescription?: string;
  script?: string;
  screenshots?: string[];
}

// Cache for loaded recipe details (avoids re-fetching)
const recipeDetailCache = new Map<string, RecipeDetail>();

/**
 * Load full detail for a single recipe (longDescription, script, screenshots).
 * Results are cached in-memory so repeated opens are instant.
 */
export async function loadRecipeDetail(recipeId: string, language?: string): Promise<RecipeDetail> {
  const cacheKey = language && language !== 'en' ? `${recipeId}:${language}` : recipeId;
  const cached = recipeDetailCache.get(cacheKey);
  if (cached) return cached;

  const baseUrl = getBaseUrl();

  // Load base detail
  let detail: RecipeDetail = {};
  try {
    const res = await fetch(`${baseUrl}data/recipes/${recipeId}.json`);
    if (res.ok) {
      detail = await res.json();
    }
  } catch {
    // No detail file — recipe has no longDescription/script/screenshots
  }

  // Overlay translation if non-English
  if (language && language !== 'en') {
    try {
      const trRes = await fetch(`${baseUrl}data/recipe-translations/${language}/${recipeId}.json`);
      if (trRes.ok) {
        const tr: RecipeTranslation = await trRes.json();
        if (tr.longDescription) {
          detail = { ...detail, longDescription: tr.longDescription };
        }
      }
    } catch {
      // No translation — use base
    }
  }

  // Cache the base (English) detail always; translated detail under language-specific key
  if (!recipeDetailCache.has(recipeId)) {
    recipeDetailCache.set(recipeId, detail);
  }
  recipeDetailCache.set(cacheKey, detail);

  return detail;
}

/**
 * Load recipes with language-aware pre-translated index.
 *
 * Loads the lightweight index (without longDescription/script/screenshots)
 * for fast browsing, search, and filtering. Full details are loaded on
 * demand via loadRecipeDetail() when the user opens an app detail modal.
 *
 * Translation strategy (aggregated index):
 * - English: loads recipes-index.json
 * - Other languages: loads recipes-index.{lang}.json (pre-merged at build time)
 *   Falls back to recipes-index.json if the translated index is unavailable.
 * - Keeps English base in a ref for instant fallback on language switch.
 */
export function useRecipes() {
  const { language } = useTranslation();
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Keep base (English) recipes in a ref so switching back to English is instant.
  const baseRecipesRef = useRef<Recipe[]>([]);

  // Load recipes whenever language changes.
  // For English: load recipes-index.json (and cache as base).
  // For other languages: load recipes-index.{lang}.json, fall back to English base.
  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const baseUrl = getBaseUrl();
        let list: Recipe[] | null = null;

        if (language === 'en') {
          // English: load base index
          list = await fetchIndex(baseUrl, 'en');
          if (!cancelled && list) {
            baseRecipesRef.current = list;
          }
        } else {
          // Non-English: try pre-translated aggregated index
          list = await fetchIndex(baseUrl, language);

          // Also load English base in background if not yet cached
          if (baseRecipesRef.current.length === 0) {
            const base = await fetchIndex(baseUrl, 'en');
            if (!cancelled && base) {
              baseRecipesRef.current = base;
            }
          }

          // Fall back to English base if translated index unavailable
          if (!list) {
            list = baseRecipesRef.current;
          }
        }

        if (!cancelled) {
          setRecipes(list || []);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load recipes');
          setLoading(false);
        }
      }
    }

    load();
    return () => { cancelled = true; };
  }, [language]);

  return { recipes, loading, error, setRecipes };
}

/**
 * Fetch a recipe index file. Returns the parsed array or null on failure.
 * For 'en', tries /api/recipes (dev) then recipes-index.json.
 * For other languages, tries recipes-index.{lang}.json.
 */
async function fetchIndex(baseUrl: string, lang: string): Promise<Recipe[] | null> {
  const urls: string[] = [];

  if (lang === 'en') {
    if (import.meta.env.DEV) {
      urls.push('/api/recipes');
    }
    urls.push(`${baseUrl}data/recipes-index.json`);
  } else {
    if (import.meta.env.DEV) {
      urls.push(`/api/recipes-index/${lang}`);
    }
    urls.push(`${baseUrl}data/recipes-index.${lang}.json`);
  }

  for (const url of urls) {
    try {
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        const list: Recipe[] = Array.isArray(data) ? data : data.recipes || [];
        return list;
      }
    } catch {
      // Try next URL
    }
  }

  return null;
}

// ============================================
// useCategories (loads from /data/categories.json or Vite API)
// ============================================

/** Default categories used when no external data is available */
const DEFAULT_CATEGORIES: Category[] = [
  { id: 'internet', nameKey: 'category.internet', name: 'Internet', icon: 'Globe', order: 1 },
  { id: 'multimedia', nameKey: 'category.multimedia', name: 'Multimedia', icon: 'Music', order: 2 },
  { id: 'office', nameKey: 'category.office', name: 'Office', icon: 'FileText', order: 3 },
  { id: 'development', nameKey: 'category.development', name: 'Development', icon: 'Code', order: 4 },
  { id: 'games', nameKey: 'category.games', name: 'Games', icon: 'Gamepad2', order: 5 },
  { id: 'graphics', nameKey: 'category.graphics', name: 'Graphics', icon: 'Palette', order: 6 },
  { id: 'system', nameKey: 'category.system', name: 'System', icon: 'Wrench', order: 7 },
  { id: 'security', nameKey: 'category.security', name: 'Security', icon: 'Shield', order: 8 },
  { id: 'science', nameKey: 'category.science', name: 'Science', icon: 'Cpu', order: 9 },
  { id: 'other', nameKey: 'category.other', name: 'Other', icon: 'Package', order: 99 },
];

export function useCategories() {
  const [categories, setCategories] = useState<Category[]>(DEFAULT_CATEGORIES);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const urls = import.meta.env.DEV
          ? ['/api/categories', '/data/categories.json']
          : ['/data/categories.json'];

        for (const url of urls) {
          try {
            const res = await fetch(url);
            if (res.ok) {
              const data = await res.json();
              if (!cancelled) {
                const cats = Array.isArray(data) ? data : data.categories || [];
                if (cats.length > 0) {
                  setCategories(cats);
                }
                setLoading(false);
                return;
              }
            }
          } catch {
            // Try next
          }
        }

        // Keep defaults
        if (!cancelled) setLoading(false);
      } catch {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, []);

  return { categories, loading, setCategories };
}

// ============================================
// useStoreFilter (search, category, sort)
// ============================================

export interface StoreFilterState {
  search: string;
  categoryId: string | null;
  sortBy: 'name' | 'category';
}

export function useStoreFilter(recipes: Recipe[], categories: Category[], distroCodename?: string | null, systemArch?: string | null) {
  const [filter, setFilter] = useState<StoreFilterState>({
    search: '',
    categoryId: null,
    sortBy: 'name',
  });

  const filteredRecipes = useMemo(() => {
    let result = recipes.filter(r => r.enabled !== false);

    // Distribution + architecture compatibility filter (unified)
    if (distroCodename || systemArch) {
      result = result.filter(r => {
        if (!r.distributions) return true; // no filter = available everywhere

        // Check include list
        if (r.distributions.include && r.distributions.include.length > 0) {
          const match = r.distributions.include.find(entry => {
            if (!distroCodename) return true; // no codename known, skip name check
            if (entry.name !== distroCodename) return false;
            if (!systemArch) return true; // no arch known, name match is enough
            if (!entry.architectures || entry.architectures.length === 0) return true; // no arch restriction
            return entry.architectures.includes(systemArch);
          });
          if (!match) return false;
        }

        // Check exclude list
        if (r.distributions.exclude && r.distributions.exclude.length > 0) {
          const excluded = r.distributions.exclude.find(entry => {
            if (!distroCodename) return false; // no codename known, can't match exclude
            if (entry.name !== distroCodename) return false;
            if (!systemArch) return true; // no arch known but name matches = excluded
            if (!entry.architectures || entry.architectures.length === 0) return true; // exclude whole distro
            return entry.architectures.includes(systemArch);
          });
          if (excluded) return false;
        }

        return true;
      });
    }

    // Category filter
    if (filter.categoryId) {
      result = result.filter(r => r.categoryId === filter.categoryId);
    }

    // Search filter
    if (filter.search.trim()) {
      const q = filter.search.toLowerCase().trim();
      result = result.filter(r =>
        r.name.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        (r.tags && Array.isArray(r.tags) && r.tags.some(t => typeof t === 'string' && t.toLowerCase().includes(q))) ||
        (r.packages && Array.isArray(r.packages) && r.packages.some(p => typeof p === 'string' && p.toLowerCase().includes(q)))
      );
    }

    // Sort
    const categoryOrder = new Map(categories.map(c => [c.id, c.order]));
    result.sort((a, b) => {
      if (filter.sortBy === 'category') {
        const orderA = categoryOrder.get(a.categoryId) ?? 999;
        const orderB = categoryOrder.get(b.categoryId) ?? 999;
        if (orderA !== orderB) return orderA - orderB;
      }
      // Within same category or by name: sort by order then name
      if (a.order !== undefined && b.order !== undefined && a.order !== b.order) {
        return a.order - b.order;
      }
      return a.name.localeCompare(b.name);
    });

    return result;
  }, [recipes, categories, filter, distroCodename, systemArch]);

  const setSearch = useCallback((search: string) => {
    setFilter(prev => ({ ...prev, search }));
  }, []);

  const setCategory = useCallback((categoryId: string | null) => {
    setFilter(prev => ({ ...prev, categoryId }));
  }, []);

  const setSortBy = useCallback((sortBy: 'name' | 'category') => {
    setFilter(prev => ({ ...prev, sortBy }));
  }, []);

  return { filter, filteredRecipes, setSearch, setCategory, setSortBy };
}
