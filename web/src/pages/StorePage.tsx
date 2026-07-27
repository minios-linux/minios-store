import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useTranslation } from '@/contexts/LanguageContext';
import { useWindowVirtualizer } from '@tanstack/react-virtual';
import Header from '@/components/Header';
import CategoryBar from '@/components/CategoryBar';
import AppCard from '@/components/AppCard';
import AppDetail from '@/components/AppDetail';
import InstallProgress, { INITIAL_PROGRESS_STATE } from '@/components/InstallProgress';
import type { InstallProgressState } from '@/components/InstallProgress';
import { Search } from 'lucide-react';
import { useRecipes, useCart, useCategories, useStoreFilter } from '@/hooks/use-store';
import { storeWs } from '@/lib/websocket';
import type { Recipe, InstallRecipe, ServerMessage, SystemInfo } from '@/lib/types';
import { Toaster, toast } from 'sonner';

interface StorePageProps {
  isDevMode?: boolean;
}

const StorePage: React.FC<StorePageProps> = ({ isDevMode = false }) => {
  const { t } = useTranslation();
  const { recipes } = useRecipes();
  const { categories } = useCategories();
  const cart = useCart(recipes);
  const setInstallMode = cart.setInstallMode;
  
  // WebSocket connection (we'll handle messages directly)
  const [connectionStatus, setConnectionStatus] = useState(storeWs.status);
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);

  const { filter, filteredRecipes, setSearch, setCategory } = useStoreFilter(recipes, categories, systemInfo?.codename, systemInfo?.arch);

  // Debounced search: local input state updates immediately,
  // actual filter search is debounced by 200ms
  const [searchInput, setSearchInput] = useState('');
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const handleSearchChange = useCallback((value: string) => {
    setSearchInput(value);
    clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => {
      setSearch(value);
    }, 200);
  }, [setSearch]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => clearTimeout(searchTimerRef.current);
  }, []);

  // Detail modal
  const [detailRecipe, setDetailRecipe] = useState<Recipe | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  // Install progress state
  const [progress, setProgress] = useState<InstallProgressState>(INITIAL_PROGRESS_STATE);
  const [progressMinimized, setProgressMinimized] = useState(false);

  // Limit output lines to prevent memory issues
  const MAX_OUTPUT_LINES = 2000;

  // Update page title
  useEffect(() => {
    document.title = `MiniOS Store - ${t('Application Store')}`;
  }, [t]);

  // Handle WebSocket messages directly (not through state)
  const handleWebSocketMessage = useCallback((msg: ServerMessage) => {
    switch (msg.type) {
      case 'install_status':
        // Restore installation state if server says it's installing
        if (msg.installing) {
          console.log('[StorePage] Restoring installation state from server:', msg);
          setProgress({
            active: true,
            status: 'running',
            recipeName: msg.recipeName || '',
            step: msg.step || '',
            current: msg.current || 0,
            total: msg.total || 1,
            outputLines: msg.outputLines || [],
            successful: msg.successful || [],
            failed: msg.failed || [],
          });
          // Start minimized - user can click to see full progress
          setProgressMinimized(true);
        }
        break;

      case 'install_start':
        console.log('[StorePage] Starting installation minimized, total:', msg.total);
        setProgress({
          active: true,
          status: 'running',
          recipeName: '',
          step: '',
          current: 0,
          total: msg.total,
          outputLines: [],
          successful: [],
          failed: [],
        });
        // Start minimized by default
        setProgressMinimized(true);
        break;

      case 'install_progress':
        setProgress(prev => ({
          ...prev,
          recipeName: msg.recipeName,
          step: msg.step,
          current: msg.current,
          total: msg.total,
        }));
        break;

      case 'output':
        setProgress(prev => {
          const lines = prev.outputLines.length >= MAX_OUTPUT_LINES
            ? [...prev.outputLines.slice(-MAX_OUTPUT_LINES + 1), msg.text]
            : [...prev.outputLines, msg.text];
          return { ...prev, outputLines: lines };
        });
        break;

      case 'log':
        // Append log messages to terminal output too
        setProgress(prev => {
          if (!prev.active) return prev;
          const prefix = msg.level === 'error' ? '>>> ERROR: '
            : msg.level === 'warn' ? '>>> WARN: '
            : '>>> ';
          const lines = prev.outputLines.length >= MAX_OUTPUT_LINES
            ? [...prev.outputLines.slice(-MAX_OUTPUT_LINES + 1), prefix + msg.message]
            : [...prev.outputLines, prefix + msg.message];
          return { ...prev, outputLines: lines };
        });
        if (msg.level === 'error') {
          toast.error(msg.message);
        }
        break;

      case 'install_complete': {
        const failed = msg.failed || [];
        setProgress(prev => ({
          ...prev,
          status: failed.length > 0 ? 'error' : 'complete',
          successful: msg.successful,
          failed,
        }));
        if (failed.length === 0) {
          cart.clearCart();
        } else {
          msg.successful.forEach(cart.removeItem);
        }
        break;
      }

      case 'module_location': {
        // Show module location notification (persistent - user must dismiss)
        const moduleInfo = msg.moduleName ? ` ${msg.moduleName}` : '';
        if (msg.isFallback) {
          toast.warning(
            <>
              {t('Modules saved to fallback location')}:{moduleInfo}
              <br />
              <button
                className="mt-2 px-3 py-1.5 bg-orange-600 hover:bg-orange-700 text-white rounded text-sm font-medium transition-colors"
                onClick={(e) => {
                  e.preventDefault();
                  storeWs.send({ type: 'open_folder', path: msg.directory });
                }}
              >
                {t('Open Folder')}
              </button>
            </>,
            { 
              duration: Infinity,
              description: t('Primary location was not writable. Manual activation required.'),
              closeButton: true,
            }
          );
        } else {
          toast.success(
            <>
              {t('Modules saved')}:{moduleInfo}
              <br />
              <button
                className="mt-2 px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white rounded text-sm font-medium transition-colors"
                onClick={(e) => {
                  e.preventDefault();
                  storeWs.send({ type: 'open_folder', path: msg.directory });
                }}
              >
                {t('Open Folder')}
              </button>
            </>,
            { 
              duration: Infinity,
              description: t('Manual activation required.'),
              closeButton: true,
            }
          );
        }
        break;
      }

      case 'install_error':
        setProgress(prev => ({
          ...prev,
          status: 'error',
          outputLines: [...prev.outputLines, `>>> ${t('Error')}: ${msg.error}`],
        }));
        break;
    }
  }, [cart, t]);

  // Setup WebSocket connection and message handling
  const handleWebSocketMessageRef = useRef(handleWebSocketMessage);
  useEffect(() => {
    handleWebSocketMessageRef.current = handleWebSocketMessage;
  }, [handleWebSocketMessage]);

  useEffect(() => {
    const unsubStatus = storeWs.onStatusChange((status) => {
      setConnectionStatus(status);
      
      // Request status when connected
      if (status === 'connected') {
        console.log('[StorePage] Connected, requesting install status');
        storeWs.send({ type: 'get_status' });
      }
    });
    
    const unsubMessage = storeWs.onMessage((msg: ServerMessage) => {
      console.log('[StorePage] Direct message:', msg.type, msg);
      
      // Handle system_info separately
      if (msg.type === 'system_info') {
        if (msg.is_native) {
          setInstallMode('system');
        }
        setSystemInfo({
          codename: msg.codename,
          id: msg.id,
          name: msg.name,
          version_id: msg.version_id,
          arch: msg.arch,
          is_native: msg.is_native,
        });
        return;
      }

      // Handle all other messages
      handleWebSocketMessageRef.current(msg);
    });
    
    storeWs.connect();

    return () => {
      unsubStatus();
      unsubMessage();
    };
  }, [setInstallMode]);

  const sendInstall = useCallback((installRecipes: InstallRecipe[]) => {
    const message: any = { 
      type: 'install', 
      recipes: installRecipes, 
      mode: cart.installMode 
    };
    
    // Add packaging for module mode
    if (cart.installMode === 'module') {
      message.packaging = cart.packaging;
      
      // Add moduleName if provided
      if (cart.moduleName.trim()) {
        message.moduleName = cart.moduleName.trim();
      }
    }
    
    storeWs.send(message);
  }, [cart.installMode, cart.packaging, cart.moduleName]);

  const sendCancel = useCallback(() => {
    storeWs.send({ type: 'cancel' });
  }, []);

  const handleCloseProgress = useCallback(() => {
    const isFinished = progress.status === 'complete' || progress.status === 'error' || progress.status === 'cancelled';
    if (isFinished) {
      setProgress(INITIAL_PROGRESS_STATE);
      setProgressMinimized(false);
    } else {
      // Minimize instead of close if still running
      setProgressMinimized(true);
    }
  }, [progress.status]);

  const handleCancelInstall = useCallback(() => {
    // Immediately show cancelling status in UI
    setProgress(prev => ({
      ...prev,
      status: 'cancelled',
    }));
    sendCancel();
  }, [sendCancel]);

  const handleOpenDetail = useCallback((recipe: Recipe) => {
    setDetailRecipe(recipe);
    setDetailOpen(true);
  }, []);

  const handleToggleCartFromDetail = useCallback(() => {
    if (!detailRecipe) return;
    const result = cart.toggleItem(detailRecipe.id);
    if (!result.success && result.reason) {
      toast.error(t(result.reason));
    }
  }, [detailRecipe, cart, t]);

  const handleToggleCart = useCallback((recipeId: string) => {
    const result = cart.toggleItem(recipeId);
    if (!result.success && result.reason) {
      toast.error(t(result.reason));
    }
  }, [cart, t]);

  const handleInstall = (installRecipes: InstallRecipe[]) => {
    sendInstall(installRecipes);
  };

  const categoryMap = new Map(categories.map(c => [c.id, c]));

  // ---- Virtualized Grid ----
  const CARD_MIN_WIDTH = 260;
  const GRID_GAP = 16;
  const CARD_HEIGHT = 170; // Approximate card height in px

  const gridContainerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);

  // Measure container width with ResizeObserver
  useEffect(() => {
    const el = gridContainerRef.current;
    if (!el) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width);
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Calculate columns from container width
  const columnCount = useMemo(() => {
    if (containerWidth <= 0) return 1;
    return Math.max(1, Math.floor((containerWidth + GRID_GAP) / (CARD_MIN_WIDTH + GRID_GAP)));
  }, [containerWidth]);

  // Group recipes into rows
  const rowCount = useMemo(() => {
    return Math.ceil(filteredRecipes.length / columnCount);
  }, [filteredRecipes.length, columnCount]);

  const virtualizer = useWindowVirtualizer({
    count: rowCount,
    estimateSize: () => CARD_HEIGHT,
    overscan: 5,
    gap: GRID_GAP,
  });

  return (
    <>
      <Header
        connectionStatus={connectionStatus}
        systemInfo={systemInfo}
        searchValue={searchInput}
        onSearchChange={handleSearchChange}
        cartItems={cart.items}
        recipes={recipes}
        installMode={cart.installMode}
        packaging={cart.packaging}
        moduleName={cart.moduleName}
        onSetInstallMode={cart.setInstallMode}
        onSetPackaging={cart.setPackaging}
        onSetModuleName={cart.setModuleName}
        onRemoveItem={cart.removeItem}
        onClearCart={cart.clearCart}
        onInstall={handleInstall}
        installProgress={progressMinimized ? progress : null}
        onRestoreProgress={() => setProgressMinimized(false)}
      />

      <div className="bg-mesh" />
      <div className="bg-noise" />

      <div className="container">
        <div className="store-layout">
          <div className="store-main">
            {/* Category bar */}
            <CategoryBar
              categories={categories}
              selectedId={filter.categoryId}
              onSelect={setCategory}
            />

            {/* Virtualized app grid */}
            <div
              ref={gridContainerRef}
              style={{
                width: '100%',
                position: 'relative',
                height: virtualizer.getTotalSize(),
              }}
            >
              {virtualizer.getVirtualItems().map((virtualRow) => {
                const startIndex = virtualRow.index * columnCount;
                const rowRecipes = filteredRecipes.slice(startIndex, startIndex + columnCount);

                return (
                  <div
                    key={virtualRow.key}
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      height: CARD_HEIGHT,
                      transform: `translateY(${virtualRow.start}px)`,
                    }}
                  >
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: `repeat(${columnCount}, 1fr)`,
                        gap: `${GRID_GAP}px`,
                        height: '100%',
                      }}
                    >
                      {rowRecipes.map(recipe => (
                        <AppCard
                          key={recipe.id}
                          recipe={recipe}
                          category={categoryMap.get(recipe.categoryId)}
                          inCart={cart.isInCart(recipe.id)}
                          onToggleCart={() => handleToggleCart(recipe.id)}
                          onOpenDetail={() => handleOpenDetail(recipe)}
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Empty state */}
            {filteredRecipes.length === 0 && recipes.length > 0 && (
              <div style={{
                textAlign: 'center',
                padding: '60px 20px',
                color: 'var(--text-muted)',
              }}>
                <Search size={48} style={{ opacity: 0.2, margin: '0 auto 16px' }} />
                <p>{t('No applications found')}</p>
              </div>
            )}

            {/* No recipes at all */}
            {recipes.length === 0 && (
              <div style={{
                textAlign: 'center',
                padding: '60px 20px',
                color: 'var(--text-muted)',
              }}>
                <Search size={48} style={{ opacity: 0.2, margin: '0 auto 16px' }} />
                <p style={{ fontSize: '1.1rem', marginBottom: '8px' }}>{t('No applications available')}</p>
                {isDevMode && (
                  <p style={{ fontSize: '0.85rem', opacity: 0.7 }}>
                    {t('Add recipes via the admin panel or place YAML files in the recipes/ directory')}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Detail modal */}
      <AppDetail
        recipe={detailRecipe}
        category={detailRecipe ? categoryMap.get(detailRecipe.categoryId) : undefined}
        open={detailOpen}
        onOpenChange={setDetailOpen}
        inCart={detailRecipe ? cart.isInCart(detailRecipe.id) : false}
        onToggleCart={handleToggleCartFromDetail}
      />

      {/* Install progress dialog */}
      <InstallProgress
        state={progress}
        open={progress.active && !progressMinimized}
        onClose={handleCloseProgress}
        onCancel={handleCancelInstall}
      />

      <Toaster position="bottom-right" />
    </>
  );
};

export default StorePage;
