import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from '@/contexts/LanguageContext';
import { DynamicIcon } from '@/components/DynamicIcon';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import ScriptViewer from '@/components/ScriptViewer';
import { Check, ShoppingCart, X, ChevronLeft, ChevronRight, ExternalLink } from 'lucide-react';
import { loadRecipeDetail } from '@/hooks/use-store';
import type { Recipe, Category } from '@/lib/types';

interface AppDetailProps {
  recipe: Recipe | null;
  category?: Category;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  inCart: boolean;
  onToggleCart: () => void;
}

/** Fields loaded on demand from the detail endpoint */
interface DetailFields {
  longDescription?: string;
  script?: string;
  screenshots?: string[];
}

const AppDetail: React.FC<AppDetailProps> = ({
  recipe,
  category,
  open,
  onOpenChange,
  inCart,
  onToggleCart,
}) => {
  const { t, language } = useTranslation();
  // Detail loading state: null=not loaded yet, empty=loading, object=loaded
  const [detail, setDetail] = useState<DetailFields | null>(null);
  // Lightbox: index into screenshots array, or -1 when closed
  const [lightboxIndex, setLightboxIndex] = useState(-1);

  // Reset detail state when dialog closes or recipe changes
  const prevRecipeId = recipe?.id;
  if (!open && detail !== null) {
    setDetail(null);
    setLightboxIndex(-1);
  }

  // Derive loading state: detail is null while loading, non-null when done
  const loadingDetail = open && detail === null;

  // Load recipe detail on open
  useEffect(() => {
    if (!open || !prevRecipeId) return;

    let cancelled = false;

    loadRecipeDetail(prevRecipeId, language).then((d) => {
      if (!cancelled) {
        setDetail(d);
      }
    }).catch(() => {
      if (!cancelled) {
        setDetail({});
      }
    });

    return () => { cancelled = true; };
  }, [open, prevRecipeId, language]);

  const longDescription = detail?.longDescription || recipe?.longDescription || recipe?.description || '';
  const script = detail?.script || recipe?.script;
  const screenshots = detail?.screenshots || recipe?.screenshots;
  const screenshotCount = screenshots?.length ?? 0;

  /** Get the small thumbnail URL for a screenshot path */
  const getThumbUrl = useCallback((src: string): string => {
    // /screenshots/pkg/1.png -> /screenshots/pkg/1_small.png
    const lastDot = src.lastIndexOf('.');
    if (lastDot === -1) return src;
    return src.slice(0, lastDot) + '_small' + src.slice(lastDot);
  }, []);

  /** Resolve screenshot path to full URL */
  const resolveScreenshot = useCallback((src: string): string =>
    src.startsWith('/') ? src : `/screenshots/${src}`, []);

  const lightboxPrev = useCallback(() => {
    setLightboxIndex(i => (i <= 0 ? screenshotCount - 1 : i - 1));
  }, [screenshotCount]);

  const lightboxNext = useCallback(() => {
    setLightboxIndex(i => (i >= screenshotCount - 1 ? 0 : i + 1));
  }, [screenshotCount]);

  const lightboxClose = useCallback(() => setLightboxIndex(-1), []);

  // Keyboard navigation for lightbox
  useEffect(() => {
    if (lightboxIndex < 0) return;

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        e.preventDefault();
        lightboxClose();
      } else if (e.key === 'ArrowLeft') {
        e.stopPropagation();
        lightboxPrev();
      } else if (e.key === 'ArrowRight') {
        e.stopPropagation();
        lightboxNext();
      }
    };

    // Use capture phase to intercept before Radix Dialog
    window.addEventListener('keydown', handleKey, true);
    return () => window.removeEventListener('keydown', handleKey, true);
  }, [lightboxIndex, lightboxClose, lightboxPrev, lightboxNext]);

  if (!recipe) return null;

  return (
    <>
      <Dialog
        open={open}
        modal={lightboxIndex < 0}
        onOpenChange={(value) => {
          // Don't close dialog when lightbox is open — Escape should close lightbox first
          if (lightboxIndex >= 0 && !value) return;
          onOpenChange(value);
        }}
      >
        <DialogContent
          className="app-detail-modal"
          onEscapeKeyDown={(e) => {
            // Let lightbox keyboard handler handle Escape
            if (lightboxIndex >= 0) e.preventDefault();
          }}
          onPointerDownOutside={(e) => {
            // When non-modal (lightbox open), prevent closing on outside clicks
            if (lightboxIndex >= 0) e.preventDefault();
          }}
          onInteractOutside={(e) => {
            if (lightboxIndex >= 0) e.preventDefault();
          }}
        >
          <DialogHeader>
            <DialogTitle className="sr-only">{recipe.name}</DialogTitle>
            <DialogDescription className="sr-only">{recipe.description}</DialogDescription>
          </DialogHeader>

          {/* Header */}
          <div className="app-detail-header">
            <div className="app-detail-icon">
              {recipe.appIcon ? (
                <img src={recipe.appIcon} alt={recipe.name} />
              ) : recipe.icon.startsWith('/') || recipe.icon.startsWith('http') ? (
                <img src={recipe.icon} alt={recipe.name} />
              ) : (
                <DynamicIcon name={recipe.icon} size={32} />
              )}
            </div>
            <div className="app-detail-title">
              <h2>{recipe.name}</h2>
              <div className="app-detail-badges">
                {category && (
                  <span className="app-card-category">
                    <DynamicIcon name={category.icon} size={12} />
                    {category.name}
                  </span>
                )}
                <span className={`app-card-method ${recipe.method}`}>
                  {recipe.method}
                </span>
              </div>
              {(recipe.developer || recipe.homepage) && (
                <div className="app-detail-meta">
                  {recipe.developer && (
                    <span className="app-detail-developer">{recipe.developer}</span>
                  )}
                  {recipe.homepage && (
                    <a
                      href={recipe.homepage}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="app-detail-homepage"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <ExternalLink size={12} />
                      {t('Homepage')}
                    </a>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Loading indicator for detail */}
          {loadingDetail && (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '20px' }}>
              <div className="loading-dots">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          )}

          {/* Description */}
          {!loadingDetail && (
            <div className="app-detail-section">
              <h4>{t('Description')}</h4>
              <div
                className="app-detail-description"
                dangerouslySetInnerHTML={{ __html: longDescription }}
              />
            </div>
          )}

          {/* Packages */}
          {recipe.packages && recipe.packages.length > 0 && (
            <div className="app-detail-section">
              <h4>{t('Packages')}</h4>
              <div className="app-detail-packages">
                {recipe.packages.map(pkg => (
                  <span key={pkg}>{pkg}</span>
                ))}
              </div>
            </div>
          )}

          {/* Script */}
          {!loadingDetail && script && (
            <div className="app-detail-section">
              <h4>{t('Installation Script')}</h4>
              <ScriptViewer code={script} language="bash" />
            </div>
          )}

          {/* Screenshots */}
          {!loadingDetail && screenshots && screenshots.length > 0 && (
            <div className="app-detail-section">
              <h4>{t('Screenshots')}</h4>
              <div className="screenshot-gallery">
                {screenshots.map((src, i) => {
                  const fullSrc = resolveScreenshot(src);
                  const thumbSrc = getThumbUrl(fullSrc);
                  return (
                    <div
                      key={i}
                      className={`screenshot-thumb ${lightboxIndex === i ? 'active' : ''}`}
                      onClick={() => setLightboxIndex(i)}
                    >
                      <img
                        src={thumbSrc}
                        alt={`${recipe.name} screenshot ${i + 1}`}
                        loading="lazy"
                        onError={(e) => {
                          // Fallback to full image if thumbnail doesn't exist
                          (e.target as HTMLImageElement).src = fullSrc;
                        }}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Add to Cart button */}
          <button
            className={`app-detail-add-btn ${inCart ? 'in-cart' : ''}`}
            onClick={onToggleCart}
          >
            {inCart ? (
              <>
                <Check size={18} />
                {t('In Cart')}
              </>
            ) : (
              <>
                <ShoppingCart size={18} />
                {t('Add to Cart')}
              </>
            )}
          </button>
        </DialogContent>
      </Dialog>

      {/* Screenshot lightbox — portaled to body, Dialog is non-modal when lightbox is open */}
      {lightboxIndex >= 0 && screenshots && screenshots[lightboxIndex] && createPortal(
        <div
          className="screenshot-lightbox"
          onClick={lightboxClose}
        >
          {/* Close button */}
          <button
            className="screenshot-lightbox-close"
            onClick={(e) => { e.stopPropagation(); lightboxClose(); }}
          >
            <X size={24} />
          </button>

          {/* Previous button */}
          {screenshotCount > 1 && (
            <button
              className="screenshot-lightbox-nav screenshot-lightbox-prev"
              onClick={(e) => { e.stopPropagation(); lightboxPrev(); }}
            >
              <ChevronLeft size={32} />
            </button>
          )}

          {/* Image */}
          <img
            src={resolveScreenshot(screenshots[lightboxIndex])}
            alt={`Screenshot ${lightboxIndex + 1} of ${screenshotCount}`}
            onClick={(e) => e.stopPropagation()}
          />

          {/* Next button */}
          {screenshotCount > 1 && (
            <button
              className="screenshot-lightbox-nav screenshot-lightbox-next"
              onClick={(e) => { e.stopPropagation(); lightboxNext(); }}
            >
              <ChevronRight size={32} />
            </button>
          )}

          {/* Counter */}
          {screenshotCount > 1 && (
            <div className="screenshot-lightbox-counter">
              {lightboxIndex + 1} / {screenshotCount}
            </div>
          )}
        </div>,
        document.body
      )}
    </>
  );
};

export default AppDetail;
