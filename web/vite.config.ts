import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import fs from 'fs';
import { HttpsProxyAgent } from 'https-proxy-agent';
import type { IncomingMessage, ServerResponse } from 'http';
import type { ViteDevServer, Connect } from 'vite';

// Default timeout for API requests (ms)
const API_TIMEOUT = 30000;

// API response type
interface ApiResponse {
  status: number;
  data: string;
  error?: string;
}

// Helper function to make HTTP requests with timeout and proper error handling
async function apiRequest(
  url: string,
  options: {
    method: 'GET' | 'POST';
    headers?: Record<string, string>;
    body?: string;
    timeout?: number;
    proxyUrl?: string;
  }
): Promise<ApiResponse> {
  const controller = new AbortController();
  const timeout = options.timeout || API_TIMEOUT;
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  console.log(`[API] ${options.method} ${url}${options.proxyUrl ? ` (via proxy)` : ''}`);

  try {
    // Build fetch options
    const fetchOptions: RequestInit & { dispatcher?: unknown } = {
      method: options.method,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      body: options.body,
      signal: controller.signal,
    };

    // Add proxy agent if proxy URL is provided
    if (options.proxyUrl) {
      const agent = new HttpsProxyAgent(options.proxyUrl);
      const https = await import('https');
      const http = await import('http');
      const { URL } = await import('url');

      return new Promise((resolve) => {
        const parsedUrl = new URL(url);
        const isHttps = parsedUrl.protocol === 'https:';
        const requestModule = isHttps ? https : http;

        const reqOptions = {
          hostname: parsedUrl.hostname,
          port: parsedUrl.port || (isHttps ? 443 : 80),
          path: parsedUrl.pathname + parsedUrl.search,
          method: options.method,
          headers: {
            'Content-Type': 'application/json',
            ...options.headers,
          },
          agent: agent,
          timeout: timeout,
        };

        const req = requestModule.request(reqOptions, (res) => {
          res.setEncoding('utf8');
          let data = '';
          res.on('data', (chunk) => { data += chunk; });
          res.on('end', () => {
            clearTimeout(timeoutId);
            console.log(`[API] Response: ${res.statusCode}, ${data.length} bytes`);
            resolve({ status: res.statusCode || 500, data });
          });
        });

        req.on('error', (err) => {
          clearTimeout(timeoutId);
          console.error(`[API] Request failed:`, err.message);
          resolve({
            status: 500,
            data: JSON.stringify({ error: err.message }),
            error: err.message
          });
        });

        req.on('timeout', () => {
          req.destroy();
          clearTimeout(timeoutId);
          console.error(`[API] Request timeout after ${timeout}ms`);
          resolve({
            status: 408,
            data: JSON.stringify({ error: 'Request timeout' }),
            error: 'Request timeout'
          });
        });

        if (options.body) {
          req.write(options.body);
        }
        req.end();
      });
    }

    const response = await fetch(url, fetchOptions);

    clearTimeout(timeoutId);

    const data = await response.text();
    console.log(`[API] Response: ${response.status}, ${data.length} bytes`);

    return { status: response.status, data };
  } catch (error: unknown) {
    clearTimeout(timeoutId);

    const err = error as Error;
    if (err.name === 'AbortError') {
      console.error(`[API] Request timeout after ${timeout}ms`);
      return {
        status: 408,
        data: JSON.stringify({ error: 'Request timeout' }),
        error: 'Request timeout'
      };
    }

    console.error(`[API] Request failed:`, err.message);
    return {
      status: 500,
      data: JSON.stringify({ error: err.message }),
      error: err.message
    };
  }
}

// Helper to parse request body as JSON
function parseRequestBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk: Buffer) => {
      body += chunk.toString('utf8');
    });
    req.on('error', reject);
    req.on('end', () => resolve(body));
  });
}

// Helper to send JSON response
function sendJson(res: ServerResponse, status: number, data: unknown): void {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(typeof data === 'string' ? data : JSON.stringify(data));
}

// ═══════════════════════════════════════════════════════════════
// TRANSLATION HELPERS
// ═══════════════════════════════════════════════════════════════

// Language metadata extracted from translation files
interface LanguageMeta {
  code: string;
  name: string;
  flag: string;
}

// Get list of available languages with metadata from translation files
function getLanguagesWithMeta(): LanguageMeta[] {
  const translationsDir = path.resolve(__dirname, 'public', 'translations');
  if (!fs.existsSync(translationsDir)) {
    return [{ code: 'en', name: 'English', flag: '🇺🇸' }];
  }

  const files = fs.readdirSync(translationsDir);
  const languages: LanguageMeta[] = [];

  for (const file of files) {
    if (!file.endsWith('.json') || file === 'languages.json') continue;

    const code = file.replace('.json', '');
    const filePath = path.resolve(translationsDir, file);

    try {
      const content = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
      const meta = content._meta || {};

      languages.push({
        code,
        name: meta.name || code.toUpperCase(),
        flag: meta.flag || ''
      });
    } catch {
      languages.push({ code, name: code.toUpperCase(), flag: '' });
    }
  }

  return languages.sort((a, b) => a.code.localeCompare(b.code));
}

// Extract translatable keys from store data files (recipes + categories)
function extractTranslatableKeys(): string[] {
  const keys = new Set<string>();

  // Extract from categories.json — nameKey values are translation keys
  const categoriesPath = path.resolve(__dirname, 'public', 'data', 'categories.json');
  if (fs.existsSync(categoriesPath)) {
    try {
      const categories = JSON.parse(fs.readFileSync(categoriesPath, 'utf-8'));
      if (Array.isArray(categories)) {
        for (const cat of categories) {
          if (cat.nameKey && typeof cat.nameKey === 'string') {
            keys.add(cat.nameKey);
          }
        }
      }
    } catch (e) {
      console.error('Failed to parse categories.json:', e);
    }
  }

  // Note: Recipe name/description are translated via RecipeTranslationEditor
  // (separate per-recipe JSON files), not via the UI strings system.
  // So we don't extract recipe fields as translation keys here.

  return Array.from(keys).sort();
}

// Extract t('...') calls from source files
function extractCodeTranslationKeys(): string[] {
  const srcDir = path.resolve(__dirname, 'src');
  const keys = new Set<string>();

  const directPatterns = [
    /\bt\(\s*'([^']+)'\s*\)/g,
    /\bt\(\s*"([^"]+)"\s*\)/g,
    /\bt\(\s*`([^`]+)`\s*\)/g,
  ];

  const fallbackPatterns = [
    /\bt\([^)]+\|\|\s*'([^']+)'\s*\)/g,
    /\bt\([^)]+\|\|\s*"([^"]+)"\s*\)/g,
  ];

  const configPatterns = [
    /(?:labelKey|descriptionKey|titleKey|textKey|messageKey):\s*'([^']+)'/g,
    /(?:labelKey|descriptionKey|titleKey|textKey|messageKey):\s*"([^"]+)"/g,
  ];

  const labelsObjectPattern = /const\s+labels\s*=\s*\{([^}]+)\}/g;
  const labelValuePatterns = [
    /\w+:\s*'([^']+)'/g,
    /\w+:\s*"([^"]+)"/g,
  ];

  function scanFile(filePath: string) {
    const content = fs.readFileSync(filePath, 'utf-8');

    for (const pattern of directPatterns) {
      let match;
      pattern.lastIndex = 0;
      while ((match = pattern.exec(content)) !== null) {
        const key = match[1];
        if (!key.includes('${')) {
          keys.add(key);
        }
      }
    }

    for (const pattern of configPatterns) {
      let match;
      pattern.lastIndex = 0;
      while ((match = pattern.exec(content)) !== null) {
        keys.add(match[1]);
      }
    }

    for (const pattern of fallbackPatterns) {
      let match;
      pattern.lastIndex = 0;
      while ((match = pattern.exec(content)) !== null) {
        keys.add(match[1]);
      }
    }

    labelsObjectPattern.lastIndex = 0;
    let labelsMatch;
    while ((labelsMatch = labelsObjectPattern.exec(content)) !== null) {
      const labelsContent = labelsMatch[1];
      for (const pattern of labelValuePatterns) {
        let valueMatch;
        pattern.lastIndex = 0;
        while ((valueMatch = pattern.exec(labelsContent)) !== null) {
          keys.add(valueMatch[1]);
        }
      }
    }
  }

  function scanDir(dir: string) {
    const items = fs.readdirSync(dir);

    for (const item of items) {
      const itemPath = path.resolve(dir, item);
      const stat = fs.statSync(itemPath);

      if (stat.isDirectory()) {
        if (!item.startsWith('.') && item !== 'node_modules') {
          scanDir(itemPath);
        }
      } else if (stat.isFile() && (item.endsWith('.tsx') || item.endsWith('.ts'))) {
        scanFile(itemPath);
      }
    }
  }

  scanDir(srcDir);

  console.log(`[i18n] Extracted ${keys.size} translation keys from source code`);
  return Array.from(keys).sort();
}

// Get all translation keys (from data files + source code)
function getAllTranslationKeys(): string[] {
  const dataKeys = extractTranslatableKeys();
  const codeKeys = extractCodeTranslationKeys();

  const allKeys = new Set([...dataKeys, ...codeKeys]);
  return Array.from(allKeys).sort();
}

// Sync translation files - add missing keys, remove obsolete keys
function syncTranslations(): { added: number; removed: number; total: number; files: string[] } {
  const translationsDir = path.resolve(__dirname, 'public', 'translations');
  if (!fs.existsSync(translationsDir)) {
    fs.mkdirSync(translationsDir, { recursive: true });
    return { added: 0, removed: 0, total: 0, files: [] };
  }

  const keys = getAllTranslationKeys();
  const keysSet = new Set(keys);
  const files = fs.readdirSync(translationsDir).filter(f => f.endsWith('.json') && f !== 'languages.json');

  let totalAdded = 0;
  let totalRemoved = 0;
  const updatedFiles: string[] = [];

  for (const file of files) {
    const filePath = path.resolve(translationsDir, file);
    const langCode = file.replace('.json', '');

    try {
      const content = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
      const translations = content.translations || {};
      let addedCount = 0;
      let removedCount = 0;

      // Add missing keys
      for (const key of keys) {
        if (!(key in translations)) {
          translations[key] = langCode === 'en' ? key : '';
          addedCount++;
        }
      }

      // Remove obsolete keys
      for (const existingKey of Object.keys(translations)) {
        if (!keysSet.has(existingKey)) {
          delete translations[existingKey];
          removedCount++;
        }
      }

      if (addedCount > 0 || removedCount > 0) {
        const sortedTranslations: Record<string, string> = {};
        Object.keys(translations).sort().forEach(k => {
          sortedTranslations[k] = translations[k];
        });

        content.translations = sortedTranslations;
        fs.writeFileSync(filePath, JSON.stringify(content, null, 4), 'utf-8');
        totalAdded += addedCount;
        totalRemoved += removedCount;

        const changes: string[] = [];
        if (addedCount > 0) changes.push(`+${addedCount}`);
        if (removedCount > 0) changes.push(`-${removedCount}`);
        updatedFiles.push(`${file} (${changes.join(', ')})`);
      }
    } catch (e) {
      console.error(`Failed to sync ${file}:`, e);
    }
  }

  return { added: totalAdded, removed: totalRemoved, total: keys.length, files: updatedFiles };
}

// Get translation stats - which keys are missing/untranslated
function getTranslationStats(): Record<string, { total: number; translated: number; missing: string[] }> {
  const translationsDir = path.resolve(__dirname, 'public', 'translations');
  const keys = getAllTranslationKeys();
  const files = fs.readdirSync(translationsDir).filter(f => f.endsWith('.json') && f !== 'languages.json');

  const stats: Record<string, { total: number; translated: number; missing: string[] }> = {};

  for (const file of files) {
    const filePath = path.resolve(translationsDir, file);
    const langCode = file.replace('.json', '');

    try {
      const content = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
      const translations = content.translations || {};
      const missing: string[] = [];
      let translated = 0;

      for (const key of keys) {
        const value = translations[key];
        if (value && value.trim() !== '') {
          translated++;
        } else {
          missing.push(key);
        }
      }

      stats[langCode] = { total: keys.length, translated, missing };
    } catch {
      stats[langCode] = { total: keys.length, translated: 0, missing: keys };
    }
  }

  return stats;
}

// ═══════════════════════════════════════════════════════════════
// RECIPE & CATEGORY HELPERS
// ═══════════════════════════════════════════════════════════════

interface Recipe {
  id: string;
  name: string;
  description: string;
  categoryId: string;
  icon: string;
  method: string;
  level: string;
  compression: string;
  packages?: string[];
  script?: string;
  debUrl?: string;
  distributions?: { include?: string[]; exclude?: string[] };
  version?: string;
  screenshots?: string[];
  longDescription?: string;
  tags?: string[];
  enabled?: boolean;
  order?: number;
}

interface Category {
  id: string;
  nameKey: string;
  name: string;
  icon: string;
  order: number;
  enabled?: boolean;
}

const RECIPES_PATH = path.resolve(__dirname, 'public', 'data', 'recipes.json');
const CATEGORIES_PATH = path.resolve(__dirname, 'public', 'data', 'categories.json');
const RECIPE_TRANSLATIONS_DIR = path.resolve(__dirname, 'public', 'data', 'recipe-translations');

function ensureDataDir(): void {
  const dataDir = path.resolve(__dirname, 'public', 'data');
  if (!fs.existsSync(dataDir)) {
    fs.mkdirSync(dataDir, { recursive: true });
  }
}

function readRecipes(): Recipe[] {
  ensureDataDir();
  if (!fs.existsSync(RECIPES_PATH)) {
    fs.writeFileSync(RECIPES_PATH, '[]', 'utf-8');
    return [];
  }
  try {
    return JSON.parse(fs.readFileSync(RECIPES_PATH, 'utf-8'));
  } catch {
    return [];
  }
}

function writeRecipes(recipes: Recipe[]): void {
  ensureDataDir();
  fs.writeFileSync(RECIPES_PATH, JSON.stringify(recipes, null, 2), 'utf-8');
}

function readCategories(): Category[] {
  ensureDataDir();
  if (!fs.existsSync(CATEGORIES_PATH)) {
    return [];
  }
  try {
    return JSON.parse(fs.readFileSync(CATEGORIES_PATH, 'utf-8'));
  } catch {
    return [];
  }
}

function writeCategories(categories: Category[]): void {
  ensureDataDir();
  fs.writeFileSync(CATEGORIES_PATH, JSON.stringify(categories, null, 2), 'utf-8');
}

// ═══════════════════════════════════════════════════════════════
// VITE PLUGIN
// ═══════════════════════════════════════════════════════════════

function localDataPlugin() {
  return {
    name: 'local-data-plugin',

    // Run translation sync on startup
    buildStart() {
      console.log('[i18n] Syncing translation keys...');
      const result = syncTranslations();
      if (result.added > 0 || result.removed > 0) {
        console.log(`[i18n] Updated translations: +${result.added} added, -${result.removed} removed (${result.total} total keys)`);
        if (result.files.length > 0) {
          console.log(`[i18n] Modified files: ${result.files.join(', ')}`);
        }
      } else {
        console.log(`[i18n] Translations up to date (${result.total} keys)`);
      }
    },

    configureServer(server: ViteDevServer) {
      server.middlewares.use((req: IncomingMessage, res: ServerResponse, next: Connect.NextFunction) => {
        // Debug logging
        if (req.url?.startsWith('/api/')) {
          console.log('[API Request]', req.method, req.url);
        }

        // ═══════════════════════════════════════════════════════════
        // RECIPE CRUD ENDPOINTS
        // ═══════════════════════════════════════════════════════════

        // GET /api/recipes — list all recipes
        if (req.method === 'GET' && req.url === '/api/recipes') {
          try {
            const recipes = readRecipes();
            sendJson(res, 200, recipes);
          } catch (error) {
            console.error('Failed to read recipes:', error);
            sendJson(res, 500, { error: 'Failed to read recipes' });
          }
          return;
        }

        // GET /api/recipes-index/:lang — aggregated translated recipe index
        // Merges per-recipe translation files into a lightweight index on the fly.
        if (req.method === 'GET' && req.url?.match(/^\/api\/recipes-index\/[a-zA-Z-]+$/)) {
          try {
            const lang = req.url.split('/api/recipes-index/')[1];
            const recipes = readRecipes();

            // Build lightweight index (same fields as recipes-index.json)
            const HEAVY_FIELDS = new Set(['longDescription', 'script', 'screenshots', 'screenshotSources']);
            const index = recipes.map((r: Recipe) => {
              const light: Record<string, unknown> = {};
              for (const [k, v] of Object.entries(r)) {
                if (!HEAVY_FIELDS.has(k)) light[k] = v;
              }
              return light;
            });

            // Read per-recipe translations and overlay
            const langDir = path.resolve(RECIPE_TRANSLATIONS_DIR, lang);
            if (fs.existsSync(langDir)) {
              const trMap = new Map<string, { name?: string; description?: string }>();
              for (const fname of fs.readdirSync(langDir)) {
                if (!fname.endsWith('.json')) continue;
                const recipeId = fname.slice(0, -5);
                try {
                  const tr = JSON.parse(fs.readFileSync(path.resolve(langDir, fname), 'utf-8'));
                  trMap.set(recipeId, tr);
                } catch {
                  // skip invalid files
                }
              }

              for (const entry of index) {
                const tr = trMap.get(entry.id as string);
                if (tr) {
                  if (tr.name) entry.name = tr.name;
                  if (tr.description) entry.description = tr.description;
                }
              }
            }

            sendJson(res, 200, index);
          } catch (error) {
            console.error('Failed to build translated index:', error);
            sendJson(res, 500, { error: 'Failed to build translated index' });
          }
          return;
        }

        // GET /api/recipes/:id — get single recipe by ID
        if (req.method === 'GET' && req.url?.match(/^\/api\/recipes\/[^/]+$/) && !req.url.includes('/translations')) {
          try {
            const id = req.url.split('/api/recipes/')[1];
            const recipes = readRecipes();
            const recipe = recipes.find(r => r.id === id);

            if (!recipe) {
              sendJson(res, 404, { error: 'Recipe not found' });
              return;
            }

            sendJson(res, 200, recipe);
          } catch (error) {
            console.error('Failed to get recipe:', error);
            sendJson(res, 500, { error: 'Failed to get recipe' });
          }
          return;
        }

        // POST /api/recipes — upsert recipe
        if (req.method === 'POST' && req.url === '/api/recipes') {
          parseRequestBody(req)
            .then((body) => {
              try {
                const recipe = JSON.parse(body) as Recipe;

                if (!recipe.id) {
                  sendJson(res, 400, { error: 'Recipe ID is required' });
                  return;
                }

                const recipes = readRecipes();
                const existingIndex = recipes.findIndex(r => r.id === recipe.id);

                if (existingIndex >= 0) {
                  recipes[existingIndex] = recipe;
                } else {
                  recipes.push(recipe);
                }

                writeRecipes(recipes);
                console.log(`[Recipes] Saved recipe: ${recipe.id} (${recipe.name})`);
                sendJson(res, 200, { success: true, recipe });
              } catch (error) {
                console.error('Failed to save recipe:', error);
                sendJson(res, 500, { error: 'Failed to save recipe' });
              }
            })
            .catch((err) => {
              sendJson(res, 400, { error: 'Invalid request: ' + err.message });
            });
          return;
        }

        // DELETE /api/recipes/:id — delete recipe by ID
        if (req.method === 'DELETE' && req.url?.match(/^\/api\/recipes\/[^/]+$/) && !req.url.includes('/translations')) {
          try {
            const id = req.url.split('/api/recipes/')[1];
            const recipes = readRecipes();
            const filtered = recipes.filter(r => r.id !== id);

            if (filtered.length === recipes.length) {
              sendJson(res, 404, { error: 'Recipe not found' });
              return;
            }

            writeRecipes(filtered);

            // Also delete any recipe translations
            const languages = getLanguagesWithMeta().filter(l => l.code !== 'en');
            for (const lang of languages) {
              const translationPath = path.resolve(RECIPE_TRANSLATIONS_DIR, lang.code, `${id}.json`);
              if (fs.existsSync(translationPath)) {
                fs.unlinkSync(translationPath);
              }
            }

            console.log(`[Recipes] Deleted recipe: ${id}`);
            sendJson(res, 200, { success: true });
          } catch (error) {
            console.error('Failed to delete recipe:', error);
            sendJson(res, 500, { error: 'Failed to delete recipe' });
          }
          return;
        }

        // ═══════════════════════════════════════════════════════════
        // CATEGORY ENDPOINTS
        // ═══════════════════════════════════════════════════════════

        // GET /api/categories — list all categories
        if (req.method === 'GET' && req.url === '/api/categories') {
          try {
            const categories = readCategories();
            sendJson(res, 200, categories);
          } catch (error) {
            console.error('Failed to read categories:', error);
            sendJson(res, 500, { error: 'Failed to read categories' });
          }
          return;
        }

        // POST /api/categories — save full categories array
        if (req.method === 'POST' && req.url === '/api/categories') {
          parseRequestBody(req)
            .then((body) => {
              try {
                const categories = JSON.parse(body) as Category[];

                if (!Array.isArray(categories)) {
                  sendJson(res, 400, { error: 'Expected an array of categories' });
                  return;
                }

                writeCategories(categories);
                console.log(`[Categories] Saved ${categories.length} categories`);
                sendJson(res, 200, { success: true, count: categories.length });
              } catch (error) {
                console.error('Failed to save categories:', error);
                sendJson(res, 500, { error: 'Failed to save categories' });
              }
            })
            .catch((err) => {
              sendJson(res, 400, { error: 'Invalid request: ' + err.message });
            });
          return;
        }

        // ═══════════════════════════════════════════════════════════
        // RECIPE TRANSLATION ENDPOINTS
        // ═══════════════════════════════════════════════════════════

        // GET /api/recipes/translations — get translation status for all recipes
        if (req.method === 'GET' && req.url === '/api/recipes/translations') {
          try {
            const recipes = readRecipes();
            const languages = getLanguagesWithMeta().filter(l => l.code !== 'en');

            const result = recipes.map(recipe => {
              const translations: Record<string, 'ok' | 'missing'> = {};

              for (const lang of languages) {
                const translationPath = path.resolve(RECIPE_TRANSLATIONS_DIR, lang.code, `${recipe.id}.json`);
                translations[lang.code] = fs.existsSync(translationPath) ? 'ok' : 'missing';
              }

              return {
                id: recipe.id,
                name: recipe.name,
                enabled: recipe.enabled !== false,
                translations
              };
            });

            sendJson(res, 200, { recipes: result, languages });
          } catch (error) {
            console.error('Failed to get recipe translations:', error);
            sendJson(res, 500, { error: 'Failed to get recipe translations' });
          }
          return;
        }

        // POST /api/recipes/translations/update — save translation for a recipe
        if (req.method === 'POST' && req.url === '/api/recipes/translations/update') {
          parseRequestBody(req)
            .then((body) => {
              try {
                const { recipeId, lang, translations } = JSON.parse(body);

                if (!recipeId || !lang || !translations) {
                  sendJson(res, 400, { error: 'recipeId, lang, and translations are required' });
                  return;
                }

                // Validate lang
                if (lang.includes('..') || lang.includes('/')) {
                  sendJson(res, 400, { error: 'Invalid language code' });
                  return;
                }

                // Validate recipeId
                if (recipeId.includes('..') || recipeId.includes('/')) {
                  sendJson(res, 400, { error: 'Invalid recipe ID' });
                  return;
                }

                // Ensure directory exists
                const langDir = path.resolve(RECIPE_TRANSLATIONS_DIR, lang);
                if (!fs.existsSync(langDir)) {
                  fs.mkdirSync(langDir, { recursive: true });
                }

                // Write translation file
                const translationPath = path.resolve(langDir, `${recipeId}.json`);
                fs.writeFileSync(translationPath, JSON.stringify(translations, null, 2), 'utf-8');

                console.log(`[Recipe Translations] Saved ${recipeId} -> ${lang}`);
                sendJson(res, 200, { success: true });
              } catch (error) {
                console.error('Failed to save recipe translation:', error);
                sendJson(res, 500, { error: 'Failed to save recipe translation' });
              }
            })
            .catch((err) => {
              sendJson(res, 400, { error: 'Invalid request: ' + err.message });
            });
          return;
        }

        // DELETE /api/recipes/translations/language/:langCode — delete all recipe translations for a language
        if (req.method === 'DELETE' && req.url?.startsWith('/api/recipes/translations/language/')) {
          try {
            const langCode = req.url.split('/api/recipes/translations/language/')[1];

            if (!langCode || langCode.includes('..') || langCode.includes('/')) {
              sendJson(res, 400, { error: 'Invalid language code' });
              return;
            }

            const langDir = path.resolve(RECIPE_TRANSLATIONS_DIR, langCode);
            if (fs.existsSync(langDir)) {
              const files = fs.readdirSync(langDir);
              for (const file of files) {
                fs.unlinkSync(path.resolve(langDir, file));
              }
              fs.rmdirSync(langDir);
              console.log(`[Recipe Translations] Deleted all translations for ${langCode} (${files.length} files)`);
            }

            sendJson(res, 200, { success: true });
          } catch (error) {
            console.error('Failed to delete recipe translations:', error);
            sendJson(res, 500, { error: 'Failed to delete recipe translations' });
          }
          return;
        }

        // DELETE /api/recipes/translations — delete ALL recipe translations
        if (req.method === 'DELETE' && req.url === '/api/recipes/translations') {
          try {
            if (fs.existsSync(RECIPE_TRANSLATIONS_DIR)) {
              // Recursively delete all contents
              function rmRecursive(dirPath: string) {
                const items = fs.readdirSync(dirPath);
                for (const item of items) {
                  const itemPath = path.resolve(dirPath, item);
                  const stat = fs.statSync(itemPath);
                  if (stat.isDirectory()) {
                    rmRecursive(itemPath);
                    fs.rmdirSync(itemPath);
                  } else {
                    fs.unlinkSync(itemPath);
                  }
                }
              }
              rmRecursive(RECIPE_TRANSLATIONS_DIR);
              fs.rmdirSync(RECIPE_TRANSLATIONS_DIR);
              console.log('[Recipe Translations] Deleted all recipe translations');
            }

            sendJson(res, 200, { success: true });
          } catch (error) {
            console.error('Failed to delete all recipe translations:', error);
            sendJson(res, 500, { error: 'Failed to delete all recipe translations' });
          }
          return;
        }

        // ═══════════════════════════════════════════════════════════
        // UI TRANSLATION ENDPOINTS
        // ═══════════════════════════════════════════════════════════

        // GET /api/languages — get available languages with metadata
        if (req.url === '/api/languages') {
          const languages = getLanguagesWithMeta();
          sendJson(res, 200, languages);
          return;
        }

        // POST /api/translations/sync — sync translation keys
        if (req.method === 'POST' && req.url === '/api/translations/sync') {
          try {
            const result = syncTranslations();
            sendJson(res, 200, result);
          } catch {
            sendJson(res, 500, { error: 'Failed to sync translations' });
          }
          return;
        }

        // GET /api/translations/stats — get translation stats
        if (req.url === '/api/translations/stats') {
          try {
            const stats = getTranslationStats();
            sendJson(res, 200, stats);
          } catch {
            sendJson(res, 500, { error: 'Failed to get translation stats' });
          }
          return;
        }

        // GET /api/translations/keys — get all translatable keys
        if (req.url === '/api/translations/keys') {
          try {
            const keys = getAllTranslationKeys();
            sendJson(res, 200, { keys });
          } catch {
            sendJson(res, 500, { error: 'Failed to get translation keys' });
          }
          return;
        }

        // POST /api/translations/update — update translations for a language
        if (req.method === 'POST' && req.url === '/api/translations/update') {
          let body = '';
          req.on('data', (chunk: Buffer) => {
            body += chunk.toString('utf8');
          });
          req.on('end', () => {
            try {
              const { langCode, translations: newTranslations } = JSON.parse(body);

              if (!langCode || typeof langCode !== 'string' || langCode.includes('..') || langCode.includes('/')) {
                sendJson(res, 400, { error: 'Invalid language code' });
                return;
              }

              const filePath = path.resolve(__dirname, 'public', 'translations', `${langCode}.json`);

              if (!fs.existsSync(filePath)) {
                sendJson(res, 404, { error: 'Language file not found' });
                return;
              }

              const existing = JSON.parse(fs.readFileSync(filePath, 'utf-8'));

              const sortedTranslations: Record<string, string> = {};
              Object.keys(newTranslations).sort().forEach(k => {
                sortedTranslations[k] = newTranslations[k];
              });

              const updated = {
                _meta: existing._meta,
                translations: sortedTranslations
              };

              fs.writeFileSync(filePath, JSON.stringify(updated, null, 4), 'utf-8');

              sendJson(res, 200, { success: true, updated: Object.keys(newTranslations).length });
            } catch (error) {
              console.error('Failed to update translations:', error);
              sendJson(res, 500, { error: 'Failed to update translations' });
            }
          });
          return;
        }

        // POST /api/languages/create — create a new language
        if (req.method === 'POST' && req.url === '/api/languages/create') {
          let body = '';
          req.on('data', (chunk: Buffer) => {
            body += chunk.toString('utf8');
          });
          req.on('end', () => {
            try {
              const { code, name, flag } = JSON.parse(body);

              if (!code || !name) {
                sendJson(res, 400, { error: 'Language code and name are required' });
                return;
              }

              if (!/^[a-z]{2,3}(-[A-Z][a-z]{1,3})?(-[A-Z]{2})?$/.test(code)) {
                sendJson(res, 400, { error: 'Invalid language code format. Use BCP 47 (e.g., "pl", "pt-BR", "zh-Hans")' });
                return;
              }

              const filePath = path.resolve(__dirname, 'public', 'translations', `${code}.json`);

              if (fs.existsSync(filePath)) {
                sendJson(res, 400, { error: 'Language already exists' });
                return;
              }

              const keys = getAllTranslationKeys();
              const isEnglish = code === 'en';
              const newContent = {
                _meta: {
                  name: name,
                  flag: flag || ''
                },
                translations: Object.fromEntries(keys.map(k => [k, isEnglish ? k : '']))
              };

              fs.writeFileSync(filePath, JSON.stringify(newContent, null, 4), 'utf-8');

              sendJson(res, 200, { success: true, code, keys: keys.length });
            } catch (error) {
              console.error('Failed to create language:', error);
              sendJson(res, 500, { error: 'Failed to create language' });
            }
          });
          return;
        }

        // POST /api/languages/update — update language metadata
        if (req.method === 'POST' && req.url === '/api/languages/update') {
          let body = '';
          req.on('data', (chunk: Buffer) => {
            body += chunk.toString('utf8');
          });
          req.on('end', () => {
            try {
              const { code, name, flag } = JSON.parse(body);

              if (!code) {
                sendJson(res, 400, { error: 'Language code is required' });
                return;
              }

              const filePath = path.resolve(__dirname, 'public', 'translations', `${code}.json`);

              if (!fs.existsSync(filePath)) {
                sendJson(res, 404, { error: 'Language not found' });
                return;
              }

              const content = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
              content._meta = {
                name: name || content._meta?.name || code,
                flag: flag !== undefined ? flag : (content._meta?.flag || '')
              };

              fs.writeFileSync(filePath, JSON.stringify(content, null, 4), 'utf-8');

              sendJson(res, 200, { success: true });
            } catch (error) {
              console.error('Failed to update language:', error);
              sendJson(res, 500, { error: 'Failed to update language' });
            }
          });
          return;
        }

        // POST /api/languages/delete — delete language
        if (req.method === 'POST' && req.url === '/api/languages/delete') {
          let body = '';
          req.on('data', (chunk: Buffer) => {
            body += chunk.toString('utf8');
          });
          req.on('end', () => {
            try {
              const { code } = JSON.parse(body);

              if (!code) {
                sendJson(res, 400, { error: 'Language code is required' });
                return;
              }

              const filePath = path.resolve(__dirname, 'public', 'translations', `${code}.json`);

              if (!fs.existsSync(filePath)) {
                sendJson(res, 404, { error: 'Language not found' });
                return;
              }

              fs.unlinkSync(filePath);

              sendJson(res, 200, { success: true });
            } catch (error) {
              console.error('Failed to delete language:', error);
              sendJson(res, 500, { error: 'Failed to delete language' });
            }
          });
          return;
        }

        // ═══════════════════════════════════════════════════════════
        // AI PROXY ENDPOINTS
        // ═══════════════════════════════════════════════════════════

        // POST /api/ai/translate — proxy AI translation requests
        if (req.method === 'POST' && req.url === '/api/ai/translate') {
          parseRequestBody(req)
            .then(async (body) => {
              try {
                const { endpoint, headers, body: requestBody, proxyUrl } = JSON.parse(body);

                console.log('\n[AI Translate] ═══════════════════════════════════════');
                console.log('[AI Translate] Endpoint:', endpoint);
                console.log('[AI Translate] Proxy:', proxyUrl || '(none)');

                try {
                  const parsedBody = JSON.parse(requestBody);
                  console.log('[AI Translate] Model:', parsedBody.model);
                  if (parsedBody.messages) {
                    console.log('[AI Translate] Messages count:', parsedBody.messages.length);
                    const userMsg = parsedBody.messages.find((m: { role: string }) => m.role === 'user');
                    if (userMsg) {
                      const content = typeof userMsg.content === 'string'
                        ? userMsg.content
                        : JSON.stringify(userMsg.content);
                      console.log('[AI Translate] User message (first 500 chars):', content.substring(0, 500));
                    }
                  }
                } catch {
                  console.log('[AI Translate] Request body (raw, first 500 chars):', requestBody.substring(0, 500));
                }

                const hasAuth = headers?.['Authorization'] || headers?.['x-goog-api-key'];
                const isOpenCode = endpoint?.includes('opencode.ai') || endpoint?.includes('/api/ai/opencode-local');
                if (!hasAuth && !isOpenCode) {
                  console.log('[AI Translate] ERROR: No API key provided');
                  sendJson(res, 400, { error: 'API key is required' });
                  return;
                }

                console.log('[AI Translate] Sending request...');
                const startTime = Date.now();

                // Check if this is a request to OpenCode Local (local endpoint)
                let response: ApiResponse;
                if (endpoint === '/api/ai/opencode-local' || endpoint.startsWith('/api/ai/opencode-local')) {
                  console.log('[AI Translate] Redirecting to OpenCode Local handler');
                  try {
                    const { prompt, model, proxyUrl: localProxyUrl } = JSON.parse(requestBody);
                    const timeoutMs = 300 * 1000;

                    console.log('\n[OpenCode Local] ═══════════════════════════════════════');
                    console.log('[OpenCode Local] Model:', model);
                    console.log('[OpenCode Local] Proxy:', localProxyUrl || proxyUrl || '(none)');
                    console.log('[OpenCode Local] Timeout:', (timeoutMs / 1000) + 's');
                    console.log('[OpenCode Local] Prompt (first 300 chars):', prompt.substring(0, 300));

                    const { spawn } = await import('child_process');

                    const args = ['run', '--format', 'json'];
                    if (model) {
                      args.push('-m', model);
                    }

                    const env = { ...process.env };
                    const effectiveProxy = localProxyUrl || proxyUrl;
                    if (effectiveProxy) {
                      env.HTTPS_PROXY = effectiveProxy;
                      env.HTTP_PROXY = effectiveProxy;
                    }

                    console.log('[OpenCode Local] Running: opencode', args.join(' '));
                    const openCodeStartTime = Date.now();

                    const child = spawn('opencode', args, {
                      env,
                      stdio: ['pipe', 'pipe', 'pipe']
                    });

                    child.stdin.write(prompt);
                    child.stdin.end();

                    const result = await new Promise<{ status: number; data: string }>((resolve) => {
                      let stdout = '';
                      let stderr = '';
                      let responseSent = false;

                      const sendResponse = (status: number, data: unknown) => {
                        if (responseSent) return;
                        responseSent = true;
                        resolve({ status, data: typeof data === 'string' ? data : JSON.stringify(data) });
                      };

                      child.stdout.on('data', (data: Buffer) => {
                        stdout += data.toString();
                      });

                      child.stderr.on('data', (data: Buffer) => {
                        stderr += data.toString();
                      });

                      child.on('close', (code) => {
                        const elapsed = Date.now() - openCodeStartTime;
                        console.log(`[OpenCode Local] Exit code: ${code} (${elapsed}ms)`);

                        if (code !== 0) {
                          console.log('[OpenCode Local] Stderr:', stderr.substring(0, 500));
                          sendResponse(500, { error: `OpenCode exited with code ${code}`, stderr });
                          return;
                        }

                        try {
                          const lines = stdout.trim().split('\n');
                          let textContent = '';

                          for (const line of lines) {
                            if (!line.trim()) continue;
                            try {
                              const event = JSON.parse(line);
                              if (event.type === 'text' && event.part?.text) {
                                textContent += event.part.text;
                              }
                            } catch {
                              // Skip non-JSON lines
                            }
                          }

                          console.log('[OpenCode Local] Response (first 500 chars):', textContent.substring(0, 500));
                          console.log('[OpenCode Local] ═══════════════════════════════════════\n');

                          sendResponse(200, {
                            choices: [{
                              message: {
                                content: textContent,
                                role: 'assistant'
                              }
                            }]
                          });
                        } catch (parseError) {
                          console.error('[OpenCode Local] Parse error:', parseError);
                          sendResponse(500, { error: 'Failed to parse opencode output', stdout });
                        }
                      });

                      child.on('error', (err) => {
                        console.error('[OpenCode Local] Spawn error:', err);
                        sendResponse(500, { error: 'Failed to run opencode: ' + err.message });
                      });

                      setTimeout(() => {
                        if (!child.killed) {
                          child.kill();
                          sendResponse(408, { error: `OpenCode request timeout (${timeoutMs / 1000}s)` });
                        }
                      }, timeoutMs);
                    });

                    response = result;
                  } catch (error) {
                    console.error('[OpenCode Local] Exception:', error);
                    response = {
                      status: 500,
                      data: JSON.stringify({ error: 'OpenCode request failed: ' + (error as Error).message }),
                      error: (error as Error).message,
                    };
                  }
                } else {
                  // External endpoint - use apiRequest with proxy support
                  response = await apiRequest(endpoint, {
                    method: 'POST',
                    headers,
                    body: requestBody,
                    timeout: 60000,
                    proxyUrl: proxyUrl || undefined,
                  });
                }

                const elapsed = Date.now() - startTime;
                console.log(`[AI Translate] Response status: ${response.status} (${elapsed}ms)`);

                if (response.status >= 400) {
                  console.log('[AI Translate] ERROR Response:', response.data.substring(0, 1000));
                } else {
                  try {
                    const parsed = JSON.parse(response.data);
                    const content = parsed.choices?.[0]?.message?.content;
                    if (content) {
                      console.log('[AI Translate] Translation result (first 500 chars):', content.substring(0, 500));
                    } else {
                      console.log('[AI Translate] Response (first 500 chars):', response.data.substring(0, 500));
                    }
                  } catch {
                    console.log('[AI Translate] Response (first 500 chars):', response.data.substring(0, 500));
                  }
                }
                console.log('[AI Translate] ═══════════════════════════════════════\n');

                sendJson(res, response.status, response.data);
              } catch (error) {
                console.error('[AI Translate] Exception:', error);
                sendJson(res, 500, { error: 'AI request failed: ' + (error as Error).message });
              }
            })
            .catch((err) => {
              console.error('[AI Translate] Request parse error:', err);
              sendJson(res, 500, { error: 'Request error: ' + err.message });
            });
          return;
        }

        // POST /api/ai/models — proxy AI models list requests
        if (req.method === 'POST' && req.url === '/api/ai/models') {
          parseRequestBody(req)
            .then(async (body) => {
              try {
                const { endpoint, headers, proxyUrl } = JSON.parse(body);

                console.log('\n[AI Models] ───────────────────────────────────────');
                console.log('[AI Models] Endpoint:', endpoint);
                console.log('[AI Models] Proxy:', proxyUrl || '(none)');

                const hasAuth = headers?.['Authorization'] || headers?.['x-goog-api-key'];
                const requiresAuth = endpoint?.includes('groq.com') || endpoint?.includes('googleapis.com');
                if (requiresAuth && !hasAuth) {
                  console.log('[AI Models] ERROR: API key required but not provided');
                  sendJson(res, 400, { error: 'API key is required', data: [] });
                  return;
                }

                console.log('[AI Models] Fetching models...');
                const startTime = Date.now();

                const response = await apiRequest(endpoint, {
                  method: 'GET',
                  headers,
                  timeout: 15000,
                  proxyUrl: proxyUrl || undefined,
                });

                const elapsed = Date.now() - startTime;
                console.log(`[AI Models] Response status: ${response.status} (${elapsed}ms)`);

                if (response.status >= 400) {
                  console.log('[AI Models] ERROR Response:', response.data.substring(0, 500));
                } else {
                  try {
                    const parsed = JSON.parse(response.data);
                    const models = parsed.data || parsed.models || [];
                    console.log('[AI Models] Models count:', models.length);
                    if (models.length > 0) {
                      console.log('[AI Models] First 5 models:', models.slice(0, 5).map((m: { id?: string; name?: string }) => m.id || m.name).join(', '));
                    }
                  } catch {
                    console.log('[AI Models] Response (first 300 chars):', response.data.substring(0, 300));
                  }
                }
                console.log('[AI Models] ───────────────────────────────────────\n');

                sendJson(res, response.status, response.data);
              } catch (error) {
                console.error('[AI Models] Exception:', error);
                sendJson(res, 500, { error: 'Failed to fetch models: ' + (error as Error).message });
              }
            })
            .catch((err) => {
              console.error('[AI Models] Request parse error:', err);
              sendJson(res, 500, { error: 'Request error: ' + err.message });
            });
          return;
        }

        // POST /api/ai/gemini-cli — execute local gemini CLI
        if (req.method === 'POST' && req.url === '/api/ai/gemini-cli') {
          parseRequestBody(req)
            .then(async (body) => {
              try {
                const { prompt, model, projectId } = JSON.parse(body);

                console.log('\n[Gemini CLI] ═══════════════════════════════════════');
                console.log('[Gemini CLI] Model:', model || '(default)');
                console.log('[Gemini CLI] Project ID:', projectId || '(not set)');
                console.log('[Gemini CLI] Prompt (first 300 chars):', prompt.substring(0, 300));

                const { spawn } = await import('child_process');

                const args = ['-y', '-o', 'json'];
                if (model) {
                  args.push('-m', model);
                }
                args.push(prompt);

                const env = { ...process.env };
                if (projectId) {
                  env.GOOGLE_CLOUD_PROJECT = projectId;
                }

                console.log('[Gemini CLI] Running: gemini', args.slice(0, 3).join(' '), '...');
                const startTime = Date.now();

                const child = spawn('gemini', args, {
                  env,
                  stdio: ['pipe', 'pipe', 'pipe']
                });

                let stdout = '';
                let stderr = '';
                let responseSent = false;

                const sendResponseOnce = (status: number, data: unknown) => {
                  if (responseSent) return;
                  responseSent = true;
                  sendJson(res, status, data);
                };

                child.stdout.on('data', (data: Buffer) => {
                  stdout += data.toString();
                });

                child.stderr.on('data', (data: Buffer) => {
                  stderr += data.toString();
                });

                child.on('close', (code) => {
                  const elapsed = Date.now() - startTime;
                  console.log(`[Gemini CLI] Exit code: ${code} (${elapsed}ms)`);

                  if (code !== 0) {
                    console.log('[Gemini CLI] Stderr:', stderr.substring(0, 500));
                    sendResponseOnce(500, { error: `Gemini exited with code ${code}`, stderr });
                    return;
                  }

                  try {
                    const result = JSON.parse(stdout);
                    console.log('[Gemini CLI] Response (first 500 chars):', (result.response || '').substring(0, 500));
                    console.log('[Gemini CLI] ═══════════════════════════════════════\n');

                    sendResponseOnce(200, {
                      response: result.response,
                      choices: [{
                        message: {
                          content: result.response,
                          role: 'assistant'
                        }
                      }]
                    });
                  } catch (parseError) {
                    console.error('[Gemini CLI] Parse error:', parseError);
                    console.log('[Gemini CLI] Raw stdout:', stdout.substring(0, 500));
                    sendResponseOnce(500, { error: 'Failed to parse gemini output', stdout });
                  }
                });

                child.on('error', (err) => {
                  console.error('[Gemini CLI] Spawn error:', err);
                  sendResponseOnce(500, { error: 'Failed to run gemini: ' + err.message });
                });

                // Timeout 5 min
                setTimeout(() => {
                  if (!child.killed) {
                    child.kill();
                    sendResponseOnce(408, { error: 'Gemini request timeout (5 min)' });
                  }
                }, 300000);

              } catch (error) {
                console.error('[Gemini CLI] Exception:', error);
                sendJson(res, 500, { error: 'Gemini request failed: ' + (error as Error).message });
              }
            })
            .catch((err) => {
              console.error('[Gemini CLI] Request parse error:', err);
              sendJson(res, 500, { error: 'Request error: ' + err.message });
            });
          return;
        }

        // POST /api/ai/opencode-local — execute local opencode CLI
        if (req.method === 'POST' && req.url === '/api/ai/opencode-local') {
          parseRequestBody(req)
            .then(async (body) => {
              try {
                const { prompt, model, proxyUrl, timeout } = JSON.parse(body);
                const timeoutMs = (timeout || 300) * 1000;

                console.log('\n[OpenCode Local] ═══════════════════════════════════════');
                console.log('[OpenCode Local] Model:', model);
                console.log('[OpenCode Local] Proxy:', proxyUrl || '(none)');
                console.log('[OpenCode Local] Timeout:', (timeoutMs / 1000) + 's');
                console.log('[OpenCode Local] Prompt (first 300 chars):', prompt.substring(0, 300));

                const { spawn } = await import('child_process');

                const args = ['run', '--format', 'json'];
                if (model) {
                  args.push('-m', model);
                }

                const env = { ...process.env };
                if (proxyUrl) {
                  env.HTTPS_PROXY = proxyUrl;
                  env.HTTP_PROXY = proxyUrl;
                }

                console.log('[OpenCode Local] Running: opencode', args.join(' '));
                const startTime = Date.now();

                const child = spawn('opencode', args, {
                  env,
                  stdio: ['pipe', 'pipe', 'pipe']
                });

                child.stdin.write(prompt);
                child.stdin.end();

                let stdout = '';
                let stderr = '';
                let responseSent = false;

                const sendResponse = (status: number, data: unknown) => {
                  if (responseSent) return;
                  responseSent = true;
                  sendJson(res, status, data);
                };

                child.stdout.on('data', (data: Buffer) => {
                  stdout += data.toString();
                });

                child.stderr.on('data', (data: Buffer) => {
                  stderr += data.toString();
                });

                child.on('close', (code) => {
                  const elapsed = Date.now() - startTime;
                  console.log(`[OpenCode Local] Exit code: ${code} (${elapsed}ms)`);

                  if (code !== 0) {
                    console.log('[OpenCode Local] Stderr:', stderr.substring(0, 500));
                    sendResponse(500, { error: `OpenCode exited with code ${code}`, stderr });
                    return;
                  }

                  try {
                    const lines = stdout.trim().split('\n');
                    let textContent = '';

                    for (const line of lines) {
                      if (!line.trim()) continue;
                      try {
                        const event = JSON.parse(line);
                        if (event.type === 'text' && event.part?.text) {
                          textContent += event.part.text;
                        }
                      } catch {
                        // Skip non-JSON lines
                      }
                    }

                    console.log('[OpenCode Local] Response (first 500 chars):', textContent.substring(0, 500));
                    console.log('[OpenCode Local] ═══════════════════════════════════════\n');

                    sendResponse(200, {
                      choices: [{
                        message: {
                          content: textContent,
                          role: 'assistant'
                        }
                      }]
                    });
                  } catch (parseError) {
                    console.error('[OpenCode Local] Parse error:', parseError);
                    sendResponse(500, { error: 'Failed to parse opencode output', stdout });
                  }
                });

                child.on('error', (err) => {
                  console.error('[OpenCode Local] Spawn error:', err);
                  sendResponse(500, { error: 'Failed to run opencode: ' + err.message });
                });

                setTimeout(() => {
                  if (!child.killed) {
                    child.kill();
                    sendResponse(408, { error: `OpenCode request timeout (${timeoutMs / 1000}s)` });
                  }
                }, timeoutMs);

              } catch (error) {
                console.error('[OpenCode Local] Exception:', error);
                sendJson(res, 500, { error: 'OpenCode request failed: ' + (error as Error).message });
              }
            })
            .catch((err) => {
              console.error('[OpenCode Local] Request parse error:', err);
              sendJson(res, 500, { error: 'Request error: ' + err.message });
            });
          return;
        }

        // GET /api/ai/opencode-local/models — list opencode models
        if (req.method === 'GET' && req.url === '/api/ai/opencode-local/models') {
          (async () => {
            const { spawn } = await import('child_process');

            console.log('[OpenCode Local Models] Fetching models...');

            const child = spawn('opencode', ['models'], {
              stdio: ['pipe', 'pipe', 'pipe']
            });

            let stdout = '';
            let stderr = '';
            let responseSent = false;

            const sendResponse = (status: number, data: unknown) => {
              if (responseSent) return;
              responseSent = true;
              sendJson(res, status, data);
            };

            child.stdout.on('data', (data: Buffer) => {
              stdout += data.toString();
            });

            child.stderr.on('data', (data: Buffer) => {
              stderr += data.toString();
            });

            child.on('close', (code) => {
              if (code !== 0) {
                console.log('[OpenCode Local Models] Error:', stderr);
                sendResponse(500, { error: 'Failed to get models', models: [] });
                return;
              }

              const models = stdout.trim().split('\n').filter(m => m.trim());
              console.log('[OpenCode Local Models] Found', models.length, 'models');
              sendResponse(200, { models });
            });

            child.on('error', (err) => {
              console.error('[OpenCode Local Models] Spawn error:', err);
              sendResponse(500, { error: 'opencode not found', models: [] });
            });

            setTimeout(() => {
              if (!child.killed) {
                child.kill();
                sendResponse(408, { error: 'Timeout', models: [] });
              }
            }, 15000);
          })();
          return;
        }

        // POST /api/ai/copilot-cli — execute local GitHub Copilot CLI
        if (req.method === 'POST' && req.url === '/api/ai/copilot-cli') {
          parseRequestBody(req)
            .then(async (body) => {
              try {
                const { prompt, model, proxyUrl, timeout } = JSON.parse(body);
                const timeoutMs = (timeout || 300) * 1000;

                console.log('\n[Copilot CLI] ═══════════════════════════════════════');
                console.log('[Copilot CLI] Model:', model || '(default)');
                console.log('[Copilot CLI] Proxy:', proxyUrl || '(none)');
                console.log('[Copilot CLI] Timeout:', (timeoutMs / 1000) + 's');
                console.log('[Copilot CLI] Prompt length:', prompt.length, 'chars');
                console.log('[Copilot CLI] Prompt (first 300 chars):', prompt.substring(0, 300));

                const { spawn } = await import('child_process');

                const cliArgs = ['-p', prompt, '-s'];
                if (model) {
                  cliArgs.push('--model', model);
                }

                const env = { ...process.env };
                if (proxyUrl) {
                  env.HTTPS_PROXY = proxyUrl;
                  env.HTTP_PROXY = proxyUrl;
                }

                console.log('[Copilot CLI] Running: copilot -p <prompt> -s' + (model ? ` --model ${model}` : ''));
                const startTime = Date.now();

                const child = spawn('copilot', cliArgs, {
                  env,
                  stdio: ['pipe', 'pipe', 'pipe']
                });

                child.stdin.end();

                let stdout = '';
                let stderr = '';
                let responseSent = false;

                const sendResponse = (status: number, data: unknown) => {
                  if (responseSent) return;
                  responseSent = true;
                  sendJson(res, status, data);
                };

                child.stdout.on('data', (data: Buffer) => {
                  stdout += data.toString();
                });

                child.stderr.on('data', (data: Buffer) => {
                  stderr += data.toString();
                });

                child.on('close', (code) => {
                  const elapsed = Date.now() - startTime;

                  if (code !== 0) {
                    console.log(`[Copilot CLI] Exit code: ${code} (${elapsed}ms)`);
                    console.log('[Copilot CLI] Stderr:', stderr.substring(0, 500));
                    console.log('[Copilot CLI] Stdout:', stdout.substring(0, 500));
                    sendResponse(500, {
                      error: `Copilot exited with code ${code}`,
                      stderr,
                      stdout: stdout.substring(0, 500),
                    });
                    return;
                  }

                  const content = stdout.trim();
                  console.log(`[Copilot CLI] Success (${elapsed}ms), response length: ${content.length}`);
                  console.log('[Copilot CLI] Response (first 500 chars):', content.substring(0, 500));
                  console.log('[Copilot CLI] ═══════════════════════════════════════\n');

                  sendResponse(200, {
                    response: content,
                    choices: [{
                      message: {
                        content,
                        role: 'assistant'
                      }
                    }]
                  });
                });

                child.on('error', (err) => {
                  console.error('[Copilot CLI] Spawn error:', err);
                  sendResponse(500, { error: 'Failed to run copilot: ' + err.message });
                });

                setTimeout(() => {
                  if (!child.killed) {
                    child.kill();
                    sendResponse(408, { error: `Copilot request timeout (${timeoutMs / 1000}s)` });
                  }
                }, timeoutMs);

              } catch (error) {
                console.error('[Copilot CLI] Exception:', error);
                sendJson(res, 500, { error: 'Copilot request failed: ' + (error as Error).message });
              }
            })
            .catch((err) => {
              console.error('[Copilot CLI] Request parse error:', err);
              sendJson(res, 500, { error: 'Request error: ' + err.message });
            });
          return;
        }

        // GET /api/ai/copilot-cli/models — list GitHub Copilot CLI models
        if (req.method === 'GET' && req.url === '/api/ai/copilot-cli/models') {
          (async () => {
            const { execFile } = await import('child_process');

            console.log('[Copilot CLI Models] Fetching models from --help...');

            execFile('copilot', ['--help'], {
              timeout: 15000,
              maxBuffer: 1024 * 1024,
              env: { ...process.env },
            }, (error, stdout, stderr) => {
              if (error) {
                console.log('[Copilot CLI Models] Error:', (stderr || '').substring(0, 500));
                sendJson(res, 500, { error: 'Failed to get models', models: [] });
                return;
              }

              try {
                // Parse models from --help output
                // Looking for: --model <model>   Set the AI model to use (choices: "model1", "model2", ...)
                // The choices span multiple lines, so we need to match across newlines
                const modelMatch = stdout.match(/--model.*?\(choices:\s*([^)]+)\)/s);
                if (!modelMatch) {
                  console.log('[Copilot CLI Models] Could not parse models from help');
                  sendJson(res, 500, { error: 'Could not parse models', models: [] });
                  return;
                }

                // Extract model names from quotes
                const modelsText = modelMatch[1];
                const models = modelsText.match(/"([^"]+)"/g)?.map(m => m.slice(1, -1)) || [];
                
                console.log('[Copilot CLI Models] Found', models.length, 'models');
                sendJson(res, 200, { models });
              } catch (parseError) {
                console.error('[Copilot CLI Models] Parse error:', parseError);
                sendJson(res, 500, { error: 'Failed to parse models', models: [] });
              }
            });
          })();
          return;
        }

        // GET /api/ai/ollama-models — fetch local Ollama models
        if (req.method === 'GET' && req.url === '/api/ai/ollama-models') {
          (async () => {
            try {
              console.log('[Ollama Models] Fetching models from localhost:11434...');

              const response = await fetch('http://localhost:11434/api/tags', {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
              });

              if (!response.ok) {
                console.log('[Ollama Models] Error:', response.status);
                sendJson(res, 200, { models: [] });
                return;
              }

              const data = await response.json() as { models?: Array<{ name: string }> };
              console.log('[Ollama Models] Found', data.models?.length || 0, 'models');
              sendJson(res, 200, data);
            } catch {
              console.log('[Ollama Models] Ollama not running or not accessible');
              sendJson(res, 200, { models: [] });
            }
          })();
          return;
        }

        // Pass through to next middleware
        next();
      });
    },
  };
}

// ═══════════════════════════════════════════════════════════════
// VITE CONFIG
// ═══════════════════════════════════════════════════════════════

export default defineConfig({
  plugins: [react(), localDataPlugin()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5174,
    host: true,
    allowedHosts: ['code.a5.crims0n.ru'],
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom'],
          'vendor-ui': [
            '@radix-ui/react-popover',
            '@radix-ui/react-tabs',
            '@radix-ui/react-slot',
            '@radix-ui/react-dialog',
            '@radix-ui/react-checkbox',
            '@radix-ui/react-label',
            '@radix-ui/react-select',
            '@radix-ui/react-scroll-area',
          ],
          'vendor-motion': ['framer-motion'],
          'vendor-i18n': ['i18next', 'react-i18next', 'i18next-http-backend', 'i18next-browser-languagedetector'],
          'vendor-syntax': ['react-syntax-highlighter'],
          'admin': [
            '@dnd-kit/core',
            '@dnd-kit/sortable',
            '@dnd-kit/utilities',
          ],
        },
      },
    },
  },
});
