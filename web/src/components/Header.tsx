import { useState, useEffect, useRef } from 'react';
import { useTranslation } from '@/contexts/LanguageContext';
import { useTheme } from '@/contexts/ThemeContext';
import { DynamicIcon } from '@/components/DynamicIcon';
import { Sun, Moon, Languages, ChevronDown, Search, Store, ShoppingCart, X, Download, Trash2, Package, Layers, CheckCircle2, XCircle, Monitor } from 'lucide-react';
import type { ConnectionStatus, SystemInfo, Recipe, CartItem, InstallRecipe, InstallMode, PackagingMode } from '@/lib/types';
import { installViaUriScheme } from '@/lib/websocket';

interface HeaderProps {
  connectionStatus: ConnectionStatus;
  systemInfo?: SystemInfo | null;
  // Search props
  searchValue: string;
  onSearchChange: (value: string) => void;
  // Cart props
  cartItems: CartItem[];
  recipes: Recipe[];
  installMode: InstallMode;
  packaging: PackagingMode;
  moduleName: string;
  onSetInstallMode: (mode: InstallMode) => void;
  onSetPackaging: (packaging: PackagingMode) => void;
  onSetModuleName: (name: string) => void;
  onRemoveItem: (recipeId: string) => void;
  onClearCart: () => void;
  onInstall: (recipes: InstallRecipe[]) => void;
  installProgress?: any | null;
  onRestoreProgress?: () => void;
}

const Header: React.FC<HeaderProps> = ({
  connectionStatus,
  systemInfo,
  searchValue,
  onSearchChange,
  cartItems,
  recipes,
  installMode,
  packaging,
  moduleName,
  onSetInstallMode,
  onSetPackaging,
  onSetModuleName,
  onRemoveItem,
  onClearCart,
  onInstall,
  installProgress,
  onRestoreProgress,
}) => {
  const { t, language, changeLanguage, availableLanguages } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const [langMenuOpen, setLangMenuOpen] = useState(false);
  const [langSearch, setLangSearch] = useState('');
  const [mobileLangOpen, setMobileLangOpen] = useState(false);
  const [cartOpen, setCartOpen] = useState(false);
  const cartRef = useRef<HTMLDivElement>(null);
  const mobileCartRef = useRef<HTMLDivElement>(null);

  // Resolve cart items to full recipe data
  const cartRecipes = cartItems
    .map(item => {
      const recipe = recipes.find(r => r.id === item.recipeId);
      return recipe ? { item, recipe } : null;
    })
    .filter((x): x is { item: CartItem; recipe: Recipe } => x !== null);

  // Close dropdowns on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!(e.target as HTMLElement).closest?.('.lang-selector')) {
        setLangMenuOpen(false);
      }
      const inCart = cartRef.current?.contains(target) || mobileCartRef.current?.contains(target);
      if (!inCart) {
        setCartOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleChangeLanguage = (lang: string) => {
    changeLanguage(lang);
    setLangMenuOpen(false);
    setMobileLangOpen(false);
  };

  const handleInstall = () => {
    const installRecipes: InstallRecipe[] = cartRecipes.map(({ recipe }) => ({
      id: recipe.id,
      name: recipe.name,
      method: recipe.method,
      level: recipe.level,
      compression: recipe.compression,
      packages: recipe.packages,
      script: recipe.script,
      debUrl: recipe.debUrl,
    }));

    if (connectionStatus === 'connected') {
      onInstall(installRecipes);
    } else {
      installViaUriScheme(installRecipes, installMode, packaging, systemInfo?.codename, systemInfo?.arch);
    }
    setCartOpen(false);
  };

  const filteredLanguages = availableLanguages.filter(l =>
    l.name.toLowerCase().includes(langSearch.toLowerCase()) ||
    l.code.toLowerCase().includes(langSearch.toLowerCase())
  );

  const statusLabel = connectionStatus === 'connected'
    ? t('Connected')
    : connectionStatus === 'connecting'
      ? t('Connecting...')
      : t('Offline');

  const renderCartContent = () => (
    <>
      <div className="cart-dropdown-header">
        <span className="cart-dropdown-title">
          {t('Cart')}
          {cartItems.length > 0 && (
            <span className="cart-count">{cartItems.length}</span>
          )}
        </span>
        {cartItems.length > 0 && (
          <button
            className="cart-dropdown-clear"
            onClick={onClearCart}
            title={t('Clear cart')}
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>

      <div className="cart-dropdown-items">
        {cartRecipes.length === 0 ? (
          <div className="cart-empty">
            <Package size={36} />
            <p>{t('Your cart is empty')}</p>
            <p style={{ fontSize: '0.7rem', opacity: 0.7 }}>
              {t('Add applications to install them as modules')}
            </p>
          </div>
        ) : (
          cartRecipes.map(({ item, recipe }) => (
            <div key={item.recipeId} className="cart-item">
              <div className="cart-item-icon">
                {recipe.icon.startsWith('/') || recipe.icon.startsWith('http') ? (
                  <img src={recipe.icon} alt={recipe.name} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
                ) : (
                  <DynamicIcon name={recipe.icon} size={16} />
                )}
              </div>
              <div className="cart-item-info">
                <div className="cart-item-name">{recipe.name}</div>
              </div>
              <button
                className="cart-item-remove"
                onClick={() => onRemoveItem(item.recipeId)}
                title={t('Remove')}
              >
                <X size={14} />
              </button>
            </div>
          ))
        )}
      </div>

      {cartItems.length > 0 && (
        <div className="cart-dropdown-footer">
          {/* Install mode selector */}
          <div className="cart-mode-selector">
            <button
              className={`cart-mode-btn ${installMode === 'module' ? 'active' : ''}`}
              onClick={() => onSetInstallMode('module')}
              title={t('Build as module (.sb file)')}
            >
              <Package size={14} />
              {t('Module')}
            </button>
            <button
              className={`cart-mode-btn ${installMode === 'system' ? 'active' : ''}`}
              onClick={() => onSetInstallMode('system')}
              title={t('Install directly to system')}
            >
              <Download size={14} />
              {t('System')}
            </button>
          </div>

          {/* Packaging options (only for module mode, 2+ items) */}
          {installMode === 'module' && cartRecipes.length > 1 && (
            <div className="cart-packaging-selector">
              <button
                className={`cart-packaging-btn ${packaging === 'single' ? 'active' : ''}`}
                onClick={() => onSetPackaging('single')}
                title={t('Combine all into one module')}
              >
                <Package size={14} />
                {t('Single module')}
              </button>
              <button
                className={`cart-packaging-btn ${packaging === 'separate' ? 'active' : ''}`}
                onClick={() => onSetPackaging('separate')}
                title={t('Build each recipe as a separate module')}
              >
                <Layers size={14} />
                {t('Separate modules')}
              </button>
            </div>
          )}

          {/* Module name input (only for module mode, single packaging) */}
          {installMode === 'module' && packaging === 'single' && (
            <div className="cart-module-name">
              <input
                type="text"
                className="cart-module-name-input"
                placeholder={t('Module name (optional)')}
                value={moduleName}
                onChange={(e) => onSetModuleName(e.target.value)}
                onClick={(e) => e.stopPropagation()}
              />
            </div>
          )}

          <div className="cart-status-line">
            {connectionStatus === 'disconnected' && cartRecipes.length > 0 && (
              <span>{t('Offline')} — {t('Install')} {t('via URI scheme')}</span>
            )}
          </div>
          <button
            className="cart-install-btn"
            onClick={handleInstall}
            disabled={cartRecipes.length === 0}
          >
            <Download size={16} />
            {t('Install')} ({cartRecipes.length})
          </button>
        </div>
      )}
    </>
  );

  return (
    <>
      <header>
        <div className="container nav-wrapper">
          <a href="#" className="logo" onClick={(e) => { e.preventDefault(); window.scrollTo({ top: 0, behavior: 'smooth' }); }}>
            <Store size={28} style={{ color: 'var(--accent)' }} />
            <span className="logo-text">MiniOS Store</span>
          </a>

          <div className="header-search">
            <Search size={16} className="header-search-icon" />
            <input
              type="text"
              placeholder={t('Search applications...')}
              value={searchValue}
              onChange={(e) => onSearchChange(e.target.value)}
            />
          </div>

          <div className="header-actions">
            {/* Background install indicator */}
            {installProgress && installProgress.active && onRestoreProgress && (
              <button
                className={`connection-status installing-indicator installing-${installProgress.status}`}
                onClick={onRestoreProgress}
                title={t('Show installation progress')}
              >
                {installProgress.status === 'running' && (
                  <Download size={16} className="install-pulse-icon" />
                )}
                {installProgress.status === 'complete' && (
                  <CheckCircle2 size={16} className="install-success-icon" />
                )}
                {installProgress.status === 'error' && (
                  <XCircle size={16} className="install-error-icon" />
                )}
                {installProgress.status === 'cancelled' && (
                  <XCircle size={16} className="install-error-icon" />
                )}
                <span>
                  {installProgress.status === 'running' && t('Installing...')}
                  {installProgress.status === 'complete' && t('Installation complete')}
                  {installProgress.status === 'error' && t('Installation failed')}
                  {installProgress.status === 'cancelled' && t('Installation cancelled')}
                </span>
              </button>
            )}

            {/* Connection status */}
            <div className={`connection-status ${connectionStatus}`}>
              <span className="connection-dot" />
              <span>{statusLabel}</span>
            </div>

            {/* Distribution badge */}
            {systemInfo?.codename && (
              <div className="distro-badge" title={systemInfo.name || systemInfo.codename}>
                <Monitor size={14} />
                <span>{systemInfo.codename}{systemInfo.arch ? ` (${systemInfo.arch})` : ''}</span>
              </div>
            )}

            {/* Cart button + dropdown */}
            <div className={`cart-selector ${cartOpen ? 'active' : ''}`} ref={cartRef}>
              <button
                className="cart-btn"
                onClick={(e) => { e.stopPropagation(); setCartOpen(!cartOpen); }}
                title={t('Cart')}
              >
                <ShoppingCart size={18} />
                {cartItems.length > 0 && (
                  <span className="cart-badge">{cartItems.length}</span>
                )}
              </button>
              <div className="cart-dropdown">
                {renderCartContent()}
              </div>
            </div>

            {/* Theme toggle */}
            <button className="theme-toggle" onClick={toggleTheme} title={t('Toggle theme')}>
              {theme === 'light' ? <Sun size={20} /> : <Moon size={20} />}
            </button>

            {/* Language selector (desktop) */}
            <div className={`lang-selector ${langMenuOpen ? 'active' : ''}`}>
              <button className="lang-btn" onClick={(e) => { e.stopPropagation(); setLangMenuOpen(!langMenuOpen); }}>
                <Languages size={18} />
                <span>{language.toUpperCase().substring(0, 2)}</span>
                <ChevronDown size={16} />
              </button>
              <div className="lang-dropdown">
                <div className="lang-search-wrapper">
                  <Search size={16} className="lang-search-icon" />
                  <input
                    type="text"
                    className="lang-search"
                    placeholder="Search..."
                    value={langSearch}
                    onChange={(e) => setLangSearch(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                  />
                </div>
                <div className="lang-list">
                  {filteredLanguages.map(lang => (
                    <a
                      key={lang.code}
                      href="#"
                      onClick={(e) => { e.preventDefault(); handleChangeLanguage(lang.code); }}
                      className={language === lang.code || language.startsWith(lang.code + '-') ? 'active' : ''}
                    >
                      {lang.flag} {lang.name}
                    </a>
                  ))}
                </div>
              </div>
            </div>

            {/* Mobile buttons */}
            <button className="mobile-menu-btn" onClick={() => setMobileLangOpen(!mobileLangOpen)} title="Language">
              <Languages size={24} />
            </button>
          </div>
        </div>
      </header>

      {/* Mobile overlay */}
      <div
        className={`mobile-overlay ${mobileLangOpen || cartOpen ? 'active' : ''}`}
        onClick={() => { setMobileLangOpen(false); setCartOpen(false); }}
      />

      {/* Mobile Language Menu */}
      <nav className={`mobile-lang-menu ${mobileLangOpen ? 'active' : ''}`}>
        <div className="lang-search-wrapper mobile-search">
          <Search size={16} className="lang-search-icon" />
          <input
            type="text"
            className="lang-search"
            placeholder="Search..."
            value={langSearch}
            onChange={(e) => setLangSearch(e.target.value)}
          />
        </div>
        <div className="lang-list">
          {filteredLanguages.map(lang => (
            <a
              key={lang.code}
              href="#"
              onClick={(e) => { e.preventDefault(); handleChangeLanguage(lang.code); }}
              className={language === lang.code || language.startsWith(lang.code + '-') ? 'active' : ''}
            >
              {lang.flag} {lang.name}
            </a>
          ))}
        </div>
      </nav>

      {/* Mobile Cart Menu */}
      <div className={`mobile-cart-menu ${cartOpen ? 'active' : ''}`} ref={mobileCartRef}>
        {renderCartContent()}
      </div>
    </>
  );
};

export default Header;
