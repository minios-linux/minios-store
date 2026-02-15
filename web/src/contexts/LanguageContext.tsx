import React, { createContext, useContext, useCallback } from 'react';
import { useTranslation as useI18nTranslation } from 'react-i18next';
import { getAvailableLanguages, type LanguageMeta } from '../i18n';

interface LanguageContextType {
  language: string;
  changeLanguage: (lang: string) => void;
  t: (key: string) => string;
  availableLanguages: LanguageMeta[];
}

const LanguageContext = createContext<LanguageContextType | undefined>(undefined);

export const LanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { t: i18nT, i18n } = useI18nTranslation();

  const changeLanguage = useCallback((lang: string) => {
    i18n.changeLanguage(lang);
    // Update URL with lang parameter
    const url = new URL(window.location.href);
    url.searchParams.set('lang', lang);
    window.history.replaceState({}, '', url.toString());
  }, [i18n]);

  const t = useCallback((key: string): string => {
    return i18nT(key);
  }, [i18nT]);

  return (
    <LanguageContext.Provider value={{ 
      language: i18n.language, 
      changeLanguage, 
      t, 
      availableLanguages: getAvailableLanguages()
    }}>
      {children}
    </LanguageContext.Provider>
  );
};

export const useTranslation = () => {
  const context = useContext(LanguageContext);
  if (context === undefined) {
    throw new Error('useTranslation must be used within a LanguageProvider');
  }
  return context;
};
