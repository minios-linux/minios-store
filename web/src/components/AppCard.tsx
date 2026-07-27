import { memo, useRef, useEffect, useState, useCallback } from 'react';
import { DynamicIcon } from '@/components/DynamicIcon';
import { useTranslation } from '@/contexts/LanguageContext';
import { Plus, Check } from 'lucide-react';
import type { Recipe, Category } from '@/lib/types';

interface AppCardProps {
  recipe: Recipe;
  category?: Category;
  inCart: boolean;
  onToggleCart: () => void;
  onOpenDetail: () => void;
}

const AppCard: React.FC<AppCardProps> = ({ recipe, category, inCart, onToggleCart, onOpenDetail }) => {
  const { t } = useTranslation();
  const pkgRef = useRef<HTMLSpanElement>(null);
  const [isTruncated, setIsTruncated] = useState(false);

  const checkTruncation = useCallback(() => {
    const el = pkgRef.current;
    if (el) {
      setIsTruncated(el.scrollWidth > el.clientWidth);
    }
  }, []);

  useEffect(() => {
    checkTruncation();
    window.addEventListener('resize', checkTruncation);
    return () => window.removeEventListener('resize', checkTruncation);
  }, [checkTruncation]);

  return (
    <div className="app-card" onClick={onOpenDetail}>
      <div className="app-card-header">
        <div className="app-card-icon">
          {recipe.appIcon ? (
            <img src={recipe.appIcon} alt={recipe.name} />
          ) : recipe.icon.startsWith('/') || recipe.icon.startsWith('http') ? (
            <img src={recipe.icon} alt={recipe.name} />
          ) : (
            <DynamicIcon name={recipe.icon} size={24} />
          )}
        </div>
        <div className="app-card-info">
          <div className="app-card-name">{recipe.name}</div>
        </div>
      </div>

      <div className="app-card-description">
        {recipe.description}
      </div>

      <div className="app-card-footer">
        <div className="app-card-tags">
          {category && (
            <span className="app-card-category">
              <DynamicIcon name={category.icon} size={12} />
              {category.name}
            </span>
          )}
          <span className={`app-card-method ${recipe.method}`}>
            {recipe.method}
          </span>
          {recipe.packages && recipe.packages.length > 0 && (
            <span
              ref={pkgRef}
              className={`app-card-package${isTruncated ? ' truncated' : ''}`}
              title={isTruncated ? recipe.packages[0] : undefined}
            >
              {recipe.packages[0]}
            </span>
          )}
        </div>
        <button
          className={`app-card-add-btn ${inCart ? 'in-cart' : ''}`}
          onClick={(e) => { e.stopPropagation(); onToggleCart(); }}
          title={inCart ? t('Remove from cart') : t('Add to cart')}
        >
          {inCart ? <Check size={16} /> : <Plus size={16} />}
        </button>
      </div>
    </div>
  );
};

export default memo(AppCard);
