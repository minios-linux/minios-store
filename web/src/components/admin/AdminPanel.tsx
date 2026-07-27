import { useState, useEffect, useCallback, useRef } from 'react';
import { X, Package, FolderOpen, Languages, Sun, Moon, Search, Save, RefreshCw, Undo2 } from 'lucide-react';
import { useTranslation } from '@/contexts/LanguageContext';
import { useTheme } from '@/contexts/ThemeContext';
import { RecipeManager } from './RecipeManager';
import { CategoryManager } from './CategoryManager';
import { TranslationEditor } from './TranslationEditor';
import { SEOManager } from './SEOManager';
import type { Category } from '@/lib/types';
import type { ManagerHandle } from './types';

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
  const [saveState, setSaveState] = useState({ hasChanges: false, saving: false });
  
  // Refs for each manager
  const recipeManagerRef = useRef<ManagerHandle>(null);
  const categoryManagerRef = useRef<ManagerHandle>(null);
  const seoManagerRef = useRef<ManagerHandle>(null);

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

  const handleStateChange = useCallback((state: { hasChanges: boolean; saving: boolean }) => {
    setSaveState(state);
  }, []);
  
  const handleSave = () => {
    if (activeSection === 'recipes') recipeManagerRef.current?.save();
    else if (activeSection === 'categories') categoryManagerRef.current?.save();
    else if (activeSection === 'seo') seoManagerRef.current?.save();
  };
  
  const handleDiscard = () => {
    if (activeSection === 'recipes') recipeManagerRef.current?.discard();
    else if (activeSection === 'categories') categoryManagerRef.current?.discard();
    else if (activeSection === 'seo') seoManagerRef.current?.discard();
  };
  
  // Determine if save button should be shown and enabled
  const showSaveButton = activeSection !== 'translations';
  const canSave = saveState.hasChanges && !saveState.saving;

  // Keyboard shortcuts: Ctrl+S to save, Escape to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl+S or Cmd+S to save
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (canSave && showSaveButton) {
          handleSave();
        }
      }
      // Escape to close
      if (e.key === 'Escape') {
        // Don't close if there are unsaved changes - let user use discard first
        if (!saveState.hasChanges) {
          onClose();
        }
      }
    };
    
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [canSave, showSaveButton, saveState.hasChanges, onClose]);

  return (
    <div className="admin-panel">
      {/* Top Header */}
      <header className="admin-top-header">
        <div className="admin-top-header-inner">
          <div className="admin-logo">
            <img src="/minios_icon.svg" width="28" height="28" alt={t('Logo')} />
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
            {showSaveButton && canSave && (
              <button 
                onClick={handleDiscard} 
                className="admin-discard-btn"
                title={t('Discard Changes')}
              >
                <Undo2 className="w-5 h-5" />
              </button>
            )}
            {showSaveButton && (
              <button 
                onClick={handleSave} 
                disabled={!canSave}
                className={`admin-save-btn ${canSave ? 'has-changes' : ''}`}
                title={t('Save Changes')}
              >
                {saveState.saving ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />}
              </button>
            )}
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
            <RecipeManager 
              ref={recipeManagerRef}
              categories={categories}
              onStateChange={handleStateChange}
            />
          )}
          {activeSection === 'categories' && (
            <CategoryManager 
              ref={categoryManagerRef}
              onCategoriesChange={handleCategoriesChange}
              onStateChange={handleStateChange}
            />
          )}
          {activeSection === 'seo' && (
            <SEOManager 
              ref={seoManagerRef}
              onStateChange={handleStateChange}
            />
          )}
          {activeSection === 'translations' && (
            <TranslationEditor />
          )}
        </div>
      </main>
    </div>
  );
}
