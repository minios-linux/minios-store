import { memo } from 'react';
import { DynamicIcon } from '@/components/DynamicIcon';
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
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
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
            <span className="app-card-package">
              {recipe.packages[0]}
            </span>
          )}
        </div>
        <button
          className={`app-card-add-btn ${inCart ? 'in-cart' : ''}`}
          onClick={(e) => { e.stopPropagation(); onToggleCart(); }}
          title={inCart ? 'Remove from cart' : 'Add to cart'}
        >
          {inCart ? <Check size={16} /> : <Plus size={16} />}
        </button>
      </div>
    </div>
  );
};

export default memo(AppCard);
