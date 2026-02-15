import { useTranslation } from '@/contexts/LanguageContext';
import { DynamicIcon } from '@/components/DynamicIcon';
import type { Category } from '@/lib/types';

interface CategoryBarProps {
  categories: Category[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

const CategoryBar: React.FC<CategoryBarProps> = ({ categories, selectedId, onSelect }) => {
  const { t } = useTranslation();

  const sortedCategories = [...categories]
    .filter(c => c.enabled !== false)
    .sort((a, b) => a.order - b.order);

  return (
    <div className="category-bar">
      <button
        className={`category-chip ${selectedId === null ? 'active' : ''}`}
        onClick={() => onSelect(null)}
      >
        <DynamicIcon name="Package" size={16} />
        {t('All')}
      </button>
      {sortedCategories.map(cat => (
        <button
          key={cat.id}
          className={`category-chip ${selectedId === cat.id ? 'active' : ''}`}
          onClick={() => onSelect(cat.id === selectedId ? null : cat.id)}
        >
          <DynamicIcon name={cat.icon} size={16} />
          {t(cat.nameKey) !== cat.nameKey ? t(cat.nameKey) : cat.name}
        </button>
      ))}
    </div>
  );
};

export default CategoryBar;
