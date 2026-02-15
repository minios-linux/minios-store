import { useState, useEffect, useCallback } from 'react';
import { X, Package, FolderOpen, Languages, Sun, Moon, Store, Search } from 'lucide-react';
import { useTranslation } from '@/contexts/LanguageContext';
import { useTheme } from '@/contexts/ThemeContext';
import { RecipeManager } from './RecipeManager';
import { CategoryManager } from './CategoryManager';
import { TranslationEditor } from './TranslationEditor';
import { SEOManager } from './SEOManager';
import type { Category } from '@/lib/types';

type AdminSection = 'recipes' | 'categories' | 'seo' | 'translations';

const SECTIONS: { id: AdminSection; labelKey: string; icon: React.ReactNode }[] = [
  { id: 'recipes', labelKey: 'Recipes', icon: <Package className="w-4 h-4" /> },
  { id: 'categories', labelKey: 'Categories', icon: <FolderOpen className="w-4 h-4" /> },
  { id: 'seo', labelKey: 'SEO', icon: <Search className="w-4 h-4" /> },
  { id: 'translations', labelKey: 'Translations', icon: <Languages className="w-4 h-4" /> },
];

interface Props {
  onClose: () => void;
}

export function AdminPanel({ onClose }: Props) {
  const { t } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const [activeSection, setActiveSection] = useState<AdminSection>('recipes');
  const [categories, setCategories] = useState<Category[]>([]);

  // Fetch categories for RecipeManager
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/categories');
        if (res.ok && !cancelled) {
          const data = await res.json();
          setCategories(Array.isArray(data) ? data : data.categories || []);
        }
      } catch {
        // Will use empty array
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleCategoriesChange = useCallback((cats: Category[]) => {
    setCategories(cats);
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div className="admin-panel">
      {/* Top Header */}
      <header className="admin-top-header">
        <div className="admin-top-header-inner">
          <div className="admin-logo">
            <Store size={20} style={{ color: 'var(--accent)' }} />
            <span className="admin-logo-text">MiniOS Store Admin</span>
          </div>

          {/* Section tabs */}
          <nav className="admin-top-nav">
            {SECTIONS.map(section => (
              <button
                key={section.id}
                className={`admin-top-nav-btn ${activeSection === section.id ? 'active' : ''}`}
                onClick={() => setActiveSection(section.id)}
              >
                {section.icon}
                <span>{t(section.labelKey)}</span>
              </button>
            ))}
          </nav>

          <div className="admin-header-actions">
            <button
              onClick={toggleTheme}
              className="admin-theme-btn"
              title={t('Toggle theme')}
            >
              {theme === 'light' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
            </button>
            <button onClick={onClose} className="admin-close-btn" title={t('Close Admin Panel')}>
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="admin-main-content">
        <div className="container">
          {activeSection === 'recipes' && (
            <RecipeManager categories={categories} />
          )}
          {activeSection === 'categories' && (
            <CategoryManager onCategoriesChange={handleCategoriesChange} />
          )}
          {activeSection === 'seo' && (
            <SEOManager />
          )}
          {activeSection === 'translations' && (
            <TranslationEditor />
          )}
        </div>
      </main>
    </div>
  );
}
