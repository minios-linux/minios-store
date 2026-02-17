import { useState, useEffect, useCallback, useMemo, forwardRef, useImperativeHandle } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Search, Edit, Trash2, Package, ChevronDown, ChevronUp, ChevronLeft, ChevronRight, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';
import { useTranslation } from '@/contexts/LanguageContext';
import { IconPicker } from './IconPicker';
import { DynamicIcon } from '@/components/DynamicIcon';
import type { Recipe, Category, InstallMethod, ModuleLevel, CompressionType, DistributionEntry } from '@/lib/types';
import { COMPRESSION_TYPES } from '@/lib/types';
import type { ManagerHandle, StateChangeCallback } from './types';
import ContentSkeleton from './ContentSkeleton';

interface RecipeManagerProps {
  categories: Category[];
  onStateChange?: StateChangeCallback;
}

const EMPTY_RECIPE: Recipe = {
  id: '',
  name: '',
  description: '',
  categoryId: '',
  icon: 'Package',
  method: 'apt',
  level: 'auto',
  compression: 'zstd',
  packages: [],
  script: '',
  debUrl: '',
  tags: [],
  screenshots: [],
  longDescription: '',
  enabled: true,
  order: 0,
};

export const RecipeManager = forwardRef<ManagerHandle, RecipeManagerProps>(
  ({ categories, onStateChange }, ref) => {
  const { t } = useTranslation();
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterCategory, setFilterCategory] = useState<string>('all');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingRecipe, setEditingRecipe] = useState<Recipe | null>(null);
  const [formData, setFormData] = useState<Recipe>(EMPTY_RECIPE);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [page, setPage] = useState(0);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    basic: true,
    install: true,
    meta: false,
    advanced: false,
  });

  // Temp state for comma-separated inputs
  const [packagesText, setPackagesText] = useState('');
  const [tagsText, setTagsText] = useState('');
  const [screenshotsText, setScreenshotsText] = useState('');

  // Notify parent that RecipeManager doesn't use bulk save/discard
  useEffect(() => {
    onStateChange?.({ hasChanges: false, saving: false });
  }, [onStateChange]);

  // Expose no-op methods via ref (RecipeManager saves immediately)
  useImperativeHandle(ref, () => ({
    save: () => {},
    discard: () => {},
  }));

  const fetchRecipes = useCallback(async () => {
    try {
      const res = await fetch('/api/recipes');
      if (res.ok) {
        const data = await res.json();
        setRecipes(Array.isArray(data) ? data : data.recipes || []);
      }
    } catch (err) {
      console.error('Failed to fetch recipes:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRecipes();
  }, [fetchRecipes]);

  const toggleSection = (section: string) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  const openCreateDialog = () => {
    setEditingRecipe(null);
    const newRecipe = { ...EMPTY_RECIPE, order: recipes.length };
    setFormData(newRecipe);
    setPackagesText('');
    setTagsText('');
    setScreenshotsText('');
    setExpandedSections({ basic: true, install: true, meta: false, advanced: false });
    setDialogOpen(true);
  };

  const openEditDialog = (recipe: Recipe) => {
    setEditingRecipe(recipe);
    setFormData({ ...recipe });
    setPackagesText(recipe.packages?.join(', ') || '');
    setTagsText(recipe.tags?.join(', ') || '');
    setScreenshotsText(recipe.screenshots?.join(', ') || '');
    setExpandedSections({ basic: true, install: true, meta: true, advanced: true });
    setDialogOpen(true);
  };

  const duplicateRecipe = (recipe: Recipe) => {
    setEditingRecipe(null);
    const dup = { ...recipe, id: recipe.id + '-copy', name: recipe.name + ' (Copy)', order: recipes.length };
    setFormData(dup);
    setPackagesText(dup.packages?.join(', ') || '');
    setTagsText(dup.tags?.join(', ') || '');
    setScreenshotsText(dup.screenshots?.join(', ') || '');
    setExpandedSections({ basic: true, install: true, meta: true, advanced: true });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    // Validate
    if (!formData.id.trim()) {
      toast.error(t('Recipe ID is required'));
      return;
    }
    if (!formData.name.trim()) {
      toast.error(t('Recipe name is required'));
      return;
    }
    if (!formData.categoryId) {
      toast.error(t('Category is required'));
      return;
    }

    // Check for duplicate ID on create
    if (!editingRecipe && recipes.some(r => r.id === formData.id.trim())) {
      toast.error(t('A recipe with this ID already exists'));
      return;
    }

    // Parse comma-separated fields
    const packages = packagesText.split(',').map(s => s.trim()).filter(Boolean);
    const tags = tagsText.split(',').map(s => s.trim()).filter(Boolean);
    const screenshots = screenshotsText.split(',').map(s => s.trim()).filter(Boolean);

    const recipeToSave: Recipe = {
      ...formData,
      id: formData.id.trim(),
      name: formData.name.trim(),
      description: formData.description.trim(),
      packages: formData.method === 'apt' ? packages : undefined,
      script: formData.method === 'script' ? formData.script : undefined,
      debUrl: formData.method === 'deb' ? formData.debUrl : undefined,
      tags: tags.length > 0 ? tags : undefined,
      screenshots: screenshots.length > 0 ? screenshots : undefined,
      longDescription: formData.longDescription?.trim() || undefined,
    };

    setSaving(true);
    try {
      const res = await fetch('/api/recipes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(recipeToSave),
      });

      if (res.ok) {
        toast.success(editingRecipe ? t('Recipe updated') : t('Recipe created'));
        setDialogOpen(false);
        await fetchRecipes();
      } else {
        const err = await res.text();
        toast.error(err || t('Failed to save recipe'));
      }
    } catch {
      toast.error(t('Failed to save recipe'));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      const res = await fetch(`/api/recipes/${id}`, { method: 'DELETE' });
      if (res.ok) {
        toast.success(t('Recipe deleted'));
        setDeleteConfirm(null);
        await fetchRecipes();
      } else {
        toast.error(t('Failed to delete recipe'));
      }
    } catch {
      toast.error(t('Failed to delete recipe'));
    }
  };

  // Filter recipes
  const filtered = recipes.filter(r => {
    if (filterCategory !== 'all' && r.categoryId !== filterCategory) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      return (
        r.id.toLowerCase().includes(q) ||
        r.name.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q)
      );
    }
    return true;
  });

  // Pagination
  const PAGE_SIZE = 50;
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const paginatedRecipes = useMemo(
    () => filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE),
    [filtered, safePage],
  );

  // Reset page when filters change
  useEffect(() => {
    setPage(0);
  }, [search, filterCategory]);

  const getCategoryName = (catId: string) => {
    return categories.find(c => c.id === catId)?.name || catId;
  };

  if (loading) {
    return (
      <AnimatePresence mode="wait">
        <motion.div
          key="skeleton"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <ContentSkeleton />
        </motion.div>
      </AnimatePresence>
    );
  }

  return (
    <AnimatePresence mode="wait">
    <motion.div
      key="content"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
    >
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-2xl font-bold">{t('Recipes')}</h2>
          <p className="text-muted-foreground">
            {recipes.length} {t('recipes')} {filtered.length !== recipes.length && `(${filtered.length} ${t('shown')})`}
          </p>
        </div>
        <Button onClick={openCreateDialog} className="gap-2">
          <Plus className="w-4 h-4" />
          {t('Add Recipe')}
        </Button>
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <div className="admin-search">
          <Search className="admin-search-icon" />
          <Input
            placeholder={t('Search recipes...')}
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <Select value={filterCategory} onValueChange={setFilterCategory}>
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder={t('All categories')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('All categories')}</SelectItem>
            {categories.map(cat => (
              <SelectItem key={cat.id} value={cat.id}>{cat.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Recipe list */}
      {filtered.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          <Package className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>{recipes.length === 0 ? t('No recipes yet. Create your first recipe!') : t('No recipes match your filter.')}</p>
        </div>
      ) : (
        <>
          <div className="grid gap-3">
            {paginatedRecipes.map(recipe => (
              <div key={recipe.id} className="recipe-admin-card">
                <div className="recipe-admin-card-main">
                  <div className="recipe-admin-icon">
                    <DynamicIcon name={recipe.icon} size={24} />
                  </div>
                  <div className="recipe-admin-info">
                    <div className="recipe-admin-name">
                      {recipe.name}
                      {recipe.enabled === false && <Badge variant="secondary" className="ml-2">{t('Disabled')}</Badge>}
                    </div>
                    <div className="recipe-admin-desc">{recipe.description}</div>
                    <div className="recipe-admin-meta">
                      <Badge variant="outline">{getCategoryName(recipe.categoryId)}</Badge>
                      <Badge variant="outline">{recipe.method}</Badge>
                      <Badge variant="outline">Level {recipe.level}</Badge>
                      {recipe.packages && recipe.packages.length > 0 && (
                        <span className="text-xs text-muted-foreground">{recipe.packages.length} pkgs</span>
                      )}
                    </div>
                  </div>
                  <div className="recipe-admin-actions">
                    <Button variant="ghost" size="sm" onClick={() => duplicateRecipe(recipe)} title={t('Duplicate')}>
                      <Copy className="w-4 h-4" />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => openEditDialog(recipe)} title={t('Edit')}>
                      <Edit className="w-4 h-4" />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setDeleteConfirm(recipe.id)} title={t('Delete')}>
                      <Trash2 className="w-4 h-4 text-destructive" />
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="recipe-admin-pagination">
              <Button
                variant="outline"
                size="sm"
                disabled={safePage === 0}
                onClick={() => setPage(p => p - 1)}
              >
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <span className="recipe-admin-pagination-info">
                {safePage * PAGE_SIZE + 1}–{Math.min((safePage + 1) * PAGE_SIZE, filtered.length)} / {filtered.length}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={safePage >= totalPages - 1}
                onClick={() => setPage(p => p + 1)}
              >
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          )}
        </>
      )}

      {/* Delete confirmation */}
      <Dialog open={deleteConfirm !== null} onOpenChange={() => setDeleteConfirm(null)}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t('Delete Recipe')}</DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground">
            {t('Are you sure you want to delete this recipe? This action cannot be undone.')}
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteConfirm(null)}>{t('Cancel')}</Button>
            <Button variant="destructive" onClick={() => deleteConfirm && handleDelete(deleteConfirm)}>
              {t('Delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create/Edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="dialog-wide sm:max-w-[700px] max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {editingRecipe ? t('Edit Recipe') : t('Create Recipe')}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4">
            {/* Basic Info Section */}
            <div className="admin-form-section">
              <button
                type="button"
                className="admin-form-section-header"
                onClick={() => toggleSection('basic')}
              >
                <span>{t('Basic Information')}</span>
                {expandedSections.basic ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
              {expandedSections.basic && (
                <div className="admin-form-section-body space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label>{t('Recipe ID')}</Label>
                      <Input
                        placeholder="e.g. firefox"
                        value={formData.id}
                        onChange={e => setFormData(prev => ({ ...prev, id: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-') }))}
                        disabled={!!editingRecipe}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>{t('Name')}</Label>
                      <Input
                        placeholder="e.g. Firefox"
                        value={formData.name}
                        onChange={e => setFormData(prev => ({ ...prev, name: e.target.value }))}
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label>{t('Description')}</Label>
                    <Input
                      placeholder={t('Short description...')}
                      value={formData.description}
                      onChange={e => setFormData(prev => ({ ...prev, description: e.target.value }))}
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label>{t('Category')}</Label>
                      <Select
                        value={formData.categoryId}
                        onValueChange={v => setFormData(prev => ({ ...prev, categoryId: v }))}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder={t('Select category')} />
                        </SelectTrigger>
                        <SelectContent>
                          {categories.map(cat => (
                            <SelectItem key={cat.id} value={cat.id}>{cat.name}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>{t('Icon')}</Label>
                      <IconPicker
                        value={formData.icon}
                        onChange={icon => setFormData(prev => ({ ...prev, icon }))}
                        allowEmpty={false}
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="flex items-center gap-3 pt-6">
                      <Switch
                        checked={formData.enabled !== false}
                        onCheckedChange={v => setFormData(prev => ({ ...prev, enabled: v }))}
                      />
                      <Label>{t('Enabled')}</Label>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Installation Section */}
            <div className="admin-form-section">
              <button
                type="button"
                className="admin-form-section-header"
                onClick={() => toggleSection('install')}
              >
                <span>{t('Installation')}</span>
                {expandedSections.install ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
              {expandedSections.install && (
                <div className="admin-form-section-body space-y-4">
                  <div className="grid grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label>{t('Method')}</Label>
                      <Select
                        value={formData.method}
                        onValueChange={v => setFormData(prev => ({ ...prev, method: v as InstallMethod }))}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="apt">APT</SelectItem>
                          <SelectItem value="script">Script</SelectItem>
                          <SelectItem value="deb">DEB</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>{t('Level')}</Label>
                      <Input
                        placeholder="auto"
                        value={formData.level === 'auto' ? '' : formData.level}
                        onChange={e => {
                          const val = e.target.value.trim();
                          // Empty = auto
                          if (val === '') {
                            setFormData(prev => ({ ...prev, level: 'auto' }));
                            return;
                          }
                          // Validate: 01-09
                          if (/^0[1-9]$/.test(val)) {
                            setFormData(prev => ({ ...prev, level: val as ModuleLevel }));
                          }
                        }}
                        maxLength={2}
                        title={t('01-09 or empty for auto')}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>{t('Compression')}</Label>
                      <Select
                        value={formData.compression}
                        onValueChange={v => setFormData(prev => ({ ...prev, compression: v as CompressionType }))}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {COMPRESSION_TYPES.map(c => (
                            <SelectItem key={c.value} value={c.value}>{c.value}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  {/* Method-specific fields */}
                  {formData.method === 'apt' && (
                    <div className="space-y-2">
                      <Label>{t('Packages')} <span className="text-muted-foreground text-xs">({t('comma-separated')})</span></Label>
                      <Textarea
                        placeholder="firefox-esr, firefox-esr-l10n-ru"
                        value={packagesText}
                        onChange={e => setPackagesText(e.target.value)}
                        rows={3}
                      />
                    </div>
                  )}

                  {formData.method === 'script' && (
                    <div className="space-y-2">
                      <Label>{t('Installation Script')}</Label>
                      <Textarea
                        placeholder="#!/bin/bash&#10;apt-get install -y ..."
                        value={formData.script || ''}
                        onChange={e => setFormData(prev => ({ ...prev, script: e.target.value }))}
                        rows={10}
                        className="font-mono text-sm"
                      />
                    </div>
                  )}

                  {formData.method === 'deb' && (
                    <div className="space-y-2">
                      <Label>{t('DEB URL')}</Label>
                      <Input
                        placeholder="https://example.com/package.deb"
                        value={formData.debUrl || ''}
                        onChange={e => setFormData(prev => ({ ...prev, debUrl: e.target.value }))}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Metadata Section */}
            <div className="admin-form-section">
              <button
                type="button"
                className="admin-form-section-header"
                onClick={() => toggleSection('meta')}
              >
                <span>{t('Metadata')}</span>
                {expandedSections.meta ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
              {expandedSections.meta && (
                <div className="admin-form-section-body space-y-4">
                  <div className="space-y-2">
                    <Label>{t('Tags')} <span className="text-muted-foreground text-xs">({t('comma-separated')})</span></Label>
                    <Input
                      placeholder="browser, web, internet"
                      value={tagsText}
                      onChange={e => setTagsText(e.target.value)}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label>{t('Screenshots')} <span className="text-muted-foreground text-xs">({t('comma-separated paths')})</span></Label>
                    <Input
                      placeholder="firefox-1.png, firefox-2.png"
                      value={screenshotsText}
                      onChange={e => setScreenshotsText(e.target.value)}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label>{t('Long Description')}</Label>
                    <Textarea
                      placeholder={t('Detailed description...')}
                      value={formData.longDescription || ''}
                      onChange={e => setFormData(prev => ({ ...prev, longDescription: e.target.value }))}
                      rows={4}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label>{t('Sort Order')}</Label>
                    <Input
                      type="number"
                      value={formData.order || 0}
                      onChange={e => setFormData(prev => ({ ...prev, order: parseInt(e.target.value) || 0 }))}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Advanced Section */}
            <div className="admin-form-section">
              <button
                type="button"
                className="admin-form-section-header"
                onClick={() => toggleSection('advanced')}
              >
                <span>{t('Distribution Filters')}</span>
                {expandedSections.advanced ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
              {expandedSections.advanced && (
                <div className="admin-form-section-body space-y-4">
                  <p className="text-sm text-muted-foreground">
                    {t('Leave empty to support all distributions. Each entry specifies a distribution codename and its supported architectures.')}
                  </p>

                  {/* Include list */}
                  <div className="space-y-2">
                    <Label>{t('Include Only')}</Label>
                    {(formData.distributions?.include || []).map((entry, idx) => (
                      <div key={idx} className="flex gap-2 items-center">
                        <Input
                          placeholder="bookworm"
                          value={entry.name}
                          onChange={e => {
                            const include = [...(formData.distributions?.include || [])];
                            include[idx] = { ...include[idx], name: e.target.value.trim() };
                            setFormData(prev => ({
                              ...prev,
                              distributions: { ...prev.distributions, include },
                            }));
                          }}
                          className="w-[140px]"
                        />
                        <Input
                          placeholder="amd64, i386"
                          value={entry.architectures?.join(', ') || ''}
                          onChange={e => {
                            const archs = e.target.value.split(',').map(s => s.trim()).filter(Boolean);
                            const include = [...(formData.distributions?.include || [])];
                            include[idx] = { ...include[idx], architectures: archs.length > 0 ? archs : undefined };
                            setFormData(prev => ({
                              ...prev,
                              distributions: { ...prev.distributions, include },
                            }));
                          }}
                          className="flex-1"
                        />
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            const include = (formData.distributions?.include || []).filter((_, i) => i !== idx);
                            setFormData(prev => ({
                              ...prev,
                              distributions: include.length > 0 || prev.distributions?.exclude?.length
                                ? { ...prev.distributions, include: include.length > 0 ? include : undefined }
                                : undefined,
                            }));
                          }}
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>
                    ))}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        const include = [...(formData.distributions?.include || []), { name: '' } as DistributionEntry];
                        setFormData(prev => ({
                          ...prev,
                          distributions: { ...prev.distributions, include },
                        }));
                      }}
                    >
                      <Plus className="w-3 h-3 mr-1" /> {t('Add')}
                    </Button>
                  </div>

                  {/* Exclude list */}
                  <div className="space-y-2">
                    <Label>{t('Exclude')}</Label>
                    {(formData.distributions?.exclude || []).map((entry, idx) => (
                      <div key={idx} className="flex gap-2 items-center">
                        <Input
                          placeholder="bullseye"
                          value={entry.name}
                          onChange={e => {
                            const exclude = [...(formData.distributions?.exclude || [])];
                            exclude[idx] = { ...exclude[idx], name: e.target.value.trim() };
                            setFormData(prev => ({
                              ...prev,
                              distributions: { ...prev.distributions, exclude },
                            }));
                          }}
                          className="w-[140px]"
                        />
                        <Input
                          placeholder="amd64, i386"
                          value={entry.architectures?.join(', ') || ''}
                          onChange={e => {
                            const archs = e.target.value.split(',').map(s => s.trim()).filter(Boolean);
                            const exclude = [...(formData.distributions?.exclude || [])];
                            exclude[idx] = { ...exclude[idx], architectures: archs.length > 0 ? archs : undefined };
                            setFormData(prev => ({
                              ...prev,
                              distributions: { ...prev.distributions, exclude },
                            }));
                          }}
                          className="flex-1"
                        />
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            const exclude = (formData.distributions?.exclude || []).filter((_, i) => i !== idx);
                            setFormData(prev => ({
                              ...prev,
                              distributions: exclude.length > 0 || prev.distributions?.include?.length
                                ? { ...prev.distributions, exclude: exclude.length > 0 ? exclude : undefined }
                                : undefined,
                            }));
                          }}
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>
                    ))}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        const exclude = [...(formData.distributions?.exclude || []), { name: '' } as DistributionEntry];
                        setFormData(prev => ({
                          ...prev,
                          distributions: { ...prev.distributions, exclude },
                        }));
                      }}
                    >
                      <Plus className="w-3 h-3 mr-1" /> {t('Add')}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('Cancel')}</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? t('Saving...') : editingRecipe ? t('Update') : t('Create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </div>
    </motion.div>
    </AnimatePresence>
  );
});

RecipeManager.displayName = 'RecipeManager';
