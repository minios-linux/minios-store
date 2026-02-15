import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import HttpBackend from 'i18next-http-backend';
import LanguageDetector from 'i18next-browser-languagedetector';

// Get base URL for assets
const getBaseUrl = () => import.meta.env.BASE_URL || '/';

// Language metadata from translation files
export interface LanguageMeta {
  code: string;
  name: string;
  flag: string;
}

// Fetch available languages with metadata dynamically
// In dev: /api/languages (Vite plugin scans folder and reads _meta from files)
// In prod: /translations/languages.json (generated at build time)
async function fetchLanguagesWithMeta(): Promise<LanguageMeta[]> {
  if (import.meta.env.DEV) {
    try {
      const response = await fetch('/api/languages');
      if (response.ok) {
        return await response.json();
      }
    } catch {
      // API not available
    }
  }

  try {
    const response = await fetch(`${getBaseUrl()}translations/languages.json`);
    if (response.ok) {
      return await response.json();
    }
  } catch {
    // Fallback to English only
  }

  return [{ code: 'en', name: 'English', flag: '🇺🇸' }];
}

// Store available languages with metadata for use by other components
let languagesCache: LanguageMeta[] = [{ code: 'en', name: 'English', flag: '🇺🇸' }];

export function getAvailableLanguages(): LanguageMeta[] {
  return languagesCache;
}

// Initialize i18n with dynamic language discovery
export async function initI18n(): Promise<typeof i18n> {
  languagesCache = await fetchLanguagesWithMeta();
  const supportedLngs = languagesCache.map(l => l.code);

  await i18n
    .use(HttpBackend)
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
      fallbackLng: 'en',
      supportedLngs,

      detection: {
        order: ['querystring', 'navigator', 'htmlTag'],
        lookupQuerystring: 'lang',
        caches: ['localStorage'],
      },

      backend: {
        loadPath: `${getBaseUrl()}translations/{{lng}}.json`,
        parse: (data: string) => {
          const parsed = JSON.parse(data);
          // Original site uses { translations: {...} } structure
          const translations = parsed.translations || parsed;
          // Filter out empty strings so fallback works
          const filtered: Record<string, string> = {};
          for (const [key, value] of Object.entries(translations)) {
            if (typeof value === 'string' && value.trim() !== '') {
              filtered[key] = value;
            }
          }
          return filtered;
        },
      },

      interpolation: {
        escapeValue: false,
      },

      react: {
        useSuspense: true,
      },
    });

  return i18n;
}

export default i18n;
