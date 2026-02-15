import { useState, useEffect, useCallback } from 'react';
import { Plus, Trash2, Edit, Save, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import { useTranslation } from '@/contexts/LanguageContext';
import { IconPicker } from './IconPicker';
import { DynamicIcon } from '@/components/DynamicIcon';
import { SortableList, SortableItem } from './SortableList';
import type { Category } from '@/lib/types';

interface CategoryManagerProps {
  onCategoriesChange?: (categories: Category[]) => void;
}

const EMPTY_CATEGORY: Category = {
  id: '',
  nameKey: '',
  name: '',
  icon: 'Package',
  order: 0,
  enabled: true,
};

export function CategoryManager({ onCategoriesChange }: CategoryManagerProps) {
  const { t } = useTranslation();
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingCategory, setEditingCategory] = useState<Category | null>(null);
  const [formData, setFormData] = useState<Category>(EMPTY_CATEGORY);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const fetchCategories = useCallback(async () => {
    try {
      const res = await fetch('/api/categories');
      if (res.ok) {
        const data = await res.json();
        const cats = Array.isArray(data) ? data : data.categories || [];
        setCategories(cats);
        onCategoriesChange?.(cats);
      }
    } catch (err) {
      console.error('Failed to fetch categories:', err);
    } finally {
      setLoading(false);
    }
  }, [onCategoriesChange]);

  useEffect(() => {
    fetchCategories();
  }, [fetchCategories]);

  const handleReorder = (reordered: Category[]) => {
    const updated = reordered.map((cat, i) => ({ ...cat, order: i + 1 }));
    setCategories(updated);
    setHasChanges(true);
  };

  const openCreateDialog = () => {
    setEditingCategory(null);
    setFormData({
      ...EMPTY_CATEGORY,
      order: categories.length + 1,
    });
    setDialogOpen(true);
  };

  const openEditDialog = (category: Category) => {
    setEditingCategory(category);
    setFormData({ ...category });
    setDialogOpen(true);
  };

  const handleFormSave = () => {
    if (!formData.id.trim()) {
      toast.error(t('Category ID is required'));
      return;
    }
    if (!formData.name.trim()) {
      toast.error(t('Category name is required'));
      return;
    }

    // Check for duplicate ID on create
    if (!editingCategory && categories.some(c => c.id === formData.id.trim())) {
      toast.error(t('A category with this ID already exists'));
      return;
    }

    const categoryToSave: Category = {
      ...formData,
      id: formData.id.trim(),
      name: formData.name.trim(),
      nameKey: formData.nameKey.trim() || `category.${formData.id.trim()}`,
    };

    if (editingCategory) {
      setCategories(prev => prev.map(c => c.id === editingCategory.id ? categoryToSave : c));
    } else {
      setCategories(prev => [...prev, categoryToSave]);
    }

    setHasChanges(true);
    setDialogOpen(false);
    onCategoriesChange?.(categories);
  };

  const handleDeleteCategory = (id: string) => {
    setCategories(prev => prev.filter(c => c.id !== id).map((c, i) => ({ ...c, order: i + 1 })));
    setHasChanges(true);
    setDeleteConfirm(null);
  };

  const handleSaveAll = async () => {
    setSaving(true);
    try {
      const res = await fetch('/api/categories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(categories),
      });

      if (res.ok) {
        toast.success(t('Categories saved'));
        setHasChanges(false);
        onCategoriesChange?.(categories);
      } else {
        toast.error(t('Failed to save categories'));
      }
    } catch {
      toast.error(t('Failed to save categories'));
    } finally {
      setSaving(false);
    }
  };

  const handleDiscard = () => {
    fetchCategories();
    setHasChanges(false);
  };

  if (loading) {
    return <div className="p-4">{t('Loading categories...')}</div>;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-2xl font-bold">{t('Categories')}</h2>
          <p className="text-muted-foreground">
            {t('Drag to reorder. Changes are saved manually.')}
          </p>
        </div>
        <div className="flex gap-2">
          {hasChanges && (
            <Button variant="outline" onClick={handleDiscard} className="gap-2">
              <X className="w-4 h-4" />
              {t('Discard')}
            </Button>
          )}
          <Button
            onClick={handleSaveAll}
            disabled={!hasChanges || saving}
            className="gap-2"
          >
            <Save className="w-4 h-4" />
            {saving ? t('Saving...') : t('Save Changes')}
          </Button>
          <Button onClick={openCreateDialog} className="gap-2">
            <Plus className="w-4 h-4" />
            {t('Add Category')}
          </Button>
        </div>
      </div>

      {/* Category list with drag-and-drop */}
      {categories.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          <p>{t('No categories yet. Create your first category!')}</p>
        </div>
      ) : (
        <SortableList
          items={categories}
          getItemId={cat => cat.id}
          onReorder={handleReorder}
          className="space-y-2"
          renderItem={(category) => (
            <SortableItem key={category.id} id={category.id} className="category-admin-item">
              <div className="category-admin-content">
                <div className="category-admin-icon">
                  <DynamicIcon name={category.icon} size={20} />
                </div>
                <div className="category-admin-info">
                  <div className="category-admin-name">
                    {category.name}
                    {category.enabled === false && (
                      <span className="text-muted-foreground text-xs ml-2">({t('disabled')})</span>
                    )}
                  </div>
                  <div className="category-admin-key text-xs text-muted-foreground">
                    {category.nameKey} &bull; order: {category.order}
                  </div>
                </div>
                <div className="category-admin-actions">
                  <Button variant="ghost" size="sm" onClick={() => openEditDialog(category)} title={t('Edit')}>
                    <Edit className="w-4 h-4" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setDeleteConfirm(category.id)} title={t('Delete')}>
                    <Trash2 className="w-4 h-4 text-destructive" />
                  </Button>
                </div>
              </div>
            </SortableItem>
          )}
        />
      )}

      {/* Delete confirmation */}
      <Dialog open={deleteConfirm !== null} onOpenChange={() => setDeleteConfirm(null)}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t('Delete Category')}</DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground">
            {t('Are you sure you want to delete this category? Recipes in this category will become uncategorized.')}
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteConfirm(null)}>{t('Cancel')}</Button>
            <Button variant="destructive" onClick={() => deleteConfirm && handleDeleteCategory(deleteConfirm)}>
              {t('Delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create/Edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle>
              {editingCategory ? t('Edit Category') : t('Create Category')}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t('Category ID')}</Label>
                <Input
                  placeholder="e.g. internet"
                  value={formData.id}
                  onChange={e => setFormData(prev => ({
                    ...prev,
                    id: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'),
                    nameKey: `category.${e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-')}`,
                  }))}
                  disabled={!!editingCategory}
                />
              </div>
              <div className="space-y-2">
                <Label>{t('Name')}</Label>
                <Input
                  placeholder="e.g. Internet"
                  value={formData.name}
                  onChange={e => setFormData(prev => ({ ...prev, name: e.target.value }))}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t('Icon')}</Label>
                <IconPicker
                  value={formData.icon}
                  onChange={icon => setFormData(prev => ({ ...prev, icon }))}
                  allowEmpty={false}
                />
              </div>
              <div className="space-y-2">
                <Label>{t('Translation Key')}</Label>
                <Input
                  placeholder="category.internet"
                  value={formData.nameKey}
                  onChange={e => setFormData(prev => ({ ...prev, nameKey: e.target.value }))}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t('Sort Order')}</Label>
                <Input
                  type="number"
                  value={formData.order}
                  onChange={e => setFormData(prev => ({ ...prev, order: parseInt(e.target.value) || 0 }))}
                />
              </div>
              <div className="flex items-center gap-3 pt-6">
                <Switch
                  checked={formData.enabled !== false}
                  onCheckedChange={v => setFormData(prev => ({ ...prev, enabled: v }))}
                />
                <Label>{t('Enabled')}</Label>
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('Cancel')}</Button>
            <Button onClick={handleFormSave}>
              {editingCategory ? t('Update') : t('Create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
